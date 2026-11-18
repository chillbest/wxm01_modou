"""Three ordered, non-retrying AI requests per fixed group of ten rows."""
import json
from collections import Counter
from .bangumi import _resolve, ai_candidate_line


STAGES = (('name', 'DeepSeek'), ('gamefaqs', 'GameFAQs'), ('main_subject', 'GameFAQs主版本'))


def candidate_inputs(row):
    counts, result = {}, {}
    for candidate in row['candidates']:
        origin = candidate.get('_ai_source', 'BGM本地')
        counts[origin] = counts.get(origin, 0) + 1
        label = f'{origin}_候选{counts[origin]}'
        result[label] = ai_candidate_line(candidate, label)
    return result


def ask_group(client, task, stage, items):
    evidence = {'task': task, 'stage': stage, 'item_ids': [i['item_id'] for i in items],
                'status': 'skipped', 'interactions': [], 'errors': {}}
    if not items or client is None:
        return {}, evidence
    start = len(getattr(client, 'interactions', []))
    try:
        answer = client({'task': task, 'items': items})
        results = answer.get('results')
        if not isinstance(results, list) or any(not isinstance(r, dict) or not isinstance(r.get('item_id'), str) for r in results):
            raise ValueError('批量回复results或item_id无效')
        expected = set(evidence['item_ids'])
        if any(r['item_id'] not in expected for r in results):
            raise ValueError('批量回复包含未知item_id')
        counts = Counter(r['item_id'] for r in results)
        evidence['errors'] = {sid: '回复漏项' if not counts[sid] else '回复item_id重复'
                              for sid in expected if counts[sid] != 1}
        valid = {r['item_id']: r for r in results if counts[r['item_id']] == 1}
        inputs = {i['item_id']: i for i in items}
        for sid, result in list(valid.items()):
            error = None
            if task == 'name':
                choice = result.get('candidate')
                if 'candidate' not in result or choice is not None and (
                        not isinstance(choice, str) or choice not in inputs[sid].get('candidates', {})):
                    error = '回复候选标识无效'
            if task == 'gamefaqs' and 'outlink' not in result:
                error = '回复缺少outlink'
            if task == 'main_subject' and 'main_subject_id' not in result:
                error = '回复缺少main_subject_id'
            if error:
                evidence['errors'][sid] = error
                del valid[sid]
        evidence['status'] = 'partial' if evidence['errors'] else 'received'
        return valid, evidence
    except Exception as exc:
        evidence.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        evidence['errors'] = {i['item_id']: evidence['error'] for i in items}
        return {}, evidence
    finally:
        evidence['interactions'] = [dict(r, stage=stage) for r in getattr(client, 'interactions', [])[start:]]


def resolve_group(rows, client, api, start_index):
    """Input rows already contain local/API results; replay only the pure AI tail."""
    contexts = {}
    for offset, row in enumerate(rows):
        sid = f'item-{start_index + offset:02d}'
        row['ai_item_id'] = sid
        contexts[sid] = {'item_id': sid, 'raw_name': row['raw_name'], 'note': row['note'],
                         'candidates': candidate_inputs(row),
                         **({'required_platforms': ['PS4', 'PS5']} if row.get('ps_disc_filter') else {})}
    wanted = [contexts[r['ai_item_id']] for r in rows if not r['stage_hits']]
    names, name_record = ask_group(client, *STAGES[0], wanted)

    def replay(row, faqs=None, faq_errors=None):
        sid = row['ai_item_id']
        def cached(ctx):
            is_faq = ctx.get('task') == 'gamefaqs'
            errors = (faq_errors or {}) if is_faq else name_record['errors']
            if sid in errors:
                raise ValueError(errors[sid])
            return (faqs or {}).get(sid, {'outlink': None}) if is_faq else names.get(sid, {'candidate': None})
        return _resolve(row['raw_name'], row['note'], (), (), api,
                        cached if client is not None else None, row.get('ps_disc_filter', False), preliminary=row)

    # Deprecated 2026-11-19 (6d8b20f4): GameFAQs automatic AI identification.
    #     wanted = [contexts[r['ai_item_id']] for r in rows
    #               if not r['stage_hits'] and not names.get(r['ai_item_id'], {}).get('candidate')]
    #     faqs, faq_record = ask_group(client, *STAGES[1], wanted)
    faqs = {}
    faq_record = {'task': 'gamefaqs', 'stage': 'GameFAQs', 'item_ids': [], 'status': 'disabled', 'interactions': [], 'errors': {}}
    resolved = []
    for original in rows:
        row = replay(original, faqs, faq_record['errors'])
        row['ai_item_id'] = original['ai_item_id']
        row['ai_mode'] = 'batch'
        resolved.append(row)
    # Deprecated 2026-11-19 (6d8b20f4): GameFAQs automatic AI identification.
    #     wanted = []
    #     for row in resolved:
    #         candidate = row.get('gamefaqs_suggestion')
    #         if candidate:
    #             wanted.append({'item_id': row['ai_item_id'], 'raw_name': candidate.get('name_zh'),
    #                            'note': json.dumps(candidate, ensure_ascii=False), 'candidates': {}})
    #             row['ai_main_attempted'] = True
    #     mains, main_record = ask_group(client, *STAGES[2], wanted)
    #     from .web.links import suggest_main
    #     for row in resolved:
    #         if not row.get('ai_main_attempted'):
    #             continue
    #         sid = row['ai_item_id']
    #         def cached_main(ctx):
    #             if sid in main_record['errors']:
    #                 raise ValueError(main_record['errors'][sid])
    #             return mains.get(sid, {'main_subject_id': None})
    #         cached_main.interactions = []
    #         row['main_resolution'] = suggest_main(row['gamefaqs_suggestion'], {}, api, cached_main)
    main_record = {'task': 'main_subject', 'stage': 'GameFAQs主版本', 'item_ids': [], 'status': 'disabled', 'interactions': [], 'errors': {}}
    group = {'id': f'group-{start_index:02d}', 'start': start_index, 'end': start_index + len(rows) - 1,
             'stages': [name_record, faq_record, main_record]}
    for row in resolved:
        row['ai_group_id'] = group['id']
    resolved[-1]['ai_group'] = group
    return resolved
