"""GPC candidate review: python -m modou.bangumi_cli --help."""
from .logging_setup import note_statistics, note_phase, note_total, logged_main, event, context, summary, logged_transaction, logged_request

import argparse
import hashlib
import json
import uuid
from http.client import IncompleteRead
from urllib.error import HTTPError
from pathlib import Path
from urllib.request import Request
from .http_transport import direct_urlopen as urlopen

from sqlalchemy import create_engine, text

from .bangumi import AnonymousAPI, LocalDump, normalized, resolve, valid_product_link
from .catalog_memory import test_database_url
from .local_config import read_config, read_max_output_tokens
from .models import GPC_TYPES


def guard(conn):
    if conn.scalar(text('select current_database()')) != 'modou_test':
        raise ValueError('仅允许modou_test')
    if conn.scalar(text('select version_num from alembic_version')) not in ('0006', '0007', '0008', '0009', '0010', '0011', '0012', '0013', '0014', '0015', '0016', '0017'):
        raise ValueError('需要0006 GPC结构')


def engine_for(values):
    return create_engine(test_database_url(values), connect_args={'dbname': 'modou_test', 'connect_timeout': 8})


def ai_client(values):
    key = values.get('DEEPSEEK_API_KEY')
    if not key:
        raise ValueError('缺少DeepSeek密钥')
    max_output_tokens = read_max_output_tokens()
    interactions = []
    @logged_request("DeepSeek")
    def suggest(context):
        from .ai_prompts import prompt
        instructions, user_text = prompt(context)
        payload = {'model': values.get('DEEPSEEK_MODEL', 'deepseek-flash'),
                   'response_format': {'type': 'json_object'}, 'max_tokens': max_output_tokens,
                   'messages': [
                       {'role': 'system', 'content': instructions},
                       {'role': 'user', 'content': user_text}]}
        request = Request('https://api.deepseek.com/chat/completions', data=json.dumps(payload).encode(),
                          headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        record = {'call_id': uuid.uuid4().hex, 'system': instructions,
                  'user': payload['messages'][1]['content'], 'raw_response': None,
                  'content': None, 'status': 'pending', 'error': None}
        interactions.append(record)
        try:
            try:
                with urlopen(request, timeout=30) as response:
                    raw = response.read()
            except IncompleteRead as exc:
                record['raw_response'] = exc.partial.decode('utf-8', errors='replace') if isinstance(exc.partial, bytes) else exc.partial
                raise
            except HTTPError as exc:
                raw = exc.read()
                record['raw_response'] = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
                raise
            record['raw_response'] = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
            data = json.loads(record['raw_response'])
            choice = data['choices'][0]
            record['content'] = choice['message']['content']
            if choice['finish_reason'] != 'stop':
                raise ValueError('AI响应不完整')
            result = json.loads(record['content'])
            if not isinstance(result, dict):
                raise ValueError('AI响应不是对象')
            if 'items' in context and not isinstance(result.get('results'), list):
                raise ValueError('缺少批量results数组')
            if 'items' not in context and context.get('task') not in ('gamefaqs', 'main_subject') and 'candidate' not in result:
                raise ValueError('缺少候选标识')
            record['status'] = 'received'
            return result
        except Exception as exc:
            record['status'] = 'failed'
            record['error'] = ('未收到响应正文；' if record['raw_response'] is None else '已收到响应正文；') + type(exc).__name__
            raise
    suggest.interactions = interactions
    return suggest


def write_review(path, rows):
    payload = json.dumps(rows, ensure_ascii=False, indent=2)
    content = ('# Bangumi名称审核\n\n仅modou_test；本文件生成时未写业务数据库。\n'
               '逐条编辑下方JSON：status填confirmed或rejected；pending不得导入。\n'
               '确认条目必须填写final；gpc_id用于已有GPC，否则填写name_zh、name_en、bangumi_id、bangumi_main；type可选填Base/rebase/Expansion/母子集/合集，未知填null。\n'
               '无Bangumi对应条目时bangumi_id可为null；final.outlink为人工核实后的GameFAQs产品链接或null。主子关系必须人工核实。\n'
               '本入口只导入GPC及别名，不导入报价。\n\n```json\n' + payload + '\n```\n')
    with path.open('x', encoding='utf-8') as stream:
        stream.write(content)


def read_review(path):
    content = path.read_text(encoding='utf-8')
    if content.count('```json\n') != 1 or content.count('```') != 2:
        raise ValueError('需要唯一JSON审核块')
    rows = json.loads(content.split('```json\n', 1)[1].split('```', 1)[0])
    return validate_rows(rows)


def validate_rows(rows):
    from .outlinks import upgrade_outlinks
    # Keep the caller's row objects: downstream writers consume these same rows.
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                upgraded = upgrade_outlinks(row)
                row.clear()
                row.update(upgraded)
    if not isinstance(rows, list) or not rows:
        raise ValueError('审核条目不能为空')
    for row in rows:
        if row.get('status') not in ('confirmed', 'rejected'):
            raise ValueError('仍有未审核条目')
        if row['status'] == 'confirmed':
            final = row.get('final')
            if not isinstance(final, dict) or not isinstance(row.get('raw_name'), str) or not row['raw_name'].strip():
                raise ValueError('缺少审核字段')
            from .blacklist import is_blacklisted
            if is_blacklisted(row):
                raise ValueError('黑名单条目不可入库')
            if not final.get('gpc_id') and not str(final.get('name_zh') or '').strip():
                raise ValueError('缺少中文标准名')
            if final.get("type") is not None and (not isinstance(final["type"], str) or final["type"] not in GPC_TYPES):
                raise ValueError("type必须为Base/rebase/Expansion/母子集/合集或null")
            if final.get('outlink') is not None and not valid_product_link(final['outlink']):
                raise ValueError('外链必须是有效的HTTP/HTTPS URL')
            from .main_ids import normalize_main
            if 'bangumi_main' in final:
                final['bangumi_main'] = normalize_main(final['bangumi_main'])
            for field in ('bangumi_id',):
                value = final.get(field)
                if value is not None and (not isinstance(value, str) or not value.isascii() or not value.isdigit()):
                    raise ValueError('Bangumi ID必须为数字字符串或null')
    return rows


def import_review(conn, rows, *, source_id=None):
    validate_rows(rows)
    guard(conn)
    if conn.scalar(text('select version_num from alembic_version')) in ('0010', '0011', '0012'):
        raise ValueError('入库需要0013来源结构')
    if conn.scalar(text('select version_num from alembic_version')) in ('0013', '0014', '0015', '0016', '0017'):
        from .catalog_import import import_catalog_0010
        return import_catalog_0010(conn, rows, source_id=source_id)
    # Serialize concurrent catalog imports; all writes belong to caller's transaction.
    conn.execute(text('LOCK TABLE game_product_config, game_alias IN SHARE ROW EXCLUSIVE MODE'))
    imported = []
    for row in rows:
        if row['status'] == 'rejected':
            continue
        final = row['final']
        gpc_id = final.get('gpc_id')
        product_type = final.get('type')
        if final.get('outlink') is not None and conn.scalar(text('select version_num from alembic_version')) == '0006':
            raise ValueError('outlink需要0007或0008结构')
        if product_type is not None:
            if conn.scalar(text('select version_num from alembic_version')) not in ('0008', '0009'):
                raise ValueError('type需要0008结构')
            existing_type = conn.scalar(text('select type from game_product_config where gpc_id=:id'), {'id': gpc_id}) if gpc_id else None
            if gpc_id and existing_type != product_type:
                raise ValueError('已有GPC类型不一致；本入口不覆盖目录')
        if gpc_id:
            if not conn.scalar(text('select gpc_id from game_product_config where gpc_id=:id'), {'id': gpc_id}):
                raise ValueError('已有GPC不存在')
        else:
            existing = conn.execute(text('select * from game_product_config where bangumi_id=:id'),
                                    {'id': final.get('bangumi_id')}).mappings().first()
            if existing:
                if any(existing[k] != final.get(k) for k in ('name_zh', 'name_en', 'bangumi_main')):
                    raise ValueError('同Subject已有不同资料，请审核时指定gpc_id')
                if product_type is not None and existing['type'] != product_type:
                    raise ValueError('同Subject已有不同类型；本入口不覆盖目录')
                gpc_id = existing['gpc_id']
            else:
                fields = ['name_zh', 'name_en', 'bangumi_id', 'bangumi_main']
                if final.get('outlink') is not None:
                    fields.append('outlink')
                if product_type is not None:
                    fields.append('type')
                gpc_id = conn.scalar(text('INSERT INTO game_product_config(' + ','.join(fields) + ') VALUES (' +
                                         ','.join(':' + k for k in fields) + ') RETURNING gpc_id'),
                                     {k: final.get(k) for k in fields})
        if 'outlink' in final and final['outlink'] is not None:
            current_link = conn.scalar(text('select outlink from game_product_config where gpc_id=:id'), {'id': gpc_id})
            if current_link is not None and current_link != final['outlink']:
                raise ValueError('已有GPC的GameFAQs链接冲突；本入口不覆盖目录')
            conn.execute(text('UPDATE game_product_config SET outlink=:link WHERE gpc_id=:id'), {'link': final['outlink'], 'id': gpc_id})
        conn.execute(text('INSERT INTO game_alias(gpc_id,alias) VALUES (:id,:alias) ON CONFLICT DO NOTHING'),
                     {'id': gpc_id, 'alias': row['raw_name']})
        imported.append(gpc_id)
    return imported


@logged_main
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['review', 'import'])
    parser.add_argument('input', type=Path, help='review: JSON数组，每项raw_name及note；import:已审核Markdown')
    parser.add_argument('--output-dir', type=Path, default=Path('outputs/bangumi-review'))
    parser.add_argument('--dump-dir', type=Path, default=Path('data/bangumi_locale'))
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    parser.add_argument('--deepseek', action='store_true')
    args = parser.parse_args()
    event("输入", input=str(getattr(args, "input", getattr(args, "manifest", "-"))))
    with note_statistics(args.input, enabled=args.action == 'review'):
        values = read_config(args.env_file)
        rows = read_review(args.input) if args.action == 'import' else json.loads(args.input.read_text(encoding='utf-8-sig'))
        engine = engine_for(values)
        try:
            if args.action == 'import':
                with logged_transaction(engine) as conn:
                    ids = import_review(conn, rows)
                    event("导入条目完成（待提交）", count=len(ids))
                print(json.dumps({'database': 'modou_test', 'imported_gpc_ids': ids}))
                return
            if not rows or any(not isinstance(r.get('raw_name'), str) or not r['raw_name'].strip() or not isinstance(r.get('note'), str) for r in rows):
                raise ValueError('每项必须提供名称与原始笔记')
            note_total(len(rows))
            with note_phase("本地查询"):
                with engine.connect() as conn:
                    conn.execute(text('SET TRANSACTION READ ONLY'))
                    guard(conn)
                    aliases = list(conn.execute(text('select a.alias,g.* from game_alias a join game_product_config g using(gpc_id)')).mappings())
                dump = LocalDump(args.dump_dir)
                needed = [r['raw_name'] for r in rows if not any(a['gpc_id'] == -1 and normalized(a['alias']) == normalized(r['raw_name']) for a in aliases) and len({a['gpc_id'] for a in aliases if normalized(a['alias']) == normalized(r['raw_name'])}) != 1]
                local = dump.lookup_many(needed) if needed else {}
            api = AnonymousAPI()
            suggest = ai_client(values) if args.deepseek else None
            from .main_subject import MainSubjects
            from .product_type import ProductTypes
            main_subjects = MainSubjects(dump.path, api)
            product_types = ProductTypes()
            results = []
            for index, row in enumerate(rows, 1):
                result = resolve(row['raw_name'], row['note'], aliases, local.get(normalized(row['raw_name']), []), api, suggest, note_id=args.input, line_number=index)
                result['dump'] = dump.path.name
                chosen = next((result['stage_hits'][s] for s in ('gamefaqs', 'ds', 'api', 'local', 'alias') if s in result['stage_hits']), {})
                result['main_resolution'] = main_subjects.resolve(chosen)
                result['type_resolution'] = product_types.resolve(chosen, result['main_resolution'], raw_name=row['raw_name'], note=row['note'])
                result['ai_interactions'].extend(result['type_resolution'].get('interactions', []))
                result['final'] = {'gpc_id': None, 'name_zh': None, 'name_en': None, 'bangumi_id': None, 'bangumi_main': None, 'type': None, 'outlink': (result.get('gamefaqs_suggestion') or {}).get('outlink')}
                result['final']['type'] = result['type_resolution']['type']
                results.append(result)
            with context(note_id=str(args.input)):
                summary(["已识别" if r["source"] == "alias" or len(r["candidates"]) == 1 or bool(r["stage_hits"]) else "歧义" if r["candidates"] else "未识别" for r in results])
            with note_phase("输出"):
                args.output_dir.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256(json.dumps(results, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:6]
                output = args.output_dir / ('Bangumi审核_' + digest + '.md')
                write_review(output, results)
                event("审核文件生成", path=str(output))
                print(str(output))
        finally:
            engine.dispose()


if __name__ == '__main__':
    main()
