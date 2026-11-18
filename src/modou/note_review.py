"""Real-note GPC review and explicit test-only atomic import."""
from .logging_setup import note_statistics, note_phase, note_total, logged_main, event, context, summary, logged_transaction

import argparse
import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from .bangumi import AnonymousAPI, LocalDump, normalized, resolve, supports_ps_disc
from .bangumi_cli import ai_client, engine_for, guard, import_review, read_review, write_review
from .local_config import read_config
from .observations import save_observation, get_or_create_source
from .publication_date import infer_publication_date
from .parsing import parse_note, read_note


class ApprovedQuote(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=False)
    source_path: str = Field(min_length=1)
    published_at: date | None = None
    platform: str = Field(min_length=1)
    region: str = Field(min_length=1)
    lowprice_cny: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    lowprice_method: str = Field(min_length=1)
    lowprice_date: date


def identify_query(item):
    # Edition remains part of the query. +DLC can be a real title: never strip it.
    return re.sub(r'\s*(?<![A-Za-z0-9])(PS5|PS4)(?![A-Za-z0-9])\s*', '', item.raw_name, flags=re.I).strip()


def build_review(note, source_path, published, aliases, local, api, suggest=None, *, only_line=None, on_row=None, on_total=None):
    title = note.splitlines()[0] if note.splitlines() else ''
    titles = [title] if str(source_path).startswith(('http://', 'https://')) else [title, Path(source_path).stem]
    published = published if published is not None else infer_publication_date(str(source_path), title)
    ps_disc = any('PS' in t.upper() and '光盘' in t.upper() for t in titles)
    aliases = [a for a in aliases if a.get('gpc_id') == -1 or supports_ps_disc(a)] if ps_disc else aliases
    parsed = parse_note(note, published_date=published, source_url=None, log_results=False)
    if only_line is not None:
        parsed.items = [item for item in parsed.items if item.line_number == only_line]
    if on_total is not None:
        on_total(len(parsed.items))
    queries = [identify_query(item) for item in parsed.items]
    needed = [q for q in queries if not any(a['gpc_id'] == -1 and normalized(a['alias']) == normalized(q) for a in aliases) and len({a['gpc_id'] for a in aliases if normalized(a['alias']) == normalized(q)}) != 1]
    note_total(len(parsed.items))
    with note_phase("本地查询"):
        matches = local.lookup_many(needed) if needed else {}
    from .main_subject import MainSubjects
    main_subjects = MainSubjects(local.path, api)
    from .product_type import ProductTypes
    product_types = ProductTypes()
    rows = []
    def resolve_items():
        pairs = list(zip(parsed.items, queries))
        for start in range(0, len(pairs), 10):
            group = pairs[start:start + 10]
            initial = [resolve(query, item.raw_line, aliases, matches.get(normalized(query), []), api,
                               suggest if only_line is not None else None,
                               note_id=source_path, line_number=item.line_number, ps_disc=ps_disc, defer_ai=only_line is None)
                       for item, query in group]
            if only_line is None:
                from .ai_batch import resolve_group
                initial = resolve_group(initial, suggest, api, start + 1)
            else:
                for row in initial:
                    row['ai_mode'] = 'single'
            yield from ((item, query, resolution) for (item, query), resolution in zip(group, initial))
    for item, query, resolution in resolve_items():
        resolution['raw_name'] = query
        selected = next((v for v in resolution.get('stage_hits', {}).values() if v.get('id') or v.get('bangumi_id')), {})
        resolution['main_resolution'] = ({'status': 'blacklisted', 'main_id': None} if resolution.get('blacklisted') else resolution.get('main_resolution') or main_subjects.resolve(selected))
        type_selected = selected or resolution.get('gamefaqs_suggestion') or {}
        resolution['type_resolution'] = ({'status': 'blacklisted', 'type': None} if resolution.get('blacklisted') else product_types.resolve(type_selected, resolution['main_resolution'], raw_name=query, note=item.raw_line))
        resolution.setdefault('ai_interactions', []).extend(resolution['type_resolution'].get('interactions', []))
        if resolution['main_resolution']['status'] in ('unknown', 'failed', 'conflict'):
            resolution['errors'].append('主游戏归属待确认：' + resolution['main_resolution']['status'])
        resolution['extracted'] = item.model_dump(mode='json')
        resolution['dump'] = local.path.name
        resolution['parse_warnings'] = [e for e in parsed.validation_errors if not e.startswith('来源链接')]
        resolution['final'] = {'gpc_id': None, 'name_zh': None, 'name_en': None,
                               'bangumi_id': None, 'bangumi_main': None, 'type': resolution['type_resolution']['type'], 'outlink': (resolution.get('gamefaqs_suggestion') or {}).get('outlink')}
        resolution['quote'] = {'source_path': source_path, 'published_at': published.isoformat() if published else None,
                               **{k: item.model_dump(mode='json')[k] for k in
                                  ('platform', 'region', 'lowprice_cny', 'lowprice_method', 'lowprice_date')}}
        from .review_table import quote_platform
        resolution['quote']['platform'] = quote_platform(resolution)
        resolution['extracted']['platform'] = resolution['quote']['platform']
        rows.append(resolution)
        if on_row is not None:
            on_row(resolution)
    if not rows:
        raise ValueError('未识别到报价行，请检查笔记格式')
    with context(note_id=str(source_path)):
        summary(["已识别" if r["source"] == "alias" or len(r["candidates"]) == 1 or bool(r["stage_hits"]) else "歧义" if r["candidates"] else "未识别" for r in rows])
    return rows


def import_quotes(conn, rows):
    # Validate every quote before the first write, including rows later in the batch.
    from .bangumi_cli import validate_rows
    validate_rows(rows)
    approved = [(row, ApprovedQuote.model_validate(row.get('quote'))) for row in rows if row['status'] == 'confirmed']
    guard(conn)
    if conn.dialect.name == 'postgresql':
        conn.execute(text('LOCK TABLE data_source, game_product_config, game_alias, m_low_record IN SHARE ROW EXCLUSIVE MODE'))
    records = []
    sources = {}
    with Session(bind=conn) as session:
        for row, quote in approved:
            from .web.duplicates import existing_quote
            duplicate = existing_quote(conn, row, require_complete=False)
            if duplicate:
                records.append(duplicate['record_id'])
                continue
            key = (quote.source_path, quote.published_at)
            if key not in sources:
                sources[key] = get_or_create_source(session, *key).sources_id
            source_id = sources[key]
            gpc_id = import_review(conn, [row], source_id=source_id)[0]
            record = save_observation(session, gpc_id=gpc_id, source_id=source_id, **quote.model_dump())
            records.append(record.record_id)
        session.flush()
    return records


@logged_main
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['review', 'import'])
    parser.add_argument('input', type=Path, help='review: UTF8/UTF16笔记TXT；import:已审核Markdown')
    parser.add_argument('--date', type=date.fromisoformat)
    parser.add_argument('--source-path', help='URL或本地来源路径，默认笔记路径')
    parser.add_argument('--dump-dir', type=Path, default=Path('data/bangumi_locale'))
    parser.add_argument('--output-dir', type=Path, default=Path('outputs/note-review'))
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    parser.add_argument('--deepseek', action='store_true')
    args = parser.parse_args()
    event("输入", input=str(getattr(args, "input", getattr(args, "manifest", "-"))))
    with note_statistics(args.input, enabled=args.action == 'review'):
        values = read_config(args.env_file)
        rows = read_review(args.input) if args.action == 'import' else None
        engine = engine_for(values)
        try:
            if rows is not None:
                with logged_transaction(engine) as conn:
                    ids = import_quotes(conn, rows)
                    event("导入条目完成（待提交）", count=len(ids))
                print(json.dumps({'database': 'modou_test', 'record_ids': ids}))
                return
            note = read_note(args.input)
            with note_phase("本地查询"):
                with engine.connect() as conn:
                    conn.execute(text('SET TRANSACTION READ ONLY'))
                    guard(conn)
                    aliases = list(conn.execute(text('select a.alias,g.* from game_alias a join game_product_config g using(gpc_id)')).mappings())
            rows = build_review(note, args.source_path or args.input.as_posix(), args.date, aliases,
                                LocalDump(args.dump_dir), AnonymousAPI(), ai_client(values) if args.deepseek else None)
            with note_phase("输出"):
                args.output_dir.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:6]
                path = args.output_dir / ('笔记审核_' + digest + '.md')
                write_review(path, rows)
                # The same editable JSON contract as catalog review, with a separate approved quote.
                content = path.read_text(encoding='utf-8').replace('本入口只导入GPC及别名，不导入报价。',
                            '本文件包含报价。人工核对quote全部字段，确认后用note_review import整批事务导入；extracted仅为原始解析证据。')
                from .review_table import render_review
                content = render_review(rows) + '\n' + content
                path.write_text(content, encoding='utf-8')
                event("审核文件生成", path=str(path))
                from .review_html import write_html
                html_path = write_html(rows, args.source_path or args.input.as_posix(), note.splitlines()[0], args.output_dir)
                event("HTML审核文件生成", path=str(html_path))
                print(html_path)
        finally:
            engine.dispose()


if __name__ == '__main__':
    main()
