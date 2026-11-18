import copy
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text
from test_web_app import row, HEADERS, tmp_path
from test_submission_review import engine
from modou.web import service
from modou.web.app import create_app
from modou.web.store import Store
from modou.web.proposals import proposed_inserts
from modou.web.duplicates import mark_duplicates
from modou.models import GameProductConfig, GameAlias, PriceRecord, DataSource


def isolate_parser(monkeypatch):
    e = MagicMock()
    e.connect.return_value.__enter__.return_value.execute.return_value.mappings.return_value = []
    monkeypatch.setattr(service, 'engine_for', lambda _: e)
    monkeypatch.setattr(service, 'guard', lambda _: None)
    monkeypatch.setattr(service, 'read_config', lambda: {})
    monkeypatch.setattr(service, 'read_note', lambda _: 'note')
    monkeypatch.setattr(service, 'LocalDump', lambda _: None)
    monkeypatch.setattr(service, 'AnonymousAPI', lambda: None)
    monkeypatch.setattr(service, 'ai_client', lambda _: None)
    monkeypatch.setattr(service, 'prepare_row', lambda r, _: copy.deepcopy(r))


@pytest.mark.parametrize('count', [3, 10, 23])
def test_publish_tens_tail_and_preserve_manual_work(tmp_path, monkeypatch, count):
    isolate_parser(monkeypatch)
    store = Store(tmp_path)
    b = store.create('test.txt', 'uploads/test.txt')
    def build(*args, on_row, on_total):
        on_total(count)
        for i in range(count):
            if i == 10:
                published = store.read(b['id'])
                assert published['state'] == 'reviewable' and len(published['rows']) == 10
                def edit(latest):
                    latest['rows'][0]['final']['note'] = '人工修改'
                    latest['rows'][1].update(selected=True, imported=True, receipt={'record_id': 9})
                    latest['review_date'] = '2026-11-04'
                store.update(b['id'], published['revision'], edit)
            if i == 20:
                assert len(store.read(b['id'])['rows']) == 20
            on_row(row())
        return []
    monkeypatch.setattr(service, 'build_review', build)
    service.parse_job(store, b['id'], tmp_path/'x.txt', tmp_path)
    saved = store.read(b['id'])
    assert saved['state'] == 'ready' and len(saved['rows']) == count
    assert saved['parse_finished_at'] and saved['parse_elapsed_seconds'] >= 0
    if count > 10:
        assert saved['revision'] == 1  # Appends do not invalidate saved approvals.
        assert saved['rows'][0]['final']['note'] == '人工修改'
        assert saved['rows'][1]['imported'] and saved['rows'][1]['selected']
        assert all(r['quote']['published_at'] == '2026-11-04' for r in saved['rows'][10:])


def test_parse_failure_keeps_published_rows_and_approvals(tmp_path, monkeypatch):
    isolate_parser(monkeypatch)
    store = Store(tmp_path); b = store.create('test.txt', 'uploads/test.txt')
    def build(*args, on_row, on_total):
        on_total(13)
        for i in range(13):
            on_row(row())
        store.update(b['id'], 0, lambda b: b['rows'][0].update(selected=True))
        raise RuntimeError('外部请求失败')
    monkeypatch.setattr(service, 'build_review', build)
    service.parse_job(store, b['id'], tmp_path/'x.txt', tmp_path)
    saved = store.read(b['id'])
    assert saved['state'] == 'failed' and len(saved['rows']) == 10
    assert saved['rows'][0]['selected'] and saved['revision'] == 1


def test_proposals_show_actual_new_rows_and_hide_internal_fields():
    e = engine()
    with e.begin() as c:
        r = row(); preview = proposed_inserts(c, r)
        assert [p['table'] for p in preview] == ['game_product_config', 'game_alias', 'm_low_record']
        for p in preview:
            assert not {'sources_id','alias_id','record_id'} & p['values'].keys()
        assert 'gpc_id' not in preview[0]['values']
        receipt = service.commit_rows(c, [r])[0]
        r['final']['gpc_id'] = receipt['gpc_id']
        r['quote']['lowprice_cny'] = '90'
        assert [p['table'] for p in proposed_inserts(c, r)] == ['m_low_record']
        r['raw_name'] = '新别名'
        assert [p['table'] for p in proposed_inserts(c, r)] == ['game_alias', 'm_low_record']
        r['imported'] = True
        assert proposed_inserts(c, r)[0]['stored'] is True


def test_same_product_batch_inserts_each_proposed_alias():
    e = engine()
    with e.begin() as c:
        a, b = row(), row(); b['raw_name'] = '另一别名'; b['quote']['lowprice_cny'] = '90'
        service.commit_rows(c, [a,b])
        assert c.scalar(select(func.count()).select_from(GameAlias)) == 2
        assert c.scalar(select(func.count()).select_from(GameProductConfig)) == 1


def test_http_partial_review_single_commit_and_snapshot_are_read_only(tmp_path, monkeypatch):
    e = engine()
    with e.begin() as c:
        c.execute(text('create table alembic_version (version_num text)'))
        c.execute(text("insert into alembic_version values ('0016')"))
    class Engine:
        begin = e.begin
        def dispose(self): pass
    monkeypatch.setattr(service,'engine_for',lambda _: Engine())
    monkeypatch.setattr(service,'guard',lambda _: None)
    def check(b):
        with e.connect() as c:
            mark_duplicates(c,b)
            for r in b['rows']: r['proposed_inserts'] = proposed_inserts(c,r)
    app = create_app(tmp_path, duplicate_checker=check)
    b = app.state.store.create('test.txt','uploads/test.txt')
    second = row(); second['quote']['lowprice_cny'] = '90'
    b.update(state='reviewable',rows=[row(), second]); app.state.store.write(b)
    with TestClient(app) as client:
        base = '/api/batches/'+b['id']
        assert client.get('/review/'+b['id']).status_code == 200
        update = client.get(base+'/updates?after=1').json()
        assert '勾选条目2' in update['html'] and '勾选条目1"' not in update['html']
        assert 'id="show-all"' not in update['html'] and '⬜ 仅看未选' not in update['html']
        assert app.state.store.read(b['id'])['revision'] == 0
        assert 'proposed_inserts' not in app.state.store.read(b['id'])['rows'][0]
        committed = client.post(base+'/rows/0/commit',headers=HEADERS,json={'revision':0}).json()
        assert committed['rows'][0]['imported'] and committed['rows'][0]['selected']
        assert not committed['rows'][1]['imported']
        assert client.post(base+'/clear',headers=HEADERS,json={'revision':1}).json()['rows'][0]['selected']
        assert client.post(base+'/rows/0',headers=HEADERS,json={'revision':2,'final':{'note':'x'}}).status_code == 422
        selected = client.post(base+'/select',headers=HEADERS,json={'revision':2,'index':1,'selected':True}).json()
        assert selected['rows'][1]['selected']
        committed = client.post(base+'/commit',headers=HEADERS,json={'revision':3}).json()
        assert all(r['imported'] and r['selected'] for r in committed['rows'])
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(PriceRecord)) == 2
        # Both commits reference the same source inside its two-hour reuse window.
        assert c.scalar(select(func.count()).select_from(DataSource)) == 1


def test_single_invalid_and_similar_confirmation_do_not_write(tmp_path):
    e = engine()
    with e.begin() as c: service.commit_rows(c,[row()])
    def commit(b, confirmations=(), *, index=None):
        r = b['rows'][index]
        with e.begin() as c: results = service.commit_rows(c,[dict(r,status='confirmed')],confirmations=confirmations)
        r.update(imported=True,selected=True,receipt=results[0])
    app=create_app(tmp_path,duplicate_checker=lambda _:None);app.state.commit_batch=commit
    r=row();r['final']['outlink']='https://gamefaqs.gamespot.com/ps5/1-game'
    b=app.state.store.create('x.txt','uploads/x.txt');b.update(state='reviewable',rows=[r]);app.state.store.write(b)
    with TestClient(app) as client:
        base='/api/batches/'+b['id'];endpoint=base+'/rows/0/commit'
        rejected=client.post(endpoint,headers=HEADERS,json={'revision':0})
        assert rejected.status_code==409
        assert not app.state.store.read(b['id'])['rows'][0]['imported']
        tokens=[x['token'] for x in rejected.json()['similar_products']]
        assert client.post(endpoint,headers=HEADERS,json={'revision':0,'similar_confirmations':tokens}).json()['rows'][0]['imported']
    with e.connect() as c: assert c.scalar(select(func.count()).select_from(PriceRecord))==2


def test_public_url_extraction_and_upload(tmp_path,monkeypatch):
    from modou.web import url_note
    title,note=url_note.extract_note('<title>11.3｜PS好价光盘</title><script>window.__INITIAL_STATE__={"note":{"title":"11.3｜PS好价光盘","desc":"合金弹头7 PS4｜HK100","x":undefined}}</script>')
    assert title=='11.3｜PS好价光盘' and '合金弹头7 PS4｜HK100' in note
    _,text_note=url_note.extract_note('<title>笔记</title><p>第一行</p><p>第二行</p><script>danger()</script>')
    assert '第一行\n第二行' in text_note and 'danger' not in text_note
    for url in ('file:///secret','http://127.0.0.1','http://[::1]','https://user:pw@example.com'):
        with pytest.raises(ValueError): url_note.check_url(url)
    monkeypatch.setattr(url_note,'fetch_note',lambda _:('https://example.com/note',title,note))
    app=create_app(tmp_path,duplicate_checker=lambda _:None)
    def parse(store,key,path,dump):
        b=store.read(key)
        assert b['source_path']=='https://example.com/note' and b['input_path'].startswith('uploads/')
        assert path.read_text(encoding='utf-8')==note
        b.update(state='ready',rows=[row()]);store.write(b)
    app.state.parse_job=parse
    with TestClient(app) as client:
        response=client.post('/api/url',headers=HEADERS,json={'url':'https://example.com/note'})
        assert response.status_code==200
