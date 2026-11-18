import copy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from modou.models import Base, GameProductConfig, PriceRecord, DataSource, GameAlias
from modou.web.app import create_app
from modou.web.service import commit_rows, edit_row, prepare_row
from modou.web.store import Store, Conflict
from modou.web.links import subject, suggest_main

@pytest.fixture
def tmp_path():
    import uuid
    path = Path('.tmp/web-tests') / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path.resolve()

HEADERS = {'X-Modou-Review': '1'}


def row():
    return {'raw_name':'测试游戏','status':'confirmed','stage_hits':{},'candidates':[], 'errors':[],
            'selected':False,'imported':False,'revision':0,'gpc_baseline':None,
            'final':{'gpc_id':None,'name_zh':'测试游戏','name_en':'Test Game','bangumi_id':'4','bangumi_main':'4','type':'Base','outlink':None,'note':None,'display_name':None},
            'quote':{'source_path':'uploads/test.txt','published_at':'2026-11-03','platform':'PS5','region':'港版','lowprice_cny':'100','lowprice_method':'直接购买','lowprice_date':'2026-11-03'}}


def test_commit_identity_retry_and_optional_updates():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        first=commit_rows(conn,[row()])
        assert commit_rows(conn,[row()])[0] == {k:v for k,v in first[0].items() if k != 'added'}
        alternate=row();alternate['quote']['platform']='PS4'
        second=commit_rows(conn,[alternate])
        assert first[0]['gpc_id']!=second[0]['gpc_id']
        assert conn.scalar(select(func.count()).select_from(PriceRecord))==2
        assert conn.scalar(select(func.count()).select_from(DataSource))==2
        assert conn.scalar(select(func.count()).select_from(GameAlias))==2
        update=row();update['final'].update(gpc_id=first[0]['gpc_id'],note='共享备注',display_name='显示名')
        update['quote']['lowprice_cny']='90'
        assert commit_rows(conn,[update])[0]['gpc_id']==first[0]['gpc_id']
        assert conn.scalar(select(GameProductConfig.note).where(GameProductConfig.gpc_id==first[0]['gpc_id']))=='共享备注'


def test_invalid_later_row_and_conflicting_product_write_nothing():
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with engine.begin() as conn:
        bad=row();bad['quote']['region']='?'
        with pytest.raises(ValueError):commit_rows(conn,[row(),bad])
        bad=row();bad['final']['type']='Expansion'
        with pytest.raises(ValueError,match='冲突'):commit_rows(conn,[row(),bad])
        assert conn.scalar(select(func.count()).select_from(GameProductConfig))==0


def test_transaction_failure_rolls_back_catalog_and_quote():
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with pytest.raises(ValueError):
        with engine.begin() as conn:
            commit_rows(conn,[row()])
            changed=row();changed['final']['gpc_id']=999
            commit_rows(conn,[changed])
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(GameProductConfig))==0
        assert conn.scalar(select(func.count()).select_from(PriceRecord))==0


def test_store_revision_and_path_safety(tmp_path):
    store=Store(tmp_path);batch=store.create('a.txt','a.txt')
    store.update(batch['id'],0,lambda b:b.update(state='ready'))
    with pytest.raises(Conflict):store.update(batch['id'],0,lambda b:None)
    with pytest.raises(ValueError):store.read('../.env')
    assert Store(tmp_path).read(batch['id'])['state']=='ready'


def test_http_draft_approval_edit_invalidation_commit_and_recovery(tmp_path):
    app=create_app(tmp_path);store=app.state.store
    b=store.create('a.txt','a.txt');b.update(state='ready',rows=[row()]);store.write(b)
    def commit(batch):
        for r in batch['rows']:
            if r['selected']:r.update(imported=True,selected=False,receipt={'record_id':1,'gpc_id':1})
    app.state.commit_batch=commit
    with TestClient(app) as client:
        key=b['id'];url='/api/batches/'+key
        assert client.get('/').status_code==200
        assert client.get('/review/'+key).status_code==200
        assert client.get('/assets/review.js').status_code==200
        assert client.post(url+'/select',json={'revision':0,'index':0,'selected':True}).status_code==403
        assert client.post(url+'/select',headers={**HEADERS,'Origin':'https://evil.test'},json={'revision':0,'index':0,'selected':True}).status_code==403
        selected=client.post(url+'/select',headers=HEADERS,json={'revision':0,'index':0,'selected':True}).json()
        assert selected['rows'][0]['selected']
        assert client.post(url+'/clear',headers=HEADERS,json={'revision':0}).status_code==409
        assert client.post(url+'/rows/0',headers=HEADERS,json={'revision':1,'final':{'note':'备注'}}).status_code==422
        assert client.post(url+'/select',headers=HEADERS,json={'revision':1,'index':0,'selected':False}).status_code==200
        changed=client.post(url+'/rows/0',headers=HEADERS,json={'revision':2,'final':{'note':'备注'}}).json()
        assert not changed['rows'][0]['selected']
        assert client.post(url+'/select',headers=HEADERS,json={'revision':3,'index':0,'selected':True}).status_code==200
        committed=client.post(url+'/commit',headers=HEADERS,json={'revision':4}).json()
        assert committed['rows'][0]['imported']
        assert client.post(url+'/rows/0',headers=HEADERS,json={'revision':5,'final':{'note':'改'}}).status_code==422
    assert Store(tmp_path/'batches').read(key)['rows'][0]['receipt']['record_id']==1


def test_upload_background_and_filename_safety(tmp_path):
    app=create_app(tmp_path)
    def parse(store,key,path,dump):
        assert path.is_relative_to(tmp_path/'uploads')
        b=store.read(key);b.update(state='ready',rows=[row()]);store.write(b)
    app.state.parse_job=parse
    with TestClient(app) as client:
        assert client.post('/api/upload',headers=HEADERS,files={'file':('a.csv',b'abc')}).status_code==422
        response=client.post('/api/upload',headers=HEADERS,files={'file':('../11.3.txt',b'abc')})
        assert response.status_code==200
    assert app.state.store.read(response.json()['id'])['filename']=='11.3.txt'


def test_unknown_main_stays_unknown_and_only_main_is_suggested():
    class API:
        def request(self,path):return {'id':8,'type':4,'name':'游戏'}
    class AI:
        interactions=[]
        def __call__(self,context):
            assert context['task']=='main_subject'
            return {'main_subject_id':'8','reason':'主版本'}
    c={'outlink':'https://gamefaqs.gamespot.com/ps5/123-game','name':'游戏'}
    result=suggest_main(c,{},api=API(),suggest=AI())
    assert result['main_id'] is None and result['status']=='disabled' and 'bangumi_id' not in result
    with pytest.raises(ValueError):subject('https://evil.test/subject/8',API())
    class Failed(AI):
        def __call__(self,context):return {'main_subject_id':None}
    assert suggest_main(c,{},api=API(),suggest=Failed())['main_id'] is None

from test_gpc_schema import connection


def test_online_web_import_0010_atomic_and_idempotent(connection):
    from modou.bangumi_cli import guard
    guard(connection)
    first = commit_rows(connection, [row()])
    assert commit_rows(connection, [row()]) == first
    assert connection.scalar(select(func.count()).select_from(PriceRecord)) == 1
    bad = row()
    bad['final'].update(gpc_id=9999, bangumi_id='9999')
    with pytest.raises(ValueError):
        with connection.begin_nested():
            alternate = row(); alternate['quote']['platform'] = 'PS4'
            commit_rows(connection, [alternate, bad])
    assert connection.scalar(select(func.count()).select_from(PriceRecord)) == 1
    assert connection.scalar(select(func.count()).select_from(GameProductConfig)) == 1


def test_restore_baseline_and_manual_markers():
    from modou.web.service import restore_row
    original = row()
    original['parse_baseline'] = copy.deepcopy({k: original[k] for k in ('final','quote','gpc_baseline')})
    batch = {'state':'ready','rows':[original,copy.deepcopy(original)]}
    other = copy.deepcopy(batch['rows'][1])
    edit_row(batch,0,{'final':{'type':None},'quote':{'region':None},'manual_target':True})
    assert original['manual_fields'] == ['final.type','quote.region']
    assert not original['manual_target']
    restore_row(batch,0)
    assert original['final']['type'] == 'Base'
    assert original['quote']['region'] == '港版'
    assert original['manual_fields'] == []
    assert not original['selected']
    assert batch['rows'][1] == other
    original['imported'] = True
    with pytest.raises(ValueError): restore_row(batch,0)


def test_restore_reparse_revision_and_failure_isolation(tmp_path, monkeypatch):
    import modou.web.app as module
    app = create_app(tmp_path)
    store = app.state.store
    b = store.create('example.txt','uploads/example.txt')
    b.update(state='ready',rows=[row(),row()])
    b['rows'][0]['parse_baseline'] = copy.deepcopy({k:b['rows'][0][k] for k in ('final','quote','gpc_baseline')})
    store.write(b)
    replacement = row(); replacement['raw_name'] = '重新解析结果'
    monkeypatch.setattr(module,'reparse_one',lambda *args: copy.deepcopy(replacement))
    with TestClient(app) as client:
        base='/api/batches/'+b['id']
        r=client.post(base+'/rows/0',headers=HEADERS,json={'revision':0,'final':{'type':None}})
        assert r.status_code == 200
        r=client.post(base+'/rows/0/restore',headers=HEADERS,json={'revision':1})
        assert r.status_code == 200
        assert r.json()['rows'][0]['final']['type'] == 'Base'
        assert r.json()['rows'][0]['manual_fields'] == []
        other=copy.deepcopy(r.json()['rows'][1])
        r=client.post(base+'/rows/0/reparse',headers=HEADERS,json={'revision':2})
        assert r.status_code == 200
        assert r.json()['rows'][0]['raw_name'] == '重新解析结果'
        assert r.json()['rows'][1] == other
        assert client.post(base+'/rows/0/reparse',headers=HEADERS,json={'revision':2}).status_code == 409
        before=store.read(b['id'])
        def fail(*args): raise ValueError('解析失败测试')
        monkeypatch.setattr(module,'reparse_one',fail)
        assert client.post(base+'/rows/0/reparse',headers=HEADERS,json={'revision':3}).status_code == 422
        assert store.read(b['id']) == before


def test_manual_flags_follow_parse_baseline_and_equal_numeric_values():
    from modou.web.service import refresh_review_state
    r=row();r['parse_baseline']=copy.deepcopy({k:r[k] for k in ('final','quote','gpc_baseline')})
    b={'state':'ready','rows':[r]}
    r['manual_fields']=['final.type'];r['manual_target']=True
    refresh_review_state(r)
    assert r['manual_fields']==[] and not r['manual_target']
    edit_row(b,0,{'final':{'type':'Expansion','bangumi_id':'8'},'quote':{'lowprice_cny':'100.00'}})
    assert r['manual_fields']==['final.bangumi_id','final.type']
    assert r['manual_target']
    edit_row(b,0,{'manual_target':True,'final':{'type':'Base','bangumi_id':'4'}})
    assert r['manual_fields']==[] and not r['manual_target']
    assert r['quote']['lowprice_cny']=='100.00'


def test_red_history_survives_correction_reload_restore_and_remains_selectable(tmp_path):
    from modou.web.service import public_batch
    app=create_app(tmp_path);store=app.state.store
    b=store.create('test.txt','uploads/test.txt');r=row();r['final']['type']=None
    r['parse_baseline']=copy.deepcopy({k:r[k] for k in ('final','quote','gpc_baseline')})
    b.update(state='ready',rows=[r]);store.write(b)
    with TestClient(app) as client:
        base='/api/batches/'+b['id']
        assert client.get(base).json()['rows'][0]['red_columns']==[3]
        response=client.post(base+'/rows/0',headers=HEADERS,json={'revision':0,'final':{'type':'Base'}})
        saved=response.json()['rows'][0]
        assert saved['red_columns']==[3] and saved['eligibility_errors']==[]
        assert saved['manual_fields']==['final.type']
        assert client.get(base).json()['rows'][0]['red_columns']==[3]
        assert Store(tmp_path/'batches').read(b['id'])['rows'][0]['red_columns']==[3]
        assert client.post(base+'/select',headers=HEADERS,json={'revision':1,'index':0,'selected':True}).status_code==200
        # Explicitly unlock before edits; the red history survives either action.
        client.post(base+'/select',headers=HEADERS,json={'revision':2,'index':0,'selected':False})
        client.post(base+'/rows/0',headers=HEADERS,json={'revision':3,'quote':{'region':None}})
        response=client.post(base+'/rows/0',headers=HEADERS,json={'revision':4,'quote':{'region':'港版'}})
        assert response.json()['rows'][0]['red_columns']==[3]
        response=client.post(base+'/rows/0/restore',headers=HEADERS,json={'revision':5})
        assert response.json()['rows'][0]['red_columns']==[3]
        assert response.json()['rows'][0]['manual_fields']==[]
        assert not response.json()['rows'][0]['selected']
    # A fresh successful parse starts its own red history.
    replacement=prepare_row({'stage_hits':{'alias':dict(row()['final'],gpc_id=1)},'quote':row()['quote']},{})
    assert replacement['red_columns']==[]


def test_all_visible_unknown_columns_are_latched_and_validity_is_independent():
    from modou.web.service import refresh_review_state
    r=row();r['parse_baseline']=copy.deepcopy({k:r[k] for k in ('final','quote','gpc_baseline')})
    b={'state':'ready','rows':[r]}
    edit_row(b,0,{'final':{'gpc_id':None,'bangumi_id':None,'outlink':None,'name_zh':None,'bangumi_main':None,'type':None},'quote':{'platform':None,'region':None,'lowprice_cny':None,'lowprice_method':None}})
    assert r['red_columns']==[1,2,3,4,5,6,7]
    edit_row(b,0,{'final':row()['final'],'quote':{k:row()['quote'][k] for k in ('platform','region','lowprice_cny','lowprice_method','lowprice_date')}})
    assert r['red_columns']==[]
    assert r['manual_fields']==[] and not r['manual_target']
    assert public_eligibility(r)==[]


def public_eligibility(r):
    from modou.web.service import public_batch
    return public_batch({'rows':[r]})['rows'][0]['eligibility_errors']


def test_date_save_changes_only_unimported_rows_and_rejects_invalid_date(tmp_path):
    app=create_app(tmp_path);store=app.state.store
    b=store.create('dates.txt','uploads/dates.txt');first=row();locked=row();locked['imported']=True
    b.update(state='ready',rows=[first,locked]);store.write(b)
    with TestClient(app) as client:
        base='/api/batches/'+b['id']
        r=client.post(base+'/date',headers=HEADERS,json={'revision':0,'date':'2026-11-04'})
        assert r.status_code==200
        assert r.json()['rows'][0]['quote']['published_at']=='2026-11-04'
        assert r.json()['rows'][0]['quote']['lowprice_date']=='2026-11-04'
        assert r.json()['rows'][1]['quote']['published_at']=='2026-11-03'
        before=store.read(b['id'])
        assert client.post(base+'/date',headers=HEADERS,json={'revision':1,'date':''}).status_code==422
        assert store.read(b['id'])==before


def test_home_program_modified_time(tmp_path, monkeypatch):
    import os
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from modou.web.app import program_modified_at
    root = tmp_path / 'src' / 'modou'
    static = root / 'web' / 'static'
    static.mkdir(parents=True)
    old = datetime(2026, 1, 1, 11, 0, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    latest = datetime(2026, 1, 1, 12, 12, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    for relative, stamp in [('core.py', old), ('web/static/index.html', latest),
                            ('__pycache__/core.pyc', latest + 5000), ('runtime.log', latest + 9000)]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('test', encoding='utf-8')
        os.utime(path, (stamp, stamp))
    assert program_modified_at(root) == '2026/01/01 12:12'
    os.utime(root / 'core.py', (latest + 60, latest + 60))
    assert program_modified_at(root) == '2026/01/01 12:13'
    monkeypatch.setattr('modou.web.app.program_modified_at', lambda: '2026/01/01 12:12')
    with TestClient(create_app(tmp_path / 'data')) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert '<span class="program-version">v2026/01/01 12:12</span>' in response.text
        assert '.batch-timing,.program-version{font-weight:400;color:#94a3b8;white-space:nowrap;font-size:14px}' in response.text
        assert 'h1{display:flex;align-items:baseline;flex-wrap:wrap;' in response.text
        assert '{{program_modified_at}}' not in response.text


def test_manual_records_hidden_but_retained_and_edits_persist(tmp_path):
    app = create_app(tmp_path, duplicate_checker=lambda batch: None)
    b = app.state.store.create('layout.txt', 'layout.txt')
    item = row()
    item['type_resolution'] = {'type': 'Base', 'status': 'rule', 'reason': 'main与bangumi_id相同'}
    item['manual_resolutions'] = [{'url': 'https://bgm.tv/subject/4'}]
    item['main_resolution'] = {'source': 'deepseek_gamefaqs', 'main_id': '4', 'reason': '主版本识别证据保留'}
    b.update(state='ready', rows=[item])
    app.state.store.write(b)
    with TestClient(app) as client:
        html = client.get('/review/' + b['id']).text
        assert '：type判定依据' not in html
        assert '：人工URL解析记录' not in html
        assert '：GameFAQs主版本识别证据' in html
        assert client.get('/api/batches/' + b['id']).json()['rows'][0]['type_resolution'] == item['type_resolution']
        resolution = {'url': 'https://bgm.tv/subject/4', 'type_resolution': item['type_resolution']}
        response = client.post('/api/batches/' + b['id'] + '/rows/0', headers=HEADERS, json={
            'revision': 0, 'final': {'note': '更新备注', 'display_name': '更新显示名'},
            'quote': {'lowprice_cny': '88'}, 'manual_resolution': resolution,
        })
        assert response.status_code == 200
        saved = app.state.store.read(b['id'])['rows'][0]
        assert saved['manual_resolutions'] == item['manual_resolutions'] + [resolution]
        assert saved['final']['note'] == '更新备注'
        assert saved['final']['display_name'] == '更新显示名'
        assert saved['quote']['lowprice_cny'] == '88'
        assert {'final.note', 'final.display_name', 'quote.lowprice_cny'} <= set(saved['manual_fields'])
        reloaded = client.get('/api/batches/' + b['id']).json()['rows'][0]
        for key in ('manual_resolutions', 'final', 'quote', 'manual_fields', 'main_resolution'):
            assert reloaded[key] == saved[key]
        refreshed = client.get('/review/' + b['id']).text
        assert '：人工URL解析记录' not in refreshed
        assert '：GameFAQs主版本识别证据' in refreshed
