import io
import json
import zipfile
import uuid
from pathlib import Path

import pytest

from modou.bangumi import AnonymousAPI, LocalDump, names, resolve
from modou.bangumi_cli import read_review, write_review


@pytest.fixture
def tmp_path():
    path = Path('.tmp') / ('bangumi-' + uuid.uuid4().hex)
    path.mkdir(parents=True)
    return path


def test_latest_dump_and_names(tmp_path):
    subject = {'id': 4, 'type': 4, 'platform': 4001, 'name': 'メタルスラッグ7', 'name_cn': '合金弹头7',
               'infobox': '{{Infobox Game\n|别名={\n[Metal Slug 7]\n}\n}}'}
    for day in ('2026-11-09', '2026-11-10'):
        with zipfile.ZipFile(tmp_path / f'dump-{day}.210405Z.zip', 'w') as z:
            z.writestr('subject.jsonlines', json.dumps(subject) + '\n' + json.dumps(dict(subject, type=2)))
    local = LocalDump(tmp_path)
    assert '11-10' in local.path.name
    assert local.lookup_many(['METAL SLUG 7'])['metal slug 7'] == [subject]
    assert 'metal slug 7' in names(dict(subject, infobox=[{'key': '别名', 'value': [{'v': 'Metal Slug 7'}]}]))


def test_anonymous_requests_cache_and_detail():
    requests = []
    def transport(request, timeout):
        requests.append(request)
        assert not request.has_header('Authorization')
        assert timeout == 20
        if request.data:
            assert json.loads(request.data)['filter'] == {'type': [4]}
            return io.StringIO('{"data":[{"id":4,"type":4}]}')
        return io.StringIO('{"id":4,"type":4,"platform":"游戏","name_cn":"合金弹头7"}')
    api = AnonymousAPI(transport)
    assert api.search('Metal Slug 7')[0]['id'] == 4
    api.search('Metal Slug 7')
    assert len(requests) == 2


def test_local_candidates_require_both_numeric_type_and_game_category(tmp_path):
    fields = [{'type': 4, 'platform': 4001}, {'type': 2, 'platform': 4001},
              {'type': 4, 'platform': 4003}, {'type': 4, 'platform': 4002},
              {'type': 4, 'platform': 4005}, {'type': 4}, {'platform': 4001},
              {'type': '4', 'platform': 4001}, {'type': 4, 'platform': '4001'},
              {'type': 4, 'platform': '游戏'}, {'type': 4, 'platform': None}]
    subjects = [dict(f, id=i, name='same game') for i, f in enumerate(fields, 1)]
    with zipfile.ZipFile(tmp_path / 'dump-2026-11-16.zip', 'w') as archive:
        archive.writestr('subject.jsonlines', '\n'.join(json.dumps(s) for s in subjects))
    assert LocalDump(tmp_path).lookup_many(['same game'])['same game'] == [subjects[0]]


def test_api_filters_subject_details_before_unique_hit_and_ai():
    fields = [{'type': 4, 'platform': '游戏'}, {'type': 2, 'platform': '游戏'},
              {'type': 4, 'platform': '扩展包'}, {'type': 4, 'platform': '软件'},
              {'type': 4, 'platform': '桌游'}, {'type': 4}, {'platform': '游戏'},
              {'type': '4', 'platform': '游戏'}, {'type': 4, 'platform': 4001},
              {'type': 4, 'platform': None}]
    subjects = {i: dict(f, id=i, name='same game') for i, f in enumerate(fields, 1)}
    requests = []
    def transport(request, timeout):
        requests.append(request)
        if request.data:
            assert json.loads(request.data)['filter'] == {'type': [4]}
            # Search summaries claim type=4 even when detail contradicts them.
            return io.StringIO(json.dumps({'data': [{'id': i, 'type': 4} for i in subjects]}))
        return io.StringIO(json.dumps(subjects[int(request.full_url.rsplit('/', 1)[1])]))
    def forbidden_ai(context):
        raise AssertionError('Filtered unique API hit must stop before AI')
    api = AnonymousAPI(transport)
    result = resolve('same game', 'original line', [], [], api, forbidden_ai)
    assert result['stage_hits']['api']['id'] == 1
    assert result['candidates'] == [dict(subjects[1], _ai_source='BGM-API')]
    assert result['ai_interactions'] == []
    assert next(t for t in result['stage_trace'] if t['stage'] == 'BangumiAPI')['result'] == '命中'
    assert api.search('same game') == [subjects[1]]
    assert len(requests) == 11  # Repeated search and details remain cached.


def test_fallback_and_ai_validation():
    class API:
        def search(self, query):
            raise RuntimeError('offline')
    alias = {'alias': 'A', 'gpc_id': 1}
    assert resolve('a', 'note', [alias], [], API())['source'] == 'alias'
    assert resolve('a', 'note', [], [{'id': 1}], API())['source'] == 'local'
    result = resolve('a', 'note', [alias, dict(alias, gpc_id=2)], [{'id': 1}, {'id': 2}], API(),
                     lambda context: {'bangumi_id': '999'})
    assert result['status'] == 'pending'
    assert len(result['errors']) == 2
    assert result['suggestion'] is None
    assert len(result['candidates']) == 2


def test_review_gate_and_manual_edit(tmp_path):
    path = tmp_path / 'review.md'
    rows = [{'raw_name': 'A', 'status': 'pending', 'final': {'name_zh': '游戏', 'bangumi_id': '4'}}]
    write_review(path, rows)
    with pytest.raises(ValueError, match='未审核'):
        read_review(path)
    path.write_text(path.read_text(encoding='utf-8').replace('pending"', 'confirmed"'), encoding='utf-8')
    assert read_review(path)[0]['final']['bangumi_id'] == '4'
    with pytest.raises(FileExistsError):
        write_review(path, rows)


def test_unique_hit_stops_all_later_stages():
    def forbidden(context):
        raise AssertionError('unique hit must not call AI')
    class API:
        calls = 0
        def search(self, query):
            self.calls += 1
            return [{'id': 4, 'name_cn': 'game'}]
    api = API()
    for aliases, local, expected in [([{'alias':'game','gpc_id':1}], [], 'alias'),
                                     ([], [{'id':4,'name_cn':'game'}], 'local'),
                                     ([], [], 'api')]:
        r = resolve('game', 'note', aliases, local, api, forbidden)
        assert set(r['stage_hits']) == {expected}
        assert r['suggestion'] is None
        assert r['errors'] == []
    assert api.calls == 1


def test_gamefaqs_fallback_and_skip():
    class API:
        def search(self, query):
            return []
    calls = []
    link = 'https://gamefaqs.gamespot.com/ps5/324823-ghost-of-tsushima-iki-island'
    def ai(context):
        calls.append(context)
        return {'name_zh': '对马岛之魂壹岐岛', 'outlink': link} if context.get('task') == 'gamefaqs' else {'bangumi_id': None}
    r = resolve('壹岐岛', '原始笔记', [], [], API(), ai)
    assert len(calls) == 1 and calls[0]['note'] == '原始笔记'
    assert r['status'] == 'pending' and not r['stage_hits']
    assert r['gamefaqs_suggestion'] is None and '已弃用' in r['stage_trace'][-1]['reason']
    calls.clear()
    r = resolve('壹岐岛', '笔记', [], [{'id': 4}], API(), ai)
    assert calls == [] and r['stage_trace'][-1]['result'] == '未执行'
    calls.clear()
    r = resolve('壹岐岛', '笔记', [], [{'id': 4}, {'id': 5}], API(), lambda c: {'bangumi_id': 4})
    assert set(r['stage_hits']) == {'ds'} and r['gamefaqs_suggestion'] is None


def test_gamefaqs_invalid_failure_and_disabled():
    from modou.bangumi import valid_gamefaqs_link
    class API:
        def search(self, query):
            return []
    for link in ['javascript:alert(1)', 'https://gamefaqs.gamespot.com.evil/ps5/1-game',
                 'https://gamefaqs.gamespot.com/ps5/category', 'https://gamefaqs.gamespot.com/ps5/1-game/data']:
        assert not valid_gamefaqs_link(link)
        r = resolve('game', 'note', [], [], API(), lambda c: {'outlink': link, 'name_zh': '游戏'})
        assert not r['stage_hits'] and not any('GameFAQs辅助失败' in e for e in r['errors'])
    assert resolve('game', 'note', [], [], API())['stage_trace'][-1]['reason'] == '功能已弃用：不再自动提供GameFAQs链接'
    r = resolve('game', 'note', [], [], API(), lambda c: {'bangumi_id': None, 'outlink': None})
    assert r['stage_trace'][-1]['result'] == '未执行'


def test_ai_client_gamefaqs_prompt(monkeypatch):
    from modou import bangumi_cli
    requests = []
    def transport(request, timeout):
        requests.append(json.loads(request.data))
        return io.StringIO(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': '{"candidate":null,"outlink":null}'}}]}))
    monkeypatch.setattr(bangumi_cli, 'urlopen', transport)
    ai = bangumi_cli.ai_client({'DEEPSEEK_API_KEY': 'test-only'})
    ai({'raw_name': 'game', 'candidates': []})
    ai({'task': 'gamefaqs', 'raw_name': 'game', 'note': 'note'})
    assert 'candidate' in requests[0]['messages'][0]['content']
    assert '禁止编造链接' in requests[1]['messages'][0]['content']
    assert 'outlink' in requests[1]['messages'][0]['content']


def test_ai_candidate_wiki_alias_block():
    from modou.bangumi import ai_candidate
    candidate = {'id': 4, 'name': 'Game', 'infobox': '{{Infobox Game\n|别名={\n[Alias A]\n[Alias B]\n}\n|售价=999\n|平台=PS5\n}}', 'images': {}}
    slim = ai_candidate(candidate)
    assert slim == '别名=["Alias A","Alias B"]｜售价=999｜平台=PS5'
    assert 'images' not in slim



@pytest.mark.parametrize('info', [
    [{'key': '平台', 'value': [{'v': 'PS5'}, {'v': 'PC'}]}],
    '{{Infobox Game\n|平台={\n[PS4]\n[PC]\n}\n|售价=123\n}}',
    [{'key': '平台', 'value': 'PlayStation 5'}],
])
def test_ps_disc_platform_evidence(info):
    from modou.bangumi import supports_ps_disc
    assert supports_ps_disc({'infobox': info})
    assert not supports_ps_disc({'summary': 'PS5', 'name_cn': 'PS5游戏'})
    assert not supports_ps_disc({'infobox': [{'key': '平台', 'value': 'PS3 PS Vita PC PS50'}]})


def test_ps_disc_filters_before_unique_hit_and_ai():
    class API:
        def search(self, query):
            return [{'id': 3, 'platform': 'PC'}, {'id': 4, 'infobox': [{'key': '平台', 'value': 'PS5'}]}]
    r = resolve('game', 'line', [{'alias': 'game', 'gpc_id': 1}], [{'id': 2, 'platform': 'PS3'}], API(), ps_disc=True)
    assert set(r['stage_hits']) == {'api'} and [c['id'] for c in r['candidates']] == [4]
    assert r['stage_trace'][0]['result'] == r['stage_trace'][1]['result'] == '未命中'
    calls = []
    class Mixed:
        def search(self, query):
            return [{'id': 1, 'platform': 'PC'}, {'id': 4, 'platform': 'PS4'}, {'id': 5, 'platform': 'PS5'}]
    def ai(context):
        calls.append(context)
        return {'bangumi_id': 4}
    r = resolve('game', 'line', [], [], Mixed(), ai, ps_disc=True)
    assert set(r['stage_hits']) == {'ds'}
    assert [c.split('：')[0] for c in calls[0]['candidates']] == ['BGM-API_候选1', 'BGM-API_候选2']
    assert calls[0]['required_platforms'] == ['PS4', 'PS5']


@pytest.mark.parametrize('platform,accepted', [('pc', False), ('ps3', False), ('ps4', True), ('ps5', True)])
def test_ps_disc_gamefaqs(platform, accepted):
    class API:
        def search(self, query):
            return []
    def ai(context):
        return {'bangumi_id': None, 'name_zh': '游戏', 'outlink': f'https://gamefaqs.gamespot.com/{platform}/1-game'}
    r = resolve('game', 'line', [], [], API(), ai, ps_disc=True)
    assert not r['stage_hits'] and r['gamefaqs_suggestion'] is None
    assert r['stage_trace'][-1]['result'] == '未执行'

@pytest.mark.parametrize('body,finish', [('broken','stop'), ('{"candidate":null}','length'), ('{"candidate":null}','stop')])
def test_actual_interactions_survive_parsing(monkeypatch, body, finish):
    from modou import bangumi_cli
    raw = json.dumps({'choices':[{'finish_reason':finish,'message':{'content':body}}]})
    sent=[]
    def transport(request, timeout):
        sent.append(json.loads(request.data))
        return io.BytesIO(raw.encode())
    monkeypatch.setattr(bangumi_cli,'urlopen',transport)
    ai=bangumi_cli.ai_client({'DEEPSEEK_API_KEY':'secret-test'})
    class API:
        def search(self,q): return []
    result=resolve('game','one line',[],[],API(),ai)
    records=result['ai_interactions']
    assert [r['stage'] for r in records]==['DeepSeek']
    for record,request in zip(records,sent):
        assert record['system']==request['messages'][0]['content']
        assert record['user']==request['messages'][1]['content']
        assert record['raw_response']==raw and record['content']==body
    assert 'secret-test' not in json.dumps(records)


def test_interaction_network_and_http_errors(monkeypatch):
    from modou import bangumi_cli
    from urllib.error import HTTPError
    ai=bangumi_cli.ai_client({'DEEPSEEK_API_KEY':'secret'})
    for error,expected in [(TimeoutError('secret'),None), (HTTPError('https://example.com',500,'error',{},io.BytesIO(b'bad response')),'bad response')]:
        def transport(*args,**kwargs): raise error
        monkeypatch.setattr(bangumi_cli,'urlopen',transport)
        with pytest.raises(Exception): ai({'candidates':[]})
        record=ai.interactions[-1]
        assert record['raw_response']==expected
        assert 'secret' not in record['error']


def test_candidate_mapping_and_complete_fields():
    from modou.bangumi import ai_candidate
    class API:
        def search(self,q): return [{'id':2,'infobox':[{'key':'空','value':''}]}, {'id':3}]
    local=[{'id':1,'infobox':[{'key':'售价','value':'a\n｜b'},{'key':'售价','value':'2'}]}, {'id':2}]
    calls=[]
    def ai(c):
        calls.append(c)
        return {'candidate':'BGM-API_候选1','edition':'标准版','reason':'test'}
    r=resolve('game','line',[],local,API(),ai)
    assert r['suggestion']['bangumi_id']==2 and r['suggestion']['edition']=='标准版'
    assert calls[0]['candidates']['BGM本地_候选1']['name'] is None
    assert ai_candidate({'infobox':[]})==''
    r=resolve('game','line',[],local,API(),lambda c:{'candidate':'bad'})
    assert not r['stage_hits'] and r['suggestion'] is None



def test_candidate_limit_applies_to_both_ai_requests_without_changing_evidence(monkeypatch):
    from copy import deepcopy
    from modou.bangumi_cli import ai_client
    requests = []
    def transport(request, timeout):
        requests.append(json.loads(request.data))
        return io.StringIO(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': '{"candidate":null,"outlink":null}'}}]}))
    monkeypatch.setattr('modou.bangumi_cli.urlopen', transport)
    class API:
        def search(self, query):
            return []
    candidates = [{'id': i, 'infobox': [{'key': '别名', 'value': text * 200}]}
                  for i, text in enumerate(('中文', '🙂a中'), 1)]
    before = deepcopy(candidates)
    result = resolve('game', 'original line', [], candidates, API(), ai_client({'DEEPSEEK_API_KEY': 'test'}))
    assert len(requests) == 1
    for request in requests:
        prompt = request['messages'][1]['content']
        assert '当前报价原始行：original line' in prompt
        for index, candidate in enumerate(before, 1):
            assert f'BGM本地_候选{index}：name=' in prompt
            assert candidate['infobox'][0]['value'] in prompt
            assert '｜平台=null｜游戏类型=null｜发行日期=null' in prompt
    assert candidates == before
    assert result['candidates'][0]['infobox'] == before[0]['infobox']
    assert result['ai_interactions'][0]['user'] == requests[0]['messages'][1]['content']


def test_partial_http_body_is_retained(monkeypatch):
    from http.client import IncompleteRead
    from modou import bangumi_cli
    class Response(io.BytesIO):
        def read(self): raise IncompleteRead(b'partial-json',20)
    monkeypatch.setattr(bangumi_cli,'urlopen',lambda *a,**k: Response())
    ai=bangumi_cli.ai_client({'DEEPSEEK_API_KEY':'test'})
    with pytest.raises(IncompleteRead): ai({'candidates':[]})
    assert ai.interactions[-1]['raw_response']=='partial-json'
