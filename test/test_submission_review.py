import copy
from datetime import date
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import pytest
from fastapi.testclient import TestClient
from modou.models import Base, DataSource, GameProductConfig, PriceRecord
from modou.web.service import commit_rows, edit_row, prepare_row, restore_row
from modou.web.duplicates import SimilarProducts, mark_duplicates
from modou.web.app import create_app
from test_web_app import row, HEADERS, tmp_path
from test_gpc_schema import connection


def engine():
    e = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(e)
    return e


def test_submission_sources_share_only_within_the_same_review_batch():
    e = engine()
    with e.begin() as c:
        a, b = row(), row(); b['quote']['platform'] = 'PS4'
        first = commit_rows(c, [a, b], review_batch_id='1234abcd', batch_created_at='2026-11-18T01:00:00+00:00')
        assert c.scalar(select(func.count()).select_from(DataSource)) == 1
    with e.begin() as c:
        a = row(); a['quote']['lowprice_cny'] = '90'
        commit_rows(c, [a], review_batch_id='1234abcd', batch_created_at='2026-11-18T01:00:00+00:00')
        assert c.scalar(select(func.count()).select_from(DataSource)) == 1
        sources = c.execute(select(DataSource.__table__)).mappings().all()
        assert len(sources) == 1
        assert c.scalar(select(GameProductConfig.sources_id).where(GameProductConfig.gpc_id == first[0]['gpc_id'])) == sources[0]['sources_id']
    with e.begin() as c:
        a = row(); a['quote']['source_path'] = 'different.txt'
        assert commit_rows(c, [a]) == [{k:v for k,v in first[0].items() if k != 'added'}]
        assert c.scalar(select(func.count()).select_from(DataSource)) == 1
        assert c.scalar(select(func.count()).select_from(PriceRecord)) == 3


def test_similar_insert_requires_current_snapshot_and_exact_identity_reuses():
    e = engine()
    with e.begin() as c:
        commit_rows(c, [row()])
        alternative = row()
        alternative['final']['outlink'] = 'https://gamefaqs.gamespot.com/ps5/1-game'
        with pytest.raises(SimilarProducts) as error: commit_rows(c, [alternative])
        token = error.value.conflicts[0]['token']
        assert error.value.conflicts[0]['existing'][0]['bangumi_id'] == '4'
        c.execute(GameProductConfig.__table__.update().values(note='changed'))
        with pytest.raises(SimilarProducts) as newer: commit_rows(c, [alternative], confirmations=[token])
        result = commit_rows(c, [alternative], confirmations=[newer.value.conflicts[0]['token']])
        assert len(result) == 1
        assert commit_rows(c, [alternative]) == [{k:v for k,v in result[0].items() if k != 'added'}]


def test_duplicate_only_locks_when_all_required_fields_are_known():
    e = engine()
    with e.begin() as c:
        commit_rows(c, [row()])
        batch = {'rows': [row()]}
        mark_duplicates(c, batch)
        assert batch['rows'][0]['already_imported'] and batch['rows'][0]['selected']
        with pytest.raises(ValueError): edit_row(dict(batch, state='ready'), 0, {'final': {'type': 'rebase'}})
        incomplete = row(); incomplete['final']['type'] = None
        batch = {'rows': [incomplete]}; mark_duplicates(c, batch)
        assert not batch['rows'][0].get('already_imported')


def test_missing_bangumi_ids_do_not_imply_similarity_and_exact_links_still_reuse():
    e = engine()
    with e.begin() as c:
        first = row()
        first['final'].update(bangumi_id=None, outlink='https://vgcollect.com/item/265632',
                              name_zh='艾尔登法环 黄金树幽影版')
        first_receipt = commit_rows(c, [first])[0]
        other = row()
        other['final'].update(bangumi_id=None, outlink='https://vgcollect.com/item/205944',
                              bangumi_main='105697', name_zh='神秘海域4+dlc')
        second_receipt = commit_rows(c, [other])[0]
        assert first_receipt['gpc_id'] != second_receipt['gpc_id']
        assert commit_rows(c, [other])[0]['record_id'] == second_receipt['record_id']
        changed_price = copy.deepcopy(other)
        changed_price['quote']['lowprice_cny'] = '90'
        assert commit_rows(c, [changed_price])[0]['gpc_id'] == second_receipt['gpc_id']
        assert c.scalar(select(func.count()).select_from(GameProductConfig)) == 2


def test_gamefaqs_manual_name_is_required_and_tracks_display_name():
    b = {'state': 'ready', 'rows': [row()]}
    link = 'https://gamefaqs.gamespot.com/ps5/1-game'
    edit_row(b, 0, {'manual_resolution': {'candidate': {'outlink': link}},
                   'final': {'outlink': link, 'display_name': '中文产品名'}})
    assert b['rows'][0]['final']['name_zh'] == '中文产品名'
    edit_row(b, 0, {'final': {'display_name': '新名字'}})
    assert b['rows'][0]['final']['name_zh'] == '新名字'
    with pytest.raises(ValueError): edit_row(copy.deepcopy(b), 0, {'final': {'display_name': ''}})


def test_prepared_type_suggestion_and_unknown_candidates_survive():
    raw = row(); raw['stage_hits'] = {'local': {'id': 4, 'name_cn': 'Game'}}
    raw['type_resolution'] = {'type': 'rebase', 'candidates': [], 'evidence': []}
    assert prepare_row(raw, {}, suggest_missing=False)['final']['type'] == 'rebase'
    raw['type_resolution'].update(type=None, candidates=[{'type': 'rebase', 'evidence_ids': ['E1']}])
    prepared = prepare_row(raw, {}, suggest_missing=False)
    assert prepared['final']['type'] is None and prepared['type_resolution']['candidates']


def test_http_refresh_persists_early_lock_and_clear_cannot_unlock(tmp_path):
    e = engine()
    with e.begin() as c: commit_rows(c, [row()])
    def check(batch):
        with e.connect() as c: mark_duplicates(c, batch)
    app = create_app(tmp_path, duplicate_checker=check)
    b = app.state.store.create('a.txt', 'a.txt'); b.update(state='ready', rows=[row()]); app.state.store.write(b)
    with TestClient(app) as client:
        url = '/api/batches/' + b['id']
        data = client.get(url).json()
        assert data['rows'][0]['already_imported'] and data['rows'][0]['selected']
        response = client.post(url + '/clear', json={'revision': data['revision']}, headers=HEADERS)
        assert response.json()['rows'][0]['selected']
        assert app.state.store.read(b['id'])['rows'][0]['already_imported']


def test_http_similar_confirmation_returns_table_and_rechecks_token(tmp_path):
    e = engine()
    with e.begin() as c: commit_rows(c, [row()])
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    r = row(); r['selected'] = True
    r['final']['outlink'] = 'https://gamefaqs.gamespot.com/ps5/1-game'
    b = app.state.store.create('a.txt', 'a.txt'); b.update(state='ready', rows=[r]); app.state.store.write(b)
    def commit(batch, confirmations=()):
        with e.begin() as c:
            receipts = commit_rows(c, [dict(batch['rows'][0], status='confirmed')], confirmations=confirmations)
        batch['rows'][0].update(imported=True, selected=False, receipt=receipts[0])
    app.state.commit_batch = commit
    with TestClient(app) as client:
        url = '/api/batches/' + b['id'] + '/commit'
        response = client.post(url, headers=HEADERS, json={'revision': 0})
        assert response.status_code == 409
        conflicts = response.json()['similar_products']
        assert conflicts[0]['existing'][0]['platform'] == 'PS5'
        assert app.state.store.read(b['id'])['revision'] == 0
        with e.begin() as c: c.execute(GameProductConfig.__table__.update().values(note='changed'))
        response = client.post(url, headers=HEADERS, json={'revision': 0, 'similar_confirmations': [conflicts[0]['token']]})
        assert response.status_code == 409
        token = response.json()['similar_products'][0]['token']
        response = client.post(url, headers=HEADERS, json={'revision': 0, 'similar_confirmations': [token]})
        assert response.status_code == 200 and response.json()['rows'][0]['imported']


def test_source_migration_preserves_existing_rows_and_times(connection):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import text, inspect
    spec = importlib.util.spec_from_file_location('source_submission_migration', Path('migrations/versions/0013_source_submissions.py'))
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    c = connection
    c.execute(text('ALTER TABLE data_source ADD CONSTRAINT qa_source_unique UNIQUE (source_path)'))
    c.execute(text("INSERT INTO data_source(source_path,recorded_at) VALUES ('old.txt','2020-01-01T00:00:00Z')"))
    before = c.execute(select(DataSource.__table__)).mappings().all()
    migration.op = Operations(MigrationContext.configure(c))
    migration.upgrade()
    assert c.execute(select(DataSource.__table__)).mappings().all() == before
    assert inspect(c).get_unique_constraints('data_source') == []
    c.execute(text("INSERT INTO data_source(source_path) VALUES ('old.txt')"))
    assert c.scalar(select(func.count()).select_from(DataSource)) == 2


def test_commit_rechecks_duplicate_under_transaction_lock(connection, monkeypatch):
    from contextlib import nullcontext
    from unittest.mock import Mock
    from modou.web import service
    commit_rows(connection, [row()])
    selected = row(); selected['selected'] = True
    batch = {'rows': [selected]}
    mocked_engine = Mock(); mocked_engine.begin.return_value = nullcontext(connection)
    monkeypatch.setattr(service, 'engine_for', lambda _: mocked_engine)
    monkeypatch.setattr(service, 'read_config', lambda: {})
    assert service.commit_batch(batch) == []
    assert selected['already_imported'] and selected['selected'] and not selected['imported']
    assert connection.scalar(select(func.count()).select_from(DataSource)) == 1


@pytest.mark.parametrize('created', ['2020-01-01T00:00:00+00:00', '2026-11-18T01:00:00+00:00'])
def test_source_batch_reuse_is_independent_of_elapsed_time(created):
    from datetime import datetime, timezone
    from modou.observations import get_or_create_source
    e = engine()
    with e.begin() as c, Session(bind=c) as session:
        source = get_or_create_source(session, 'window.txt', '2026-11-03', review_batch_id='0123abcd', recorded_at=created)
        first_id = source.sources_id
    with e.begin() as c, Session(bind=c) as session:
        source = get_or_create_source(session, 'window.txt', '2026-11-03', review_batch_id='0123abcd', recorded_at=created)
        assert source.sources_id == first_id
        assert source.recorded_at.replace(tzinfo=timezone.utc) == datetime.fromisoformat(created)
    with e.begin() as c, Session(bind=c) as session:
        source = get_or_create_source(session, 'window.txt', '2026-11-03', review_batch_id='0123abce', recorded_at=created)
        assert source.sources_id != first_id
        assert get_or_create_source(session, 'window.txt', '2026-11-03').sources_id != source.sources_id


def test_source_date_conflict_and_different_paths():
    from modou.observations import get_or_create_source
    e = engine()
    with e.begin() as c, Session(bind=c) as session:
        context = dict(review_batch_id='0123abcd', recorded_at='2026-11-18T01:00:00+00:00')
        first = get_or_create_source(session, 'a.txt', '2026-11-03', **context)
        other = get_or_create_source(session, 'b.txt', '2026-11-03')
        assert first.sources_id != other.sources_id
        with pytest.raises(ValueError, match='发布日期冲突'):
            get_or_create_source(session, 'a.txt', '2026-11-04', **context)
        with pytest.raises(ValueError, match='路径冲突'):
            get_or_create_source(session, 'b.txt', '2026-11-03', **context)


@pytest.mark.parametrize('main', ['4', '100'])
def test_main_preserved_in_preview_and_database(main):
    from modou.web.proposals import proposed_inserts
    e = engine()
    r = row(); r['final']['bangumi_main'] = main
    with e.begin() as c:
        preview = proposed_inserts(c, r)
        assert next(p for p in preview if p['table'] == 'game_product_config')['values']['bangumi_main'] == main
        result = commit_rows(c, [r])
        assert c.scalar(select(GameProductConfig.bangumi_main).where(GameProductConfig.gpc_id == result[0]['gpc_id'])) == main
