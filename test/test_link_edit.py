import copy
import io
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient
from modou.web import links
from modou.web.app import create_app
from test_web_app import row, HEADERS
from test_web_batches import tmp_path

URL = 'https://gamefaqs.gamespot.com/ps5/123-elden-ring'


def test_vgcollect_manual_link_display_eligibility_and_import(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, select
    from modou.models import Base, GameProductConfig
    from modou.web.service import commit_rows
    from modou.web_review import eligibility_errors
    for method in ('subject', 'gamefaqs', 'suggest_main'):
        monkeypatch.setattr('modou.web.app.' + method, lambda *a: pytest.fail('unexpected external lookup'))
    monkeypatch.setattr(links, 'vgcollect', lambda url: 'Uncharted: Legacy of Thieves Collection')
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    b = app.state.store.create('vg.txt', 'uploads/vg.txt')
    item = row(); item['final'].update(bangumi_id='123', name_zh=None, bangumi_main='105697',
                                     name_en='Previous Game', type='母子集')
    item['parse_baseline'] = {'final': copy.deepcopy(item['final']), 'quote': copy.deepcopy(item['quote'])}
    b.update(state='ready', rows=[item]); app.state.store.write(b)
    url = 'https://vgcollect.com/item/205944'
    with TestClient(app) as client:
        base = '/api/batches/' + b['id']
        response = client.post(base + '/rows/0/candidate', headers=HEADERS,
                               json={'row_revision': 0, 'url': url, 'display_name': '神秘海域4+dlc'})
        assert response.status_code == 200
        saved = response.json()
        for changes in ({'final': {'type': '母子集'}}, {'quote': {'platform': 'PS5'}}):
            response = client.post(base + '/rows/0', headers=HEADERS,
                                   json={'revision': saved['revision'], **changes})
            assert response.status_code == 200
            saved = response.json()
        reloaded = client.get(base).json()['rows'][0]
        assert reloaded['final']['bangumi_id'] is None
        assert 'final.bangumi_id' in reloaded['manual_fields']
        assert reloaded['final']['outlink'] == url
        assert reloaded['final']['bangumi_main'] == '105697'
        assert reloaded['final']['name_en'] == 'Uncharted: Legacy of Thieves Collection'
        assert not eligibility_errors(reloaded)
        selected = client.post(base + '/select', headers=HEADERS,
                               json={'revision': saved['revision'], 'index': 0, 'selected': True})
        assert selected.status_code == 200 and selected.json()['rows'][0]['selected']
        assert client.get('/review/' + b['id']).status_code == 200
    engine = create_engine('sqlite://'); Base.metadata.create_all(engine)
    with engine.begin() as conn:
        reloaded['status'] = 'confirmed'
        receipt = commit_rows(conn, [reloaded])
        product = conn.execute(select(GameProductConfig)).mappings().one()
        assert product['bangumi_id'] is None
        assert receipt and product['outlink'] == url
        assert product['bangumi_main'] == '105697'


@pytest.mark.parametrize('url', ['https://vgcollect.com/item/205944', 'https://vgcollect.com/item/205944/'])
def test_vgcollect_product_url_validation(url):
    assert links.valid_vgcollect_link(url)
    for bad in ('javascript:alert(1)', 'https://vgcollect.com.evil/item/205944',
                'https://vgcollect.com/item/abc', 'http://vgcollect.com/item/205944'):
        assert not links.valid_vgcollect_link(bad)


def test_unsaved_url_and_main_survive_unrelated_rerenders():
    import subprocess
    from pathlib import Path
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8').split('(() => {', 1)[0]
    checks = r"""
const assert=require('node:assert/strict'),drafts=new Map();
const url={},main={};
const clear=bindDraftInput(url,drafts,'7:url','');
bindDraftInput(main,drafts,'7:main','');
url.value='https://vgcollect.com/item/205944';url.oninput();
main.value='105697';main.oninput();
for(const change of ['type','platform']){
 const nextURL={},nextMain={};
 bindDraftInput(nextURL,drafts,'7:url',null);bindDraftInput(nextMain,drafts,'7:main',null);
 assert.equal(nextURL.value,url.value);assert.equal(nextMain.value,'105697');
}
assert.equal(mainSubjectURL(main.value),'https://bgm.tv/subject/105697');
assert.equal(mainSubjectURL('https://bgm.tv/subject/105697'),'https://bgm.tv/subject/105697');
url.value='https://bgm.tv/subject/105697';url.oninput();
clear('https://vgcollect.com/item/205944');
assert.equal(drafts.get('7:url'),url.value);
clear(url.value);assert.equal(drafts.has('7:url'),false);
const saved={};bindDraftInput(saved,drafts,'7:url',url.value);assert.equal(saved.value,url.value);
"""
    subprocess.run(['node', '-e', source + checks], check=True, capture_output=True, text=True)


def test_manual_main_preserved_after_type_and_platform_save(tmp_path, monkeypatch):
    monkeypatch.setattr('modou.web.app.subject', lambda url: {'id': 105697, 'type': 4})
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    b = app.state.store.create('manual-main.txt', 'uploads/manual-main.txt')
    b.update(state='ready', rows=[row()]); app.state.store.write(b)
    with TestClient(app) as client:
        resolved = client.post('/api/resolve', headers=HEADERS,
                              json={'url': 'https://bgm.tv/subject/105697', 'kind': 'main'})
        assert resolved.status_code == 200
        for revision, changes in enumerate([
            {'final': {'bangumi_main': resolved.json()['main_id']}},
            {'final': {'type': '母子集'}}, {'quote': {'platform': 'PS4'}},
        ]):
            response = client.post(f'/api/batches/{b["id"]}/rows/0', headers=HEADERS,
                                   json={'revision': revision, **changes})
            assert response.status_code == 200
            assert response.json()['rows'][0]['final']['bangumi_main'] == '105697'
        assert client.get(f'/api/batches/{b["id"]}').json()['rows'][0]['final']['bangumi_main'] == '105697'


@pytest.mark.parametrize('html, name', [
    ('<title>Elden Ring: Shadow of the Erdtree Edition for PlayStation 5 - GameFAQs</title>', 'Elden Ring: Shadow of the Erdtree Edition'),
    ('<title>Other - GameFAQs</title><h1><span>Elden Ring</span></h1>', 'Elden Ring'),
    ('<title>Tom &amp; Jerry for PS4 - GameFAQs</title>', 'Tom & Jerry'),
])
def test_gamefaqs_extracts_english_product_name(monkeypatch, html, name):
    class Opener:
        def open(self, *a, **k): return io.BytesIO(html.encode())
    monkeypatch.setattr(links, 'direct_opener', lambda *a: Opener())
    c = links.gamefaqs(URL)
    assert c['name_en'] == c['name'] == name
    assert c['outlink'] == URL


def test_gamefaqs_does_not_save_challenge_title(monkeypatch):
    class Opener:
        def open(self, *a, **k): return io.BytesIO(b'<title>Just a moment...</title>')
    monkeypatch.setattr(links, 'direct_opener', lambda *a: Opener())
    with pytest.raises(ValueError, match='验证'): links.gamefaqs(URL)


def test_gamefaqs_redirect_is_confined_to_product_pages():
    handler = links.NoRedirect()
    req = Request(URL)
    target = 'https://gamefaqs.gamespot.com/ps5/456-correct-product'
    assert handler.redirect_request(req, None, 301, '', {}, target).full_url == target
    for url in ('https://evil.test/ps5/456-product', 'https://gamefaqs.gamespot.com/search', 'http://gamefaqs.gamespot.com/ps5/456-product'):
        with pytest.raises(ValueError): handler.redirect_request(req, None, 301, '', {}, url)


@pytest.mark.parametrize('gamefaqs', [False, True])
def test_unmatched_link_saves_name_and_notes_before_main_job(tmp_path, monkeypatch, gamefaqs):
    jobs = []
    class Pool:
        def __init__(self, **k): pass
        def submit(self, fn, *a): jobs.append((fn, a))
        def shutdown(self, **k): pass
    monkeypatch.setattr('modou.web.app.ThreadPoolExecutor', Pool)
    subject = {'id': 123, 'type': 4, 'name': '日本語', 'infobox': [{'key': '英文名', 'value': 'English Game'}]}
    product = {'name': 'English Product', 'name_en': 'English Product', 'outlink': URL}
    monkeypatch.setattr('modou.web.app.subject', lambda u: subject)
    monkeypatch.setattr('modou.web.app.gamefaqs', lambda u: product)
    monkeypatch.setattr('modou.web.app.suggest_main', lambda *a: pytest.fail('blocking main lookup'))
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    b = app.state.store.create('empty.txt', 'uploads/empty.txt')
    r = row();r['final'] = dict.fromkeys(r['final']);r['final']['note'] = '已补充备注'
    r['final']['display_name'] = '显示名'
    r['parse_baseline'] = {'final': dict.fromkeys(r['final']), 'quote': copy.deepcopy(r['quote']), 'gpc_baseline': None}
    r['manual_fields'] = ['final.note', 'final.display_name']
    b.update(state='ready', rows=[r]);app.state.store.write(b)
    with TestClient(app) as client:
        response = client.post(f'/api/batches/{b["id"]}/rows/0/candidate', headers=HEADERS,
                               json={'row_revision': 0, 'url': URL if gamefaqs else 'https://bgm.tv/subject/123', 'display_name': '显示名'})
    assert response.status_code == 200
    saved = app.state.store.read(b['id'])['rows'][0]
    assert saved['final']['name_en'] == (None if gamefaqs else 'English Game')
    assert saved['final']['note'] == '已补充备注'
    assert saved['final']['display_name'] == '显示名'
    assert saved['final']['bangumi_id'] == (None if gamefaqs else '123')
    if gamefaqs:
        assert saved['manual_gamefaqs'] and 'candidate_lookup' not in saved and jobs == []
    else:
        assert saved['candidate_lookup']['status'] == 'pending' and len(jobs) == 1


def test_failed_product_request_reports_unsaved_and_keeps_draft(tmp_path, monkeypatch):
    monkeypatch.setattr('modou.web.app.subject', lambda _: (_ for _ in ()).throw(TimeoutError()))
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    b = app.state.store.create('a.txt', 'uploads/a.txt');b.update(state='ready', rows=[row()]);app.state.store.write(b)
    before = app.state.store.read(b['id'])
    with TestClient(app) as client:
        r = client.post(f'/api/batches/{b["id"]}/rows/0/candidate', headers=HEADERS,
                        json={'row_revision': 0, 'url': 'https://bgm.tv/subject/123', 'display_name': 'x'})
    assert r.status_code == 422 and '未保存' in r.json()['detail']
    assert app.state.store.read(b['id']) == before


def test_manual_gamefaqs_never_reads_link_or_links_other_columns_and_survives_platform(tmp_path, monkeypatch):
    for method in ('gamefaqs', 'subject', 'suggest_main', 'hydrate_candidate'):
        monkeypatch.setattr('modou.web.app.' + method, lambda *a: pytest.fail('unexpected linked lookup'))
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    b = app.state.store.create('manual.txt', 'uploads/manual.txt')
    r = row(); r['final'].update(name_en='Manual English', bangumi_main='88', type='Expansion', note='keep')
    r['quote']['platform'] = 'PS4'
    r['candidate_lookup'] = {'token': 'old', 'status': 'pending'}
    b.update(state='ready', rows=[r]);app.state.store.write(b)
    with TestClient(app) as client:
        base = f'/api/batches/{b["id"]}'
        response = client.post(base + '/rows/0/candidate', headers=HEADERS,
                               json={'row_revision': 0, 'url': URL, 'display_name': '自填显示名'})
        assert response.status_code == 200
        saved = response.json(); final = saved['rows'][0]['final']
        assert final['outlink'] == URL and final['display_name'] == '自填显示名'
        assert final['name_en'] == 'Manual English' and final['bangumi_main'] == '88'
        assert final['type'] == 'Expansion' and final['note'] == 'keep'
        assert saved['rows'][0]['quote']['platform'] == 'PS4'
        assert 'candidate_lookup' not in saved['rows'][0]
        response = client.post(base + '/rows/0', headers=HEADERS,
                               json={'revision': saved['revision'], 'quote': {'platform': 'PS5'}})
        assert response.status_code == 200
        assert response.json()['rows'][0]['final']['outlink'] == URL
        reloaded = client.get(base).json()['rows'][0]
        assert reloaded['final']['outlink'] == URL and reloaded['quote']['platform'] == 'PS5'
        client.post(base+'/rows/0',headers=HEADERS,json={'revision':response.json()['revision'],
                    'final':{'name_en':'Hand English','bangumi_main':'99','type':'Base'}})
    final = app.state.store.read(b['id'])['rows'][0]['final']
    assert final['outlink'] == URL and final['name_en'] == 'Hand English'


def test_manual_link_does_not_trigger_legacy_english_autofill():
    from modou.web.candidate_pick import save_manual_gamefaqs
    from modou.web.service import public_batch
    r = row()
    r['final']['name_en'] = None
    r['stage_hits'] = {'api': {'id': 4, 'name': 'Unexpected Autofill'}}
    r['parse_baseline'] = copy.deepcopy({k:r[k] for k in ('final','quote','gpc_baseline')})
    b = {'state':'ready','rows':[r]}
    save_manual_gamefaqs(b, 0, URL, '手填')
    assert public_batch(b)['rows'][0]['final']['name_en'] is None


@pytest.mark.parametrize('title,expected', [
    ('Uncharted: Legacy of Thieves Collection - PlayStation 5 [NA] - VGCollect', 'Uncharted: Legacy of Thieves Collection'),
    ('Ratchet &amp; Clank - PlayStation 4 [EU] - VGCollect', 'Ratchet & Clank'),
    ('Game - Deluxe Edition - PlayStation 5 [NA] - VGCollect', 'Game - Deluxe Edition'),
    ('Just a moment...', None), ('Access Denied', None),
])
def test_vgcollect_page_english_name(monkeypatch, title, expected):
    class Response(io.BytesIO):
        def geturl(self):
            return 'https://vgcollect.com/item/205944'
    class Opener:
        def open(self, req, timeout):
            return Response(('<title>' + title + '</title>').encode())
    monkeypatch.setattr(links, 'direct_opener', lambda *args: Opener())
    if expected:
        assert links.vgcollect('https://vgcollect.com/item/205944') == expected
    else:
        with pytest.raises(ValueError):
            links.vgcollect('https://vgcollect.com/item/205944')


def test_platform_preview_api(tmp_path, monkeypatch):
    monkeypatch.setattr('modou.web.app.subject', lambda url: {
        'name_cn': '游戏', 'infobox': [{'key': '平台', 'value': [{'v': 'PS5'}, {'v': 'PC'}]}]})
    with TestClient(create_app(tmp_path)) as client:
        result = client.get('/api/preview/123').json()
        assert result['platform'] == 'PS5 / PC'


def test_platform_dump_text():
    from modou.review_table import platform_text
    assert platform_text({'infobox': '|平台=PS5、PC\n|发行日期=2026'}) == 'PS5、PC'
    assert platform_text({'infobox': '|平台={\n[PS5]\n[PC]\n}\n|发行日期=2026'}) == 'PS5 / PC'
    assert platform_text({}) == ''



def test_vgcollect_failure_keeps_original_target(tmp_path, monkeypatch):
    def fail(url):
        raise ValueError('VGCollect unavailable')
    monkeypatch.setattr(links, 'vgcollect', fail)
    app = create_app(tmp_path)
    b = app.state.store.create('fail.txt', 'uploads/fail.txt')
    item = row(); item['final'].update(bangumi_id='123', name_en='Original')
    b.update(state='ready', rows=[item]); app.state.store.write(b)
    with TestClient(app) as client:
        response = client.post('/api/batches/' + b['id'] + '/rows/0/candidate', headers=HEADERS,
                               json={'row_revision': 0, 'url': 'https://vgcollect.com/item/205944', 'display_name': 'Game'})
        assert response.status_code == 422
    assert app.state.store.read(b['id'])['rows'][0]['final'] == item['final']


def test_display_dialog_preserves_input_until_explicit_action():
    import subprocess
    from pathlib import Path
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    helper = source[source.index('function askDisplayName('):source.index('const noteTooltip=')]
    harness = r"""
const assert=require('node:assert/strict');
const nodes=[];
function el(tag,text){const n={tag,text,children:[],value:'',append(...items){this.children.push(...items);},setAttribute(){},showModal(){this.open=true;},close(){this.open=false;},remove(){this.removed=true;},focus(){},select(){}};nodes.push(n);return n;}
const document={body:{append(){}}};
"""
    checks = r"""
(async()=>{
let settled=false;const result=askDisplayName('Name','Original').then(value=>{settled=true;return value;});
const input=nodes.find(n=>n.tag==='input'),dialog=nodes.find(n=>n.tag==='dialog'),form=nodes.find(n=>n.tag==='form');
input.value='Edited';await Promise.resolve();assert.equal(settled,false);assert.equal(dialog.open,true);
assert.equal(dialog.onblur,undefined);assert.equal(dialog.onvisibilitychange,undefined);
form.onsubmit({preventDefault(){}});assert.equal(await result,'Edited');assert.equal(dialog.removed,true);
const cancelled=askDisplayName('Name','Again');nodes.filter(n=>n.tag==='dialog').at(-1).oncancel({preventDefault(){}});assert.equal(await cancelled,null);
})().catch(e=>{console.error(e);process.exit(1);});
"""
    subprocess.run(['node', '-e', harness + helper + checks], check=True, capture_output=True)
