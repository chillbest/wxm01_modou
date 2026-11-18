"""Save known candidates before optional network enrichment; never call AI."""
import copy
import uuid
from ..bangumi import english_name, LocalDump, AnonymousAPI, ps_platforms
from ..main_subject import MainSubjects
from ..product_type import ProductTypes
from .service import edit_row, refresh_review_state, hydrate_candidate, alias_bound


def candidates(row):
    return [*row.get('candidates', []), *row.get('stage_hits', {}).values(),
            *(c for t in row.get('stage_trace', []) for c in t.get('candidates', []))]


def identity(candidate):
    return (str(candidate.get('bangumi_id') or candidate.get('id') or ''), candidate.get('outlink') or '')


def save_manual_gamefaqs(batch, index, url, display_name, name_en=None):
    name = str(display_name or '').strip()
    if not name:
        raise ValueError('请输入外链display name')
    batch['rows'][index]['manual_gamefaqs'] = True
    edit_row(batch, index, {'final': {'outlink': url, 'display_name': name, 'bangumi_id': None}}, candidate_change=True)
    row = batch['rows'][index]
    row['final'].update(name_zh=name, gpc_id=None)
    if name_en is not None:
        row['final']['name_en'] = name_en
    row['gpc_baseline'] = None
    row['gamefaqs_display_name'] = True
    row['manual_gamefaqs'] = True
    for key in ('candidate_lookup', 'candidate_main_resolution', 'candidate_type_resolution'):
        row.pop(key, None)
    refresh_review_state(row)


def choose(batch, index, payload, resolved_candidate=None):
    row = batch['rows'][index]
    target = (str(payload.get('subject_id') or ''), payload.get('outlink') or '')
    candidate = copy.deepcopy(resolved_candidate) if resolved_candidate is not None else next((copy.deepcopy(c) for c in candidates(row) if identity(c) == target), None)
    if resolved_candidate is not None:
        target = identity(candidate)
    if candidate is None or target == ('', ''):
        raise ValueError('候选不属于该条目的已有资料')
    baseline = (row.get('parse_baseline') or {}).get('final') or {}
    original_target = identity(baseline) == target
    if original_target:
        for key in ('bangumi_main', 'type'):
            if baseline.get(key) is not None:
                candidate[key] = baseline[key]
    same = identity(row['final']) == target
    manual = set(row.get('manual_fields', []))
    if alias_bound(row) and not same:
        manual.clear()
    for field, value in (row.get('candidate_lookup') or {}).get('applied_fields', {}).items():
        if row['final'].get(field) == value:
            manual.discard('final.' + field)
    final = ({'name_en': english_name(candidate)} if resolved_candidate is not None else {}) if same else {
        'gpc_id': candidate.get('gpc_id'), 'bangumi_id': target[0] or None,
        'outlink': target[1] or None,
        'name_zh': candidate.get('name_cn') or candidate.get('name_zh') or candidate.get('name'),
        'name_en': english_name(candidate), 'bangumi_main': candidate.get('bangumi_main'),
        'type': candidate.get('type') if candidate.get('gpc_id') or original_target else None,
        'note': candidate.get('note'), 'display_name': candidate.get('display_name')}
    for key in ('type', 'bangumi_main', 'note', 'display_name'):
        if 'final.' + key in manual and not same:
            final[key] = row['final'].get(key)
    if target[1]:
        name = str(payload.get('display_name') or '').strip()
        if not name:
            raise ValueError('请输入外链display name')
        final.update(display_name=name, name_zh=name)
    platforms = ps_platforms(candidate)
    previous_platform = (row.get('candidate_lookup') or {}).get('applied_quote', {}).get('platform')
    manual_platform = ('quote.platform' in manual and row['quote'].get('platform') != previous_platform)
    quote = {}
    if candidate.get('gpc_id') and candidate.get('platform') in ('PS4', 'PS5'):
        quote['platform'] = candidate['platform']
    elif original_target and not manual_platform and (row.get('parse_baseline') or {}).get('quote', {}).get('platform') in ('PS4', 'PS5'):
        quote['platform'] = row['parse_baseline']['quote']['platform']
    elif not manual_platform and (not same or not row['quote'].get('platform')):
        import re
        explicit_ps4 = bool(re.search(r'(?<![A-Za-z0-9])PS\s*4(?![A-Za-z0-9])', row.get('extracted', {}).get('raw_name', row['raw_name']), re.I))
        quote['platform'] = ('PS4' if explicit_ps4 and 'PS4' in platforms else
                             'PS5' if 'PS5' in platforms else 'PS4' if 'PS4' in platforms else None)
    if row.get('main_explicit_null') and 'final.bangumi_main' in manual:
        final['bangumi_main'] = ' '
    edit_row(batch, index, {'final': final, 'quote': quote, 'manual_target': True,
                          'manual_resolution': {'candidate': candidate}}, candidate_change=True)
    row.pop('manual_gamefaqs', None)
    row['manual_target'] = True
    applied = {key: final[key] for key in ('bangumi_main', 'type', 'note', 'display_name')
               if key in final and 'final.' + key not in manual}
    if original_target:
        manual.update('final.' + key for key in ('bangumi_main', 'type') if baseline.get(key) is not None)
    token = uuid.uuid4().hex
    row['candidate_lookup'] = {'token': token, 'status': 'pending', 'protected_fields': sorted(manual),
                               'applied_fields': applied, 'applied_quote': quote}
    return candidate, token, row['revision']


def enrich(candidate, platform, dump_dir):
    candidate = hydrate_candidate(candidate, platform)
    if candidate.get('outlink'):
        # Existing saved main may be reused; no webpage request or AI on selection.
        main = {'status': 'saved' if candidate.get('bangumi_main') else 'unknown',
                'main_id': candidate.get('bangumi_main')}
    else:
        main = MainSubjects(LocalDump(dump_dir).path, AnonymousAPI()).resolve(candidate)
    types = ProductTypes().resolve(candidate, main)
    return candidate, main, types


def complete(store, key, index, token, revision, candidate, dump_dir):
    def current(row):
        return (row.get('candidate_lookup') or {}).get('token') == token
    with store.lock:
        batch = store.read(key)
        row = batch['rows'][index]
        if not current(row):
            return
        if row.get('revision') != revision or row.get('selected') or row.get('imported') or row.get('already_imported'):
            row['candidate_lookup']['status'] = 'superseded'
            batch['revision'] += 1
            store.write(batch)
            return
        platform = row['quote'].get('platform')
    try:
        candidate, main, types = enrich(candidate, platform, dump_dir)
        status = 'failed' if main.get('status') == 'failed' else 'done'
    except Exception:
        candidate, main, types, status = {}, {}, {}, 'failed'
    with store.lock:
        batch = store.read(key)
        row = batch['rows'][index]
        if not current(row):
            return
        if row.get('revision') != revision or row.get('selected') or row.get('imported') or row.get('already_imported'):
            row['candidate_lookup']['status'] = 'superseded'
        else:
            # Fields inherited from the choice are not manual overrides. Keep
            # only the fields explicitly protected when this lookup started.
            protected = set(row['candidate_lookup'].get('protected_fields', []))
            applied = dict(row['candidate_lookup'].get('applied_fields', {}))
            if candidate.get('gpc_id'):
                row['final']['gpc_id'] = candidate['gpc_id']
                for field in ('name_zh', 'name_en', 'note', 'display_name'):
                    if candidate.get(field) is not None and 'final.' + field not in protected:
                        # Keep the explicitly entered GameFAQs display name.
                        if row.get('gamefaqs_display_name') and field in ('name_zh', 'display_name'):
                            continue
                        row['final'][field] = candidate[field]
                        applied[field] = candidate[field]
                from .service import GPC_FIELDS
                row['gpc_baseline'] = {k: candidate.get(k) for k in GPC_FIELDS if k not in ('bangumi_id', 'outlink')}
            if candidate.get('gpc_id') and 'bangumi_main' in candidate and candidate['bangumi_main'] is None and 'final.bangumi_main' not in protected:
                row['final']['bangumi_main'] = None
                row['main_explicit_null'] = True
            for field, value in (('bangumi_main', main.get('main_id')), ('type', types.get('type'))):
                if field == 'bangumi_main' and row.get('main_explicit_null'):
                    continue
                if value is not None and 'final.' + field not in protected:
                    row['final'][field] = str(value)
                    applied[field] = str(value)
            row['candidate_main_resolution'] = main
            row['candidate_type_resolution'] = types
            row['candidate_lookup']['status'] = status
            row['candidate_lookup']['applied_fields'] = applied
            row['revision'] += 1
            refresh_review_state(row)
        batch['revision'] += 1
        store.write(batch)
