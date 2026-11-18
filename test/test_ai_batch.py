import copy
import io
import json
from pathlib import Path
from datetime import date

import pytest

from modou.ai_batch import ask_group, resolve_group
from modou.ai_prompts import prompt
from modou.bangumi import resolve
from modou.note_review import build_review
from modou.review_html import render_html
from modou.web.service import prepare_row


class API:
    def __init__(self):
        self.searches = []
        self.details = []

    def search(self, query):
        self.searches.append(query)
        return []

    def request(self, path):
        self.details.append(path)
        return {'id': 100, 'type': 4, 'name': 'Game'}


class Client:
    def __init__(self, chooser=None):
        self.interactions = []
        self.calls = []
        self.chooser = chooser

    def __call__(self, ctx):
        self.calls.append(copy.deepcopy(ctx))
        task = ctx['task']
        results = []
        for item in reversed(ctx['items']):
            result = {'item_id': item['item_id'], 'reason': item['item_id']}
            if task == 'name':
                result['candidate'] = self.chooser(item) if self.chooser else None
            elif task == 'gamefaqs':
                result.update(name_zh='Game ' + item['item_id'], name_en='Game',
                              outlink='https://gamefaqs.gamespot.com/ps4/123-game', platforms=['PS4'])
            else:
                result['main_subject_id'] = '100'
            results.append(result)
        system, user = prompt(ctx)
        answer = {'results': results}
        self.interactions.append({'call_id': str(len(self.calls)), 'system': system, 'user': user,
                                  'content': json.dumps(answer), 'raw_response': '{}', 'status': 'received'})
        return answer


def preliminary(api, count=10, local=()):
    return [resolve('game' + str(i), 'line ' + str(i), [], local, api, ps_disc=True, defer_ai=True) for i in range(count)]


def test_name_only_request_without_gamefaqs_or_main_search():
    api, client = API(), Client()
    rows = resolve_group(preliminary(api), client, api, 1)
    assert [c['task'] for c in client.calls] == ['name']
    assert len(api.searches) == 10
    assert len(api.details) == 0
    for i, row in enumerate(rows, 1):
        assert row['gamefaqs_suggestion'] is None
        assert 'main_resolution' not in row
        assert row['ai_mode'] == 'batch' and row['ai_interactions'] == []
    group = rows[-1]['ai_group']
    assert (group['start'], group['end']) == (1, 10)
    assert [len(s['interactions']) for s in group['stages']] == [1, 0, 0]


def test_name_success_excludes_row_from_following_rounds():
    api = API()
    local = [{'id': 1, 'name_cn': 'a', 'infobox': [{'key': '平台', 'value': 'PS4'}]},
             {'id': 2, 'name_cn': 'b', 'infobox': [{'key': '平台', 'value': 'PS5'}]}]
    client = Client(lambda item: 'BGM本地_候选1' if item['item_id'] == 'item-01' else None)
    rows = resolve_group(preliminary(api, 2, local), client, api, 1)
    assert rows[0]['stage_hits']['ds']['id'] == 1
    assert len(client.calls) == 1
    assert rows[1]['gamefaqs_suggestion'] is None


def test_unique_local_hits_check_api_and_skip_ai_when_no_more_candidates():
    api, client = API(), Client()
    rows = resolve_group(preliminary(api, 2, [{'id': 1, 'infobox': [{'key': '平台', 'value': 'PS4'}]}]), client, api, 1)
    assert client.calls == [] and api.searches == ['game0', 'game1']
    assert [s['status'] for s in rows[-1]['ai_group']['stages']] == ['skipped', 'disabled', 'disabled']


@pytest.mark.parametrize('answer, expected, status', [
    ({'results': [{'item_id': 'a', 'candidate': None}]}, ['b'], 'partial'),
    ({'results': [{'item_id': 'a', 'candidate': None}, {'item_id': 'a', 'candidate': None}, {'item_id': 'b', 'candidate': None}]}, ['a'], 'partial'),
    ({'results': [{'item_id': 'unknown'}]}, ['a', 'b'], 'failed'),
    ({'results': 'invalid'}, ['a', 'b'], 'failed'),
])
def test_invalid_reply_ids_do_not_cross_fill(answer, expected, status):
    results, evidence = ask_group(lambda _: answer, 'name', 'DeepSeek', [{'item_id': 'a'}, {'item_id': 'b'}])
    assert sorted(evidence['errors']) == expected
    assert evidence['status'] == status
    assert not any(sid in results for sid in expected)


def test_request_failure_is_recorded_without_retry():
    class Failed(Client):
        def __call__(self, ctx):
            self.calls.append(ctx)
            self.interactions.append({'status': 'failed', 'error': 'offline'})
            raise TimeoutError('offline')
    client, api = Failed(), API()
    rows = resolve_group(preliminary(api), client, api, 1)
    assert len(client.calls) == 1  # Deprecated rounds never execute, including after failures.
    assert not any(r['stage_hits'] for r in rows)
    assert rows[-1]['ai_group']['stages'][0]['interactions'][0]['error'] == 'offline'


@pytest.mark.parametrize('task', ['name', 'gamefaqs', 'main_subject'])
def test_batch_prompt_markdown_and_minimal_fields(task):
    system, user = prompt({'task': task, 'items': [{'item_id': 'item-01', 'raw_name': 'Game',
                                                  'note': 'line', 'required_platforms': ['PS4', 'PS5']}]})
    assert '# 规则' in system and '# 输出' in system and 'results' in system
    assert '# 条目\n## item-01' in user
    assert 'edition' not in system.split('。')[1]  # Never an output field.
    if task == 'name':
        assert 'PS4' not in system and 'PS5' not in system
        assert 'platform' not in system and '范围：' not in user
    if task == 'gamefaqs':
        assert 'platforms' in system and 'PS4/PS5' in system


@pytest.fixture
def isolated_main(monkeypatch):
    class Main:
        def __init__(self, *args): pass
        def resolve(self, chosen): return {'status': 'unknown', 'main_id': None}
    monkeypatch.setattr('modou.main_subject.MainSubjects', Main)


@pytest.mark.parametrize('count', [1, 10, 11, 23])
def test_build_groups_tens_and_tail_with_one_call_ceiling(isolated_main, count):
    class Local:
        path = Path('dump.zip')
        def lookup_many(self, _): return {}
    client, api, published = Client(), API(), []
    text = 'PS好价光盘\n' + '\n'.join(f'游戏{i}｜HK100' for i in range(count))
    from modou import logging_setup as logs
    with logs.note_statistics('11.3.txt'):
        rows = build_review(text, '11.3.txt', date(2026, 11, 3), [], Local(), api, client, on_row=published.append)
        assert len(logs._note_stats.get().results) == count
    assert len(rows) == len(published) == count
    assert len(client.calls) == ((count + 9) // 10)
    assert all(1 <= len(c['items']) <= 10 for c in client.calls)
    assert all(r['quote']['platform'] is None and r['type_resolution']['type'] is None for r in rows)
    assert rows[-1]['ai_group']['end'] == count
    prepared = [prepare_row(r, {}) for r in rows]
    assert len(client.calls) == ((count + 9) // 10)
    assert all(r['final']['bangumi_main'] is None for r in prepared)


def test_batch_popup_and_single_reparse_popup_have_distinct_owners(isolated_main):
    api, client = API(), Client()
    row = resolve_group(preliminary(api, 1), client, api, 1)[0]
    row.update(extracted={'raw_name': 'game', 'raw_line': 'game｜HK100'}, quote={'platform': 'PS4'})
    html = render_html([row], 'test', None, online=True)
    assert 'AI建议 · 01—01' in html
    assert 'data-detail="ai-group-01"' in html
    assert html.count('role="tab"') == 3
    assert html.count('role="tabpanel"') == 3
    assert 'data-detail="ai-1-GameFAQs"' not in html
    row['ai_mode'] = 'single'
    row['ai_interactions'] = [dict(client.interactions[0], stage='GameFAQs')]
    html = render_html([row], 'test', None, online=True)
    assert 'data-detail="ai-1-GameFAQs"' in html
    assert 'data-detail="ai-group-01"' in html


def test_real_client_accepts_batch_results_and_preserves_request(monkeypatch):
    from modou.bangumi_cli import ai_client
    sent = []
    def transport(request, timeout):
        sent.append(json.loads(request.data))
        return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {
            'content': '{"results":[{"item_id":"a","candidate":null}]}'}}]}).encode())
    monkeypatch.setattr('modou.bangumi_cli.urlopen', transport)
    client = ai_client({'DEEPSEEK_API_KEY': 'test'})
    answer = client({'task': 'name', 'items': [{'item_id': 'a', 'raw_name': 'game'}]})
    assert answer['results'][0]['item_id'] == 'a'
    assert client.interactions[0]['user'] == sent[0]['messages'][1]['content']


def test_failed_main_is_not_retried_per_row(isolated_main, monkeypatch):
    class MissingMain(Client):
        def __call__(self, ctx):
            answer = super().__call__(ctx)
            if ctx['task'] == 'main_subject':
                answer['results'] = []
            return answer
    api, client = API(), MissingMain()
    rows = resolve_group(preliminary(api), client, api, 1)
    monkeypatch.setattr('modou.web.service.suggest_main', lambda *a, **k: pytest.fail('unexpected per-row retry'))
    for r in rows:
        r.update(quote={'platform': 'PS4'}, type_resolution={'type': None})
        prepared = prepare_row(r, {})
        assert prepared['final']['bangumi_main'] is None
        assert 'main_resolution' not in r
    assert len(client.calls) == 1


def test_single_reparse_uses_single_requests_and_preserves_group(isolated_main, monkeypatch):
    from unittest.mock import MagicMock
    from modou.web import service
    class Local:
        path = Path('dump.zip')
        def lookup_many(self, _): return {}
    class Single:
        interactions = []
        def __call__(self, ctx):
            assert 'items' not in ctx
            self.interactions.append({'stage': ctx.get('task', 'name'), 'system': 'single',
                                      'user': ctx['note'], 'content': '{}', 'status': 'received'})
            if ctx.get('task') == 'gamefaqs':
                return {'name_zh': '只狼', 'outlink': 'https://gamefaqs.gamespot.com/ps4/123-game', 'platforms': ['PS4']}
            if ctx.get('task') == 'main_subject':
                return {'main_subject_id': '100'}
            return {'candidate': None}
    client = Single()
    monkeypatch.setattr(service, 'ai_client', lambda _: client)
    monkeypatch.setattr('modou.web.links.ai_client', lambda _: client)
    monkeypatch.setattr('modou.web.links.subject', lambda *a: {'id': 100, 'type': 4})
    monkeypatch.setattr(service, 'LocalDump', lambda _: Local())
    monkeypatch.setattr(service, 'AnonymousAPI', API)
    monkeypatch.setattr(service, 'read_config', lambda: {})
    monkeypatch.setattr(service, 'guard', lambda _: None)
    monkeypatch.setattr(service, 'engine_for', lambda _: MagicMock())
    monkeypatch.setattr(service, 'read_note', lambda _: 'PS好价光盘\n只狼｜HK100')
    original = {'selected': False, 'imported': False, 'revision': 2,
                'extracted': {'line_number': 2}, 'quote': {'published_at': '2026-11-03'},
                'ai_group': {'id': 'group-01'}, 'ai_group_id': 'group-01', 'ai_item_id': 'item-10'}
    batch = {'state': 'ready', 'source_path': 'demo.txt', 'rows': [original]}
    replacement = service.reparse_one(batch, 0, 'unused', 'unused')
    assert len(client.interactions) == 1
    assert replacement['ai_mode'] == 'single' and replacement['revision'] == 3
    assert replacement['ai_group'] == original['ai_group']
    assert replacement['previous_parse'] == original
    assert replacement['final']['bangumi_main'] is None
    assert len(replacement['ai_interactions']) == 1
