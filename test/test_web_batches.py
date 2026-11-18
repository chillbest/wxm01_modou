"""Batch metadata, parse timing and selected-item server locks."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from modou.web.app import create_app
from modou.web.store import Store, display_filename
from modou.web import service
from test_web_app import row, HEADERS


@pytest.fixture
def tmp_path():
    directory=Path('.tmp/web-batches')/uuid4().hex
    directory.mkdir(parents=True)
    return directory.resolve()


def test_repeat_numbers_are_atomic_stable_and_do_not_change_source(tmp_path):
    store=Store(tmp_path)
    first=store.create('游戏.txt','uploads/a/游戏.txt')
    first['state']='failed';store.write(first)
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches=list(pool.map(lambda _:store.create('游戏.txt','uploads/b/游戏.txt'),range(4)))
    assert sorted(b['upload_index'] for b in batches)==[2,3,4,5]
    assert display_filename(first)=='游戏.txt'
    assert display_filename(next(b for b in batches if b['upload_index']==2))=='游戏.txt（2）'
    assert all(b['filename']=='游戏.txt' and b['source_path']=='uploads/b/游戏.txt' for b in batches)
    before={b['id']:(b['upload_index'],b['batch_order']) for b in store.list()}
    recovered=Store(tmp_path)
    assert {b['id']:(b['upload_index'],b['batch_order']) for b in recovered.list()}==before
    assert recovered.create('游戏.TXT','uploads/c')['upload_index']==6
    assert recovered.create('不同.txt','uploads/d')['upload_index']==1


def test_legacy_numbers_are_persisted_without_fabricated_parse_times(tmp_path):
    for i in (1,2):
        batch=dict(id=f'{i:032x}',filename='old.txt',source_path='uploads/old.txt',state='ready',rows=[],revision=0,error=None)
        (tmp_path/(batch['id']+'.json')).write_text(json.dumps(batch),encoding='utf-8')
    store=Store(tmp_path)
    assert sorted(b['upload_index'] for b in store.list())==[1,2]
    original={b['id']:b['upload_index'] for b in store.list()}
    assert all('parse_started_at' not in b for b in store.list())
    assert {b['id']:b['upload_index'] for b in Store(tmp_path).list()}==original
    assert store.create('old.txt','uploads/new')['upload_index']==3


def test_batch_api_title_and_pending_page_share_repeat_name(tmp_path):
    app=create_app(tmp_path);store=app.state.store
    store.create('test.txt','uploads/test.txt')
    second=store.create('test.txt','uploads/another.txt')
    with TestClient(app) as client:
        assert client.get('/api/batches').json()[1]['display_filename']=='test.txt（2）'
        assert '<title>test.txt（2）</title>' in client.get('/review/'+second['id']).text
        second.update(state='ready',rows=[row()]);store.write(second)
        page=client.get('/review/'+second['id']).text
        assert '<title>test.txt（2）</title>' in page
        assert '<h1>test.txt（2）</h1>' in page
        assert client.get('/api/batches/'+second['id']).json()['display_filename']=='test.txt（2）'


@pytest.mark.parametrize('fails',[False,True])
def test_parse_timing_measures_only_actual_execution(tmp_path,monkeypatch,fails):
    store=Store(tmp_path);b=store.create('test.txt','uploads/test.txt')
    b['created_at']='2000-01-01T00:00:00+00:00';store.write(b)
    clocks=iter([100.,180.]);monkeypatch.setattr(service,'perf_counter',lambda:next(clocks))
    engine=MagicMock();engine.connect.return_value.__enter__.return_value.execute.return_value.mappings.return_value=[]
    monkeypatch.setattr(service,'engine_for',lambda _:engine)
    monkeypatch.setattr(service,'guard',lambda _:None)
    monkeypatch.setattr(service,'read_config',lambda:{})
    monkeypatch.setattr(service,'read_note',lambda _:'note')
    monkeypatch.setattr(service,'LocalDump',lambda _:None)
    monkeypatch.setattr(service,'AnonymousAPI',lambda:None)
    monkeypatch.setattr(service,'ai_client',lambda _:None)
    def build(*args, on_row, on_total):
        assert store.read(b['id'])['state']=='parsing'
        on_total(1)
        if fails:raise ValueError('mock failure')
        on_row(row())
        return [row()]
    monkeypatch.setattr(service,'build_review',build)
    monkeypatch.setattr(service,'prepare_row',lambda r,_:r)
    monkeypatch.setattr(service,'refresh_duplicates',lambda batch:None)
    service.parse_job(store,b['id'],tmp_path/'test.txt',tmp_path)
    saved=store.read(b['id'])
    assert saved['state']==('failed' if fails else 'ready')
    assert saved['parse_elapsed_seconds']==80.
    assert datetime.fromisoformat(saved['parse_started_at']).tzinfo is not None
    assert datetime.fromisoformat(saved['parse_finished_at'])>=datetime.fromisoformat(saved['parse_started_at'])


def test_selected_item_blocks_edits_restore_reparse_and_bulk_date(tmp_path,monkeypatch):
    app=create_app(tmp_path);store=app.state.store
    b=store.create('test.txt','uploads/test.txt');r=row();r['selected']=True
    b.update(state='ready',rows=[r]);store.write(b)
    def forbidden(*args):raise AssertionError('Locked item reached parser')
    monkeypatch.setattr('modou.web.app.reparse_one',forbidden)
    with TestClient(app) as client:
        base='/api/batches/'+b['id'];before=store.read(b['id'])
        for path,payload in [('/rows/0',{'final':{'note':'edit'}}),('/rows/0/restore',{}),('/rows/0/reparse',{}),('/date',{'date':'2026-11-04'})]:
            response=client.post(base+path,headers=HEADERS,json={'revision':0,**payload})
            assert response.status_code==422
            assert store.read(b['id'])==before
        assert client.post(base+'/select',headers=HEADERS,json={'revision':0,'index':0,'selected':False}).status_code==200
        assert client.post(base+'/rows/0',headers=HEADERS,json={'revision':1,'final':{'note':'edit'}}).status_code==200
        assert client.post(base+'/date',headers=HEADERS,json={'revision':2,'date':'2026-11-04'}).status_code==200

