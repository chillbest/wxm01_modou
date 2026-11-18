import copy
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from modou.bangumi import valid_product_link
from modou.models import Base, GameProductConfig
from modou.web import service
from modou.web.app import create_app
from modou.web.store import Store
from test_web_app import row, HEADERS
from test_web_batches import tmp_path


@pytest.mark.parametrize('url', ['https://example.com/game/4?a=1#details', 'http://example.org/',
                               'https://store.steampowered.com/app/1/', 'https://example.com'])
def test_general_link_saves_without_network(tmp_path, monkeypatch, url):
    for method in ('subject', 'gamefaqs', 'suggest_main'):
        monkeypatch.setattr('modou.web.app.' + method, lambda *a: pytest.fail('external request'))
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    batch = app.state.store.create('test.txt', 'uploads/test.txt')
    item = row(); item['final']['gpc_id'] = 4
    batch.update(state='ready', rows=[item]); app.state.store.write(batch)
    with TestClient(app) as client:
        response = client.post(f'/api/batches/{batch["id"]}/rows/0/candidate', headers=HEADERS,
                               json={'row_revision': 0, 'url': url, 'display_name': '外链产品'})
        assert response.status_code == 200, response.text
    saved = response.json()['rows'][0]
    assert saved['final']['outlink'] == url
    assert saved['final']['gpc_id'] is None and saved['final']['bangumi_id'] is None
    assert saved['final']['display_name'] == '外链产品'
    assert saved['quote'] == item['quote']
    assert 'candidate_lookup' not in saved


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'file:///c:/test', 'https://',
                               'https://x.com:99999/', 'https://user:pass@x.com',
                               'https://x.com/\nscript', 'https://x.com\\@evil.com'])
def test_invalid_links_rejected(url):
    assert not valid_product_link(url)


def test_legacy_draft_upgrades_nested_fields_without_disk_write(tmp_path):
    store = Store(tmp_path)
    batch = store.create('old.txt', 'uploads/old.txt')
    item = row(); item['final'].pop('outlink')
    item['final']['gamefaqs_link'] = 'https://example.com/old'
    item['manual_fields'] = ['final.gamefaqs_link']
    item['parse_baseline'] = {'final': copy.deepcopy(item['final']), 'quote': item['quote']}
    batch.update(state='ready', rows=[item])
    path = store.path(batch['id']); path.write_text(json.dumps(batch), encoding='utf-8')
    before = path.read_bytes()
    loaded = store.read(batch['id'])['rows'][0]
    assert loaded['final']['outlink'] == loaded['parse_baseline']['final']['outlink'] == 'https://example.com/old'
    assert loaded['manual_fields'] == ['final.outlink']
    assert 'gamefaqs_link' not in loaded['final'] and path.read_bytes() == before


def test_reload_restores_identity_and_allows_actual_import(tmp_path, monkeypatch):
    engine = create_engine('sqlite://'); Base.metadata.create_all(engine)
    item = row()
    with engine.begin() as conn:
        gpc_id = service.commit_rows(conn, [item])[0]['gpc_id']
        conn.execute(update(GameProductConfig).where(GameProductConfig.gpc_id == gpc_id).values(
            outlink='https://example.com/new', note='数据库备注'))
        product = dict(conn.execute(select(GameProductConfig.__table__)).mappings().one())
    snapshot = {k: product[k] for k in (*service.EDIT_FIELDS, 'platform')}
    monkeypatch.setattr(service, 'read_gpc', lambda _: copy.deepcopy(snapshot))
    item['final']['gpc_id'] = gpc_id; item['quote']['lowprice_cny'] = '88'
    item['candidate_lookup'] = {'token': 'old', 'status': 'pending'}
    batch = dict(state='ready', rows=[item])
    with engine.begin() as conn:
        with pytest.raises(ValueError, match='GPC身份已改变'):
            service.commit_rows(conn, [item])
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    saved = app.state.store.create('old.txt', 'uploads/old.txt'); saved.update(batch); app.state.store.write(saved)
    base = f'/api/batches/{saved["id"]}/rows/0'
    with TestClient(app) as client:
        preview = client.get(base + '/gpc').json()
        response = client.post(base + '/reload-gpc', headers=HEADERS, json=preview)
        assert response.status_code == 200, response.text
        loaded = response.json()['rows'][0]
        assert loaded['quote']['lowprice_cny'] == '88'
        assert loaded['final']['outlink'] == snapshot['outlink']
        assert loaded['gpc_baseline']['note'] == '数据库备注'
        assert 'candidate_lookup' not in loaded
        assert client.post(base + '/reload-gpc', headers=HEADERS, json=preview).status_code == 409
    with engine.begin() as conn:
        loaded['status'] = 'confirmed'
        result = service.commit_rows(conn, [loaded])
        assert result[0]['gpc_id'] == gpc_id
        assert conn.execute(select(GameProductConfig.outlink)).scalar_one() == snapshot['outlink']


def test_reload_rejects_changed_product_and_locked_rows(monkeypatch):
    from modou.web.store import Conflict
    item = row(); item['final']['gpc_id'] = 4
    batch = dict(state='ready', rows=[item])
    monkeypatch.setattr(service, 'read_gpc', lambda _: {'outlink': 'new'})
    before = copy.deepcopy(batch)
    with pytest.raises(Conflict):
        service.reload_gpc(batch, 0, {'row_revision': 0, 'product': {'outlink': 'old'}})
    assert batch == before
    for flag in ('selected', 'imported', 'already_imported'):
        locked = copy.deepcopy(before); locked['rows'][0][flag] = True
        with pytest.raises(ValueError):
            service.reload_gpc(locked, 0, {'row_revision': 0})


def test_frontend_selects_general_external_candidates():
    import subprocess
    from pathlib import Path
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8').split('(() => {', 1)[0]
    checks = r"""
const assert=require('node:assert/strict');
const bgm={bangumi_id:'4'},external={outlink:'https://example.com'},other={outlink:'https://store.example/subject/4'};
const pool=[bgm,external,other];
assert.equal(candidateForURL(pool,'https://example.com/'),external);
assert.equal(candidateForURL(pool,other.outlink),other);
assert.equal(candidateForURL(pool,'https://bgm.tv/subject/4'),bgm);
assert.equal(candidateForURL(pool,'https://evil.example/subject/4'),null);
assert.equal(validExternalURL('https://example.com/product/4'),true);
assert.equal(validExternalURL('javascript:alert(1)'),false);
"""
    subprocess.run(['node', '-e', source + checks], check=True, capture_output=True, text=True)
