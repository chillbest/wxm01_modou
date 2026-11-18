import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from modou.models import PriceRecord
from modou.web import service
from modou.web.alias_bulk import approved_indices, preview
from modou.web.app import create_app
from modou.web.store import Conflict
from test_submission_review import engine
from test_web_app import HEADERS, row
from test_web_batches import tmp_path


def alias_row(gpc_id=7):
    item = row()
    item['final']['gpc_id'] = gpc_id
    item['stage_hits'] = {'alias': copy.deepcopy(item['final'])}
    return item


@pytest.mark.parametrize('condition,included', [
    ('complete', True), ('selected', True), ('missing_english', False),
    ('missing_main', False), ('imported', False), ('already_imported', False),
    ('other_target', False), ('not_alias', False),
])
def test_preview_matches_alias_and_eligibility(condition, included):
    item = alias_row()
    if condition in ('selected', 'imported', 'already_imported'):
        item[condition] = True
    if condition == 'missing_english': item['final']['name_en'] = None
    if condition == 'missing_main': item['final']['bangumi_main'] = None
    if condition == 'other_target': item['final']['bangumi_id'] = '8'
    if condition == 'not_alias': item['stage_hits'] = {}
    batch = {'id': '1234abcd', 'revision': 0, 'state': 'ready', 'rows': [item], 'filename': 'demo.txt'}
    assert bool(preview(batch)['rows']) is included


def test_preview_is_read_only_and_changes_invalidate_approval():
    batch = {'id': '1234abcd', 'revision': 0, 'state': 'ready', 'rows': [alias_row()], 'filename': 'demo.txt'}
    before = copy.deepcopy(batch)
    snapshot = preview(batch)
    assert batch == before  # Opening and cancelling do not select or edit rows.
    approval = [{'index': item['index'], 'token': item['token']} for item in snapshot['rows']]
    assert approved_indices(batch, approval) == [0]
    batch['rows'][0]['final']['note'] = 'changed'
    with pytest.raises(Conflict): approved_indices(batch, approval)
    with pytest.raises(Conflict): approved_indices(batch, [])


@pytest.mark.parametrize('fail_transaction', [False, True])
def test_http_commits_exact_preview_atomically_and_preserves_other_selection(tmp_path, monkeypatch, fail_transaction):
    db = engine()
    with db.begin() as conn:
        conn.execute(text('create table alembic_version (version_num text)'))
        conn.execute(text("insert into alembic_version values ('0016')"))
        receipt = service.commit_rows(conn, [row()])[0]
    class Engine:
        begin = db.begin
        connect = db.connect
        def dispose(self): pass
    monkeypatch.setattr(service, 'engine_for', lambda _: Engine())
    monkeypatch.setattr(service, 'read_config', lambda: {})
    monkeypatch.setattr(service, 'guard', lambda _: None)
    app = create_app(tmp_path)
    batch = app.state.store.create('bulk.txt', 'uploads/bulk.txt')
    a = alias_row(receipt['gpc_id']); a['quote']['lowprice_cny'] = '90'
    b = alias_row(receipt['gpc_id']); b['quote']['lowprice_cny'] = '80'; b['selected'] = True
    unrelated = row(); unrelated['selected'] = True; unrelated['quote']['lowprice_cny'] = '70'
    batch.update(state='ready', rows=[a, b, unrelated]); app.state.store.write(batch)
    before = app.state.store.read(batch['id'])
    if fail_transaction:
        original = service.commit_rows
        def fail(conn, rows, **kwargs):
            original(conn, rows, **kwargs)
            raise ValueError('simulated transaction failure')
        monkeypatch.setattr(service, 'commit_rows', fail)
    with TestClient(app) as client:
        base = '/api/batches/' + batch['id']
        snapshot = client.get(base + '/alias-preview').json()
        assert [r['index'] for r in snapshot['rows']] == [0, 1]
        assert all('proposed_inserts' in r['row'] for r in snapshot['rows'])
        assert all('proposed_inserts' not in r for r in app.state.store.read(batch['id'])['rows'])
        assert app.state.store.read(batch['id']) == before
        payload = {'revision': snapshot['revision'], 'rows': [
            {k: r[k] for k in ('index', 'token')} for r in snapshot['rows']]}
        tampered = copy.deepcopy(payload); tampered['rows'][1]['index'] = 2
        assert client.post(base + '/alias-commit', headers=HEADERS, json=tampered).status_code == 409
        response = client.post(base + '/alias-commit', headers=HEADERS, json=payload)
        assert response.status_code == (422 if fail_transaction else 200)
        saved = app.state.store.read(batch['id'])
        if fail_transaction:
            assert saved == before
        else:
            assert all(r['imported'] for r in saved['rows'][:2])
            assert saved['rows'][2] == unrelated
            # Replaying approval cannot import anything twice.
            assert client.post(base + '/alias-commit', headers=HEADERS, json=payload).status_code == 409
    with db.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(PriceRecord)) == (1 if fail_transaction else 3)


def test_stale_revision_and_historical_preview_are_rejected(tmp_path):
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    batch = app.state.store.create('stale.txt', 'uploads/stale.txt')
    batch.update(state='ready', rows=[alias_row()]); app.state.store.write(batch)
    with TestClient(app) as client:
        base = '/api/batches/' + batch['id']
        snapshot = client.get(base + '/alias-preview').json()
        app.state.store.update(batch['id'], 0, lambda b: b['rows'][0]['quote'].update(lowprice_cny='88'))
        payload = {'revision': snapshot['revision'], 'rows': [{k: r[k] for k in ('index', 'token')} for r in snapshot['rows']]}
        assert client.post(base + '/alias-commit', headers=HEADERS, json=payload).status_code == 409
        app.state.store.update(batch['id'], 1, lambda b: b.update(preview=True))
        assert client.get(base + '/alias-preview').status_code == 422
