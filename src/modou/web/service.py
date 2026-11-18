"""Application use cases; raw parse evidence is never overwritten by edits."""
import copy
from datetime import date, datetime, timezone
from time import perf_counter
from .store import display_filename
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from ..bangumi import AnonymousAPI, LocalDump, english_name
from ..bangumi_cli import ai_client, engine_for, guard, validate_rows
from ..catalog_import import import_catalog_0010
from ..local_config import read_config
from ..logging_setup import note_statistics, event
from ..models import GameProductConfig, GPC_TYPES
from ..note_review import build_review, ApprovedQuote
from ..observations import save_observation, get_or_create_source
from ..parsing import read_note
from ..review_table import stage_hits, STAGES
from ..web_review import eligibility_errors
from .links import suggest_main, subject
from .duplicates import existing_quote, similar_products, mark_duplicates, SimilarProducts

GPC_FIELDS = ('name_zh', 'name_en', 'bangumi_id', 'bangumi_main', 'type', 'note', 'display_name', 'outlink')
EDIT_FIELDS = (*GPC_FIELDS, 'gpc_id')
QUOTE_FIELDS = ('platform', 'region', 'lowprice_cny', 'lowprice_method', 'lowprice_date')
ERROR_COLUMNS = {'命中目标待确认': 1, '游戏名称待确认': 1, 'main待确认': 2,
                 'type待确认': 3, '平台待确认': 4, '地区待确认': 5,
                 '价格无效': 6, '优惠方式待确认': 7}


def _field_value(group, key, value):
    if key in ('gpc_id', 'bangumi_id', 'bangumi_main'):
        return str(value) if value is not None else None
    if group == 'quote' and key == 'lowprice_cny':
        from decimal import Decimal, InvalidOperation
        try:
            number = Decimal(str(value))
            return number if number.is_finite() else str(value)
        except InvalidOperation:
            return value
    if key in ('note', 'display_name', 'name_en', 'outlink'):
        return value or None
    return value


def _target(final):
    if final.get('bangumi_id') or final.get('outlink'):
        return (str(final.get('bangumi_id') or ''), final.get('outlink') or '')
    return ('gpc', str(final['gpc_id'])) if final.get('gpc_id') else None


def alias_bound(row):
    """A selected alias target inherits its saved GPC fields and platform."""
    hit = stage_hits(row).get('alias') or {}
    final = row.get('final') or {}
    return bool(hit.get('gpc_id') and str(hit['gpc_id']) == str(final.get('gpc_id'))
                and _target(hit) == _target(final))


def normalize_draft(row):
    """Repair known old parser defaults without replacing manual values/evidence."""
    for state in (row, row.get('parse_baseline') or {}):
        q = state.get('quote') or {}
        if q.get('lowprice_method') == '':
            q['lowprice_method'] = '直接购买'
    if row.get('imported') or row.get('already_imported') or row.get('manual_gamefaqs'):
        return
    final = row.get('final') or {}
    baseline = row.get('parse_baseline') or {}
    manual = set(row.get('manual_fields') or [])
    def untouched(key):
        return 'final.' + key not in manual and (not baseline or final.get(key) == baseline.get('final', {}).get(key))
    if final.get('type') is not None and final.get('type') not in GPC_TYPES and untouched('type'):
        value = (row.get('type_resolution') or {}).get('type')
        final['type'] = value if value in GPC_TYPES else None
        if baseline.get('final') is not None:
            baseline['final']['type'] = final['type']
    candidates = list((row.get('stage_hits') or {}).values()) + list(row.get('candidates') or [])
    chosen = next((c for c in candidates if str(c.get('bangumi_id') or c.get('id') or '') == str(final.get('bangumi_id'))), None)
    if chosen and not final.get('gpc_id') and untouched('name_en') and (not final.get('name_en') or final.get('name_en') == chosen.get('name')):
        final['name_en'] = english_name(chosen)
        if baseline.get('final') is not None:
            baseline['final']['name_en'] = final['name_en']


def refresh_review_state(row):
    """Presentation history is separate from current approval eligibility."""
    normalize_draft(row)
    ensure_baseline(row)
    baseline = row['parse_baseline']
    if not (baseline.get('final') or {}).get('name_en'):
        row['name_en_unknown'] = True
    red = set()  # Baseline problems persist; transient edit problems do not.
    for state in (baseline, row):
        red.update(ERROR_COLUMNS[e] for e in eligibility_errors(state) if e in ERROR_COLUMNS)
    if row.get('main_explicit_null') and row['final'].get('bangumi_main') is None:
        red.discard(2)
    row['red_columns'] = sorted(red)
    row['manual_fields'] = sorted(
        group + '.' + key
        for group, keys in (('final', EDIT_FIELDS), ('quote', QUOTE_FIELDS))
        for key in keys
        if _field_value(group, key, row.get(group, {}).get(key)) !=
           _field_value(group, key, baseline.get(group, {}).get(key)))
    if bool(row.get('main_explicit_null')) != bool(baseline.get('main_explicit_null')):
        row['manual_fields'] = sorted(set(row['manual_fields']) | {'final.bangumi_main'})
    row['manual_target'] = _target(row['final']) != _target(baseline['final'])



def prepare_row(row, values, *, suggest_missing=True):
    row = copy.deepcopy(row)
    hits = stage_hits(row)
    chosen = next((hits[s] for s in reversed(STAGES) if s in hits), {})
    final = {k: chosen.get(k) for k in EDIT_FIELDS}
    final['name_zh'] = chosen.get('name_zh') or chosen.get('name_cn') or chosen.get('name')
    final['name_en'] = english_name(chosen)
    final['bangumi_id'] = str(chosen.get('bangumi_id') or chosen.get('id')) if chosen.get('bangumi_id') or chosen.get('id') else None
    if not chosen.get('gpc_id') or final.get('type') not in GPC_TYPES:
        value = (row.get('type_resolution') or {}).get('type')
        final['type'] = value if value in GPC_TYPES else None
    resolution = row.get('main_resolution') or {}
    final['bangumi_main'] = final.get('bangumi_main') or resolution.get('main_id')
    # A reviewed product's saved NULL is authoritative; do not replace it with self.
    row['main_explicit_null'] = bool(chosen.get('gpc_id') and 'bangumi_main' in chosen and chosen['bangumi_main'] is None)
    if row['main_explicit_null']:
        final['bangumi_main'] = None
    # Deprecated 2026-11-19 (6d8b20f4): GameFAQs automatic AI identification.
    #     if suggest_missing and not row.get('ai_main_attempted') and chosen.get('outlink') and not final.get('bangumi_main'):
    #         resolution = suggest_main(chosen, values)
    #         row['main_resolution'] = resolution
    #         row.setdefault('ai_interactions', []).extend(resolution.get('interactions', []))
    #         final['bangumi_main'] = resolution.get('main_id')
    row['final'] = final
    row['gpc_baseline'] = {k: chosen.get(k) for k in GPC_FIELDS if k not in ('bangumi_id', 'outlink')} if chosen.get('gpc_id') else None
    row['parse_baseline'] = copy.deepcopy({k: row.get(k) for k in ('final', 'quote', 'gpc_baseline', 'type_resolution', 'gamefaqs_display_name', 'main_explicit_null')})
    row['selected'] = False
    row['imported'] = False
    if chosen.get('gpc_id') == -1:
        from ..blacklist import mark_blacklisted
        mark_blacklisted(row)
    row['revision'] = 0
    row['red_columns'] = []
    refresh_review_state(row)
    return row


def parse_job(store, key, path, dump_dir):
    started = perf_counter()
    pending = []
    def update(fn):
        # Parse publication never invalidates approval revisions: only append rows
        # and change parse metadata while holding the same lock as manual edits.
        with store.lock:
            latest = store.read(key)
            fn(latest)
            latest['parse_revision'] = latest.get('parse_revision', 0) + 1
            store.write(latest)
            return latest
    def publish(state=None):
        def change(b):
            for row in pending:
                if b.get('review_date'):
                    row['quote'].update(published_at=b['review_date'], lowprice_date=b['review_date'])
                b['rows'].append(row)
            if state:
                b['state'] = state
            elif b['rows']:
                b['state'] = 'reviewable'
            b['parse_elapsed_seconds'] = max(0, perf_counter() - started)
            if state == 'ready':
                b['parse_finished_at'] = datetime.now(timezone.utc).isoformat()
        update(change)
        pending.clear()
    try:
        batch = update(lambda b: b.update(state='parsing', parse_started_at=datetime.now(timezone.utc).isoformat()))
        values = read_config()
        engine = engine_for(values)
        try:
            with engine.connect() as conn:
                conn.execute(text('SET TRANSACTION READ ONLY'))
                guard(conn)
                aliases = [dict(r) for r in conn.execute(text('select a.alias,g.* from game_alias a join game_product_config g using(gpc_id)')).mappings()]
        finally:
            engine.dispose()
        def completed(row):
            pending.append(prepare_row(row, values))
            if len(pending) >= 10:
                publish()
        with note_statistics(path):
            build_review(read_note(path), batch['source_path'], None, aliases,
                         LocalDump(dump_dir), AnonymousAPI(), ai_client(values), on_row=completed,
                         on_total=lambda total: update(lambda b: b.update(total_rows=total)))
        publish('ready')
    except Exception as exc:
        event('网页解析失败', reason=type(exc).__name__)
        def fail(b):
            b['parse_finished_at'] = datetime.now(timezone.utc).isoformat()
            b['parse_elapsed_seconds'] = max(0, perf_counter() - started)
            b.update(state='failed', error='解析失败：' + type(exc).__name__ + '；已发布条目保留，请检查日志、配置与笔记格式')
        update(fail)


def public_batch(batch):
    result = copy.deepcopy(batch)
    result['display_filename'] = display_filename(batch)
    for row in result['rows']:
        refresh_review_state(row)
        row['alias_bound'] = alias_bound(row)
        row['eligibility_errors'] = eligibility_errors(row)
    return result


def edit_row(batch, index, payload, *, candidate_change=False):
    if batch['state'] not in ('ready', 'reviewable', 'failed'):
        raise ValueError('批次尚未解析完成')
    row = batch['rows'][index]
    if row['imported'] or row.get('already_imported'):
        raise ValueError('已入库条目不能修改')
    if row.get('selected'):
        raise ValueError('请先取消勾选，再修改条目')
    final, quote = payload.get('final', {}), payload.get('quote', {})
    if str(final.get('gpc_id')) == '-1':
        raise ValueError('请使用黑名单专用按钮')
    if alias_bound(row) and not candidate_change:
        if quote or set(final) - {'note', 'display_name', 'bangumi_main'}:
            raise ValueError('别名库命中时仅可修改命中备注/显示名及main；更换产品请使用候选或产品URL')
    if set(final) - set(EDIT_FIELDS) or set(quote) - set(QUOTE_FIELDS):
        raise ValueError('包含不可编辑字段')
    if any(v is not None and not isinstance(v, str) for k, v in final.items() if k != 'gpc_id'):
        raise ValueError('字段必须是文字或空值')
    explicit_null = row.get('main_explicit_null', False)
    if 'bangumi_main' in final:
        from ..main_ids import normalize_main
        raw_main = final['bangumi_main']
        explicit_null = bool(isinstance(raw_main, str) and raw_main.isspace())
        if candidate_change and raw_main is None:
            explicit_null = bool(row.get('main_explicit_null') or (final.get('gpc_id') and 'bangumi_main' in final))
        final = dict(final, bangumi_main=normalize_main(raw_main))
    if final.get('outlink') is not None:
        from ..bangumi import valid_product_link
        if not valid_product_link(final['outlink']):
            raise ValueError('外链必须是有效的HTTP/HTTPS URL')
    changed = any(row['final'].get(k) != v for k, v in final.items()) or any(row['quote'].get(k) != v for k, v in quote.items())
    if payload.get('manual_resolution') is not None:
        row.setdefault('manual_resolutions', []).append(copy.deepcopy(payload['manual_resolution']))
    refresh_review_state(row)
    row['final'].update(final)
    row['main_explicit_null'] = explicit_null
    if row.get('gamefaqs_display_name') and row['final'].get('outlink') and 'display_name' in final:
        if not str(final['display_name'] or '').strip():
            raise ValueError('外链显示名不能为空')
        row['final']['name_zh'] = final['display_name'].strip()
        row['final']['display_name'] = final['display_name'].strip()
    manual_candidate = (payload.get('manual_resolution') or {}).get('candidate') or {}
    if manual_candidate.get('outlink'):
        name = str(final.get('display_name') or '').strip()
        if not name:
            raise ValueError('请输入外链display name')
        row['gamefaqs_display_name'] = True
        row['final'].update(name_zh=name, display_name=name)
    elif any(k in final for k in ('gpc_id', 'bangumi_id', 'outlink')):
        row.pop('gamefaqs_display_name', None)
    if payload.get('manual_resolution') is not None:
        row['type_resolution'] = copy.deepcopy(payload['manual_resolution'].get('type_resolution') or {})
    if not row['final'].get('gpc_id'):
        row['gpc_baseline'] = None
    row['quote'].update(quote)
    refresh_review_state(row)
    row['selected'] = False if changed else row['selected']
    row['revision'] += 1
    row['status'] = 'pending'


def select_row(batch, index, selected):
    row = batch['rows'][index]
    if row['imported'] or row.get('already_imported') or (selected and eligibility_errors(row)):
        raise ValueError('条目尚未满足审核条件，或已经入库')
    row['selected'] = selected


def commit_rows(conn, rows, *, confirmations=(), review_batch_id=None, batch_created_at=None):
    """Caller owns the transaction. Validate all selected rows before any write."""
    validate_rows(rows)
    approved = []
    for row in rows:
        errors = eligibility_errors(row)
        if errors:
            raise ValueError('；'.join(errors))
        approved.append(ApprovedQuote.model_validate(row['quote']))
    if conn.dialect.name == 'postgresql':
        conn.execute(text('LOCK TABLE data_source, game_product_config, game_alias, m_low_record IN SHARE ROW EXCLUSIVE MODE'))
    # Check every proposed insert before the first write, then recheck under locks.
    conflicts = similar_products(conn, rows)
    if any(c['token'] not in confirmations for c in conflicts):
        raise SimilarProducts(conflicts)
    # Reject conflicting edits of shared products before updating anything.
    edits = {}
    for row in rows:
        f = row['final']
        identity = ('id', f['gpc_id']) if f.get('gpc_id') else ('new', f.get('bangumi_id'), row['quote']['platform'], f.get('outlink'))
        fields = {k: f.get(k) for k in GPC_FIELDS}
        if identity in edits and edits[identity] != fields:
            raise ValueError('同一GPC存在冲突修改')
        edits[identity] = fields
    results = []
    sources = {}
    for row, quote in zip(rows, approved):
        duplicate = existing_quote(conn, row)
        if duplicate:
            results.append(duplicate)
            continue
        f = row['final']
        identity = ('id', f['gpc_id']) if f.get('gpc_id') else ('new', f.get('bangumi_id'), row['quote']['platform'], f.get('outlink'))
        from .proposals import proposed_inserts
        added = [p['table'] for p in proposed_inserts(conn, row)]
        with Session(bind=conn) as session:
            key = (quote.source_path, quote.published_at)
            if key not in sources:
                sources[key] = get_or_create_source(session, *key, review_batch_id=review_batch_id,
                                                    recorded_at=batch_created_at).sources_id
            source_id = sources[key]
            gpc_id = import_catalog_0010(conn, [row], allow_updates=True, source_id=source_id)[0]
            record = save_observation(session, gpc_id=gpc_id, source_id=source_id, **quote.model_dump())
            results.append({'gpc_id': gpc_id, 'record_id': record.record_id, 'added': added})
    return results


def commit_batch(batch, confirmations=(), *, index=None, indices=None):
    selected = [r for i, r in enumerate(batch['rows']) if (i in indices if indices is not None else r['selected'] if index is None else i == index) and not r['imported'] and not r.get('already_imported')]
    if not selected:
        if any(r.get('already_imported') for r in batch['rows']):
            return []
        raise ValueError('请先勾选待入库条目')
    rows = [dict(r, status='confirmed') for r in selected]
    engine = engine_for(read_config())
    try:
        with engine.begin() as conn:
            guard(conn)
            if conn.scalar(text('select version_num from alembic_version')) not in ('0016', '0017'):
                raise ValueError('网页入库要求0016或0017外链结构')
            if conn.dialect.name == 'postgresql':
                conn.execute(text('LOCK TABLE data_source, game_product_config, game_alias, m_low_record IN SHARE ROW EXCLUSIVE MODE'))
            mark_duplicates(conn, batch)
            selected = [r for r in selected if not r.get('already_imported')]
            rows = [dict(r, status='confirmed') for r in selected]
            results = commit_rows(conn, rows, confirmations=confirmations,
                                  review_batch_id=batch['id'], batch_created_at=batch.get('created_at')) if rows else []
    finally:
        engine.dispose()
    for row, receipt in zip(selected, results):
        row.update(imported=True, selected=True, receipt=receipt, status='confirmed')
    return results


def check_gpc_reload(batch, index):
    if not 0 <= index < len(batch['rows']):
        raise ValueError('条目不存在')
    row = batch['rows'][index]
    if batch.get('preview') or batch['state'] not in ('ready', 'reviewable', 'failed'):
        raise ValueError('当前批次不能重新加载GPC')
    if row.get('imported') or row.get('already_imported') or row.get('selected'):
        raise ValueError('请先取消勾选；已入库条目不能重新加载GPC')
    if not row['final'].get('gpc_id'):
        raise ValueError('当前条目未绑定GPC')


def read_gpc(gpc_id):
    engine = engine_for(read_config())
    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            guard(conn)
            product = conn.execute(select(GameProductConfig.__table__).where(
                GameProductConfig.gpc_id == gpc_id)).mappings().one_or_none()
            if product is None or product['gpc_id'] == -1:
                raise ValueError('已有GPC不存在或为黑名单占位')
            return {k: product[k] for k in (*EDIT_FIELDS, 'platform')}
    finally:
        engine.dispose()


def reload_gpc(batch, index, payload):
    from .store import Conflict
    check_gpc_reload(batch, index)
    row = batch['rows'][index]
    if row['revision'] != payload.get('row_revision'):
        raise Conflict('条目已修改，请重新查看GPC差异')
    product = read_gpc(row['final']['gpc_id'])
    if product != payload.get('product'):
        raise Conflict('GPC资料再次改变，请重新查看差异')
    row.pop('gamefaqs_display_name', None)
    edit_row(batch, index, {'final': {k: product[k] for k in EDIT_FIELDS},
                          'quote': {'platform': product['platform']}}, candidate_change=True)
    row['gpc_baseline'] = {k: product[k] for k in GPC_FIELDS if k not in ('bangumi_id', 'outlink')}
    for key in ('candidate_lookup', 'candidate_main_resolution', 'candidate_type_resolution',
                'manual_gamefaqs', 'gamefaqs_display_name'):
        row.pop(key, None)
    row.setdefault('manual_resolutions', []).append({'source': 'reload_gpc', 'candidate': product})
    refresh_review_state(row)


def hydrate_candidate(candidate, platform):
    """A pasted URL may already identify a local product; preserve its shared fields."""
    engine = engine_for(read_config())
    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            guard(conn)
            sid = candidate.get('id') or candidate.get('bangumi_id')
            sid = str(sid) if sid else None
            link = candidate.get('outlink')
            matches = conn.execute(select(GameProductConfig.__table__).where(
                GameProductConfig.bangumi_id == sid, GameProductConfig.platform == platform,
                GameProductConfig.outlink == link)).mappings().all()
            if len(matches) == 1:
                return {**candidate, **dict(matches[0])}
            if len(matches) > 1:
                raise ValueError('本地存在多个相同产品，请先处理目录歧义')
    finally:
        engine.dispose()
    return candidate


def ensure_baseline(row):
    if 'parse_baseline' not in row:
        # Legacy drafts: reconstruct from original stage evidence, never from edits.
        original = prepare_row(row, {}, suggest_missing=False)
        original['quote'] = copy.deepcopy(row.get('quote', {}))
        for key in QUOTE_FIELDS:
            if key in row.get('extracted', {}):
                original['quote'][key] = row['extracted'][key]
        row['parse_baseline'] = copy.deepcopy({k: original.get(k) for k in ('final', 'quote', 'gpc_baseline', 'type_resolution', 'gamefaqs_display_name', 'main_explicit_null')})


def restore_row(batch, index):
    row = batch['rows'][index]
    if row['imported'] or row.get('already_imported') or row.get('selected') or batch['state'] not in ('ready', 'reviewable', 'failed'):
        raise ValueError('条目当前不能恢复')
    refresh_review_state(row)
    for key in ('candidate_lookup', 'candidate_main_resolution', 'candidate_type_resolution', 'manual_gamefaqs'):
        row.pop(key, None)
    row.update(copy.deepcopy(row['parse_baseline']))
    row['main_explicit_null'] = bool(row['parse_baseline'].get('main_explicit_null'))
    row.update(manual_fields=[], manual_target=False, selected=False, status='pending', revision=row.get('revision', 0) + 1)
    refresh_review_state(row)


def reparse_one(batch, index, path, dump_dir):
    row = batch['rows'][index]
    if row['imported'] or row.get('already_imported') or row.get('selected') or batch['state'] not in ('ready', 'reviewable', 'failed'):
        raise ValueError('条目当前不能重新解析')
    line = row.get('extracted', {}).get('line_number')
    if not isinstance(line, int):
        raise ValueError('缺少原始行号，不能单条重新解析')
    values = read_config()
    engine = engine_for(values)
    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            guard(conn)
            aliases = [dict(r) for r in conn.execute(text('select a.alias,g.* from game_alias a join game_product_config g using(gpc_id)')).mappings()]
    finally:
        engine.dispose()
    day = row['quote'].get('published_at')
    rows = build_review(read_note(path), batch['source_path'], date.fromisoformat(day) if day else None,
                        aliases, LocalDump(dump_dir), AnonymousAPI(), ai_client(values), only_line=line)
    replacement = prepare_row(rows[0], values)
    for key in ('ai_group', 'ai_group_id', 'ai_item_id'):
        if key in row:
            replacement[key] = copy.deepcopy(row[key])
    replacement['revision'] = row.get('revision', 0) + 1
    replacement['previous_parse'] = copy.deepcopy(row)
    return replacement


def refresh_duplicates(batch):
    if batch.get('state') not in ('ready', 'reviewable', 'failed') or not batch['rows']:
        return
    engine = engine_for(read_config())
    try:
        with engine.connect() as conn:
            if conn.dialect.name == 'postgresql':
                conn.execute(text('SET TRANSACTION READ ONLY'))
                guard(conn)
            for row in batch['rows']:
                normalize_draft(row)
            mark_duplicates(conn, batch)
            from .proposals import proposed_inserts
            for row in batch['rows']:
                row['proposed_inserts'] = proposed_inserts(conn, row)
    finally:
        engine.dispose()


def blacklist_row(batch, index, payload):
    from .store import Conflict
    from ..blacklist import add_alias, mark_blacklisted
    from ..bangumi import normalized
    if batch.get('preview') or batch['state'] not in ('ready', 'reviewable', 'failed'):
        raise ValueError('当前批次不能加入黑名单')
    if not 0 <= index < len(batch['rows']):
        raise ValueError('条目不存在')
    row = batch['rows'][index]
    if row.get('imported') or row.get('already_imported') or row.get('selected'):
        raise ValueError('请先取消勾选；已入库条目不能加入黑名单')
    if row.get('revision') != payload.get('row_revision') or row['raw_name'] != payload.get('text'):
        raise Conflict('条目已改变，请重新确认黑名单文本')
    engine = engine_for(read_config())
    try:
        with engine.begin() as conn:
            guard(conn)
            add_alias(conn, row['raw_name'], batch)
    finally:
        engine.dispose()
    for other in batch['rows']:
        if not other.get('imported') and normalized(other['raw_name']) == normalized(row['raw_name']):
            mark_blacklisted(other)
            other['revision'] = other.get('revision', 0) + 1
