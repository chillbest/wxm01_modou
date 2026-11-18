import copy
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.pool import StaticPool
from modou.models import Base, GameAlias, GameProductConfig, PriceRecord, DataSource
from modou.blacklist import add_alias, ensure_sentinel
from modou.bangumi import resolve
from modou.ai_batch import resolve_group
from modou.web.service import prepare_row, edit_row, commit_rows
from modou.web.duplicates import mark_duplicates
from modou.web.proposals import proposed_inserts
from modou.main_ids import normalize_main
from modou.main_subject import MainSubjects
from modou.review_html import main_subject_link
from modou.web.app import create_app
from test_web_app import row, HEADERS, tmp_path


@pytest.fixture
def db():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, record):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def batch():
    return {'id': 'abcd1234', 'source_path': 'uploads/test.txt', 'created_at': '2026-11-19T01:00:00+00:00'}


@pytest.mark.parametrize('ps_disc', [False, True])
def test_blacklist_short_circuits_api_ai_even_when_normal_alias_also_matches(ps_disc):
    api, ai = Mock(), Mock()
    aliases = [{'alias': 'Test', 'gpc_id': 3, 'bangumi_id': '4'},
               {'alias': 'test', 'gpc_id': -1, 'platform': 'blacklist'}]
    resolved = resolve('TEST', '', aliases, [], api, ai, ps_disc=ps_disc)
    assert resolved['blacklisted'] and resolved['stage_hits']['alias']['gpc_id'] == -1
    grouped = resolve_group([resolved], ai, api, 1)[0]
    draft = prepare_row(dict(grouped, quote=row()['quote']), {})
    assert draft['already_imported'] and draft['blacklisted'] and not draft['selected']
    assert not api.mock_calls and not ai.mock_calls


def test_blacklist_idempotency_refresh_provenance_and_no_quote(db):
    with db.begin() as conn:
        add_alias(conn, 'Test', batch())
        add_alias(conn, ' TEST ', batch())
        assert conn.scalar(select(func.count()).select_from(GameAlias)) == 1
        assert conn.scalar(select(GameAlias.gpc_id)) == -1
        assert conn.scalar(select(DataSource.source_path).join(GameAlias, GameAlias.sources_id == DataSource.sources_id)) == 'uploads/test.txt'
        draft = row(); draft['raw_name'] = 'test'
        draft['candidate_lookup'] = {'status': 'pending', 'token': 'old'}
        b = {'rows': [draft]}
        mark_duplicates(conn, b); mark_duplicates(conn, b)
        assert draft['blacklisted'] and draft['already_imported']
        assert 'candidate_lookup' not in draft
        assert proposed_inserts(conn, draft) == []
        from sqlalchemy.orm import Session
        from modou.observations import save_observation
        with Session(bind=conn) as session:
            for sentinel_id in (-1, '-1'):
                with pytest.raises(ValueError, match='黑名单'):
                    save_observation(session, gpc_id=sentinel_id, **row()['quote'])
        with pytest.raises(ValueError, match='黑名单'):
            commit_rows(conn, [draft])
        assert conn.scalar(select(func.count()).select_from(PriceRecord)) == 0


def test_blacklist_endpoint_revision_and_locked_rows(db, tmp_path, monkeypatch):
    import modou.web.service as service
    monkeypatch.setattr(service, 'engine_for', lambda _: db)
    monkeypatch.setattr(db, 'dispose', lambda: None)
    monkeypatch.setattr(service, 'guard', lambda _: None)
    monkeypatch.setattr(service, 'read_config', lambda: {})
    def refresh(b):
        with db.connect() as conn: mark_duplicates(conn, b)
    app = create_app(tmp_path, duplicate_checker=refresh)
    b = app.state.store.create('test.txt', 'uploads/test.txt')
    b.update(state='ready', rows=[row(), row()]); app.state.store.write(b)
    with TestClient(app) as client:
        url = '/api/batches/' + b['id'] + '/rows/0/blacklist'
        bad = client.post(url, headers=HEADERS, json={'revision': 0, 'row_revision': 99, 'text': row()['raw_name']})
        assert bad.status_code == 409
        bad = client.post(url, headers=HEADERS, json={'revision': 0, 'row_revision': 0, 'text': 'tampered'})
        assert bad.status_code == 409
        assert client.post(url, json={}).status_code == 403
        saved = client.post(url, headers=HEADERS, json={'revision': 0, 'row_revision': 0, 'text': row()['raw_name']})
        assert saved.status_code == 200, saved.text
        assert all(r['blacklisted'] and r['already_imported'] for r in saved.json()['rows'])
        again = client.post(url, headers=HEADERS, json={'revision': saved.json()['revision'], 'row_revision': 1, 'text': row()['raw_name']})
        assert again.status_code == 422
        home = client.get('/api/batches').json()
        assert home[0]['imported_count'] == 2
        assert client.get('/api/batches/' + b['id']).json()['rows'][0]['blacklisted']
    with db.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(GameAlias)) == 1
        assert conn.scalar(select(func.count()).select_from(PriceRecord)) == 0


@pytest.mark.parametrize('value', ['1||2', '|1', '1|', '1|abc', '-1|2', '0|2', '１２|3'])
def test_multi_main_rejects_invalid_values(value):
    with pytest.raises(ValueError): normalize_main(value)


def test_multi_main_edit_import_reload_and_links(db):
    draft = row(); b = {'state': 'ready', 'rows': [draft]}
    edit_row(b, 0, {'final': {'bangumi_main': ' 004 | 5 |4 ', 'type': '合集'}})
    assert draft['final']['bangumi_main'] == '4|5'
    draft['status'] = 'confirmed'
    with db.begin() as conn:
        result = commit_rows(conn, [draft])
        product = dict(conn.execute(select(GameProductConfig.__table__).where(GameProductConfig.gpc_id == result[0]['gpc_id'])).mappings().one())
        assert product['bangumi_main'] == '4|5' and product['type'] == '合集'
    resolver = MainSubjects.__new__(MainSubjects); resolver.api = Mock(); resolver.edges = []
    main = resolver.resolve(product)
    assert main['main_id'] == '4|5' and main['relation'] == 'equal'
    assert not resolver.api.mock_calls
    html = main_subject_link('4|5')
    assert 'subject/4' in html and 'subject/5' in html and 'subject/4|5' not in html


def test_frontend_blacklist_filters_highlight_and_main_input():
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    helpers = source.split('(() => {', 1)[0]
    subprocess.run(['node', '-e', helpers + """
const assert=require('node:assert/strict');
assert.equal(normalizeMainInput(' 004 | 5 |4 '),'4|5');
assert.throws(()=>normalizeMainInput('4||5'));
const blocked={blacklisted:true,already_imported:true,selected:false};
assert.equal(selectionCounts([blocked]).imported,1);
assert.equal(rowHidden(blocked,false,true),true);
assert.equal(rowHidden(blocked,false,false),false);
assert.equal(topmostVisibleOriginal([{top:10,bottom:30,left:0,right:100}],0,100,100,[blocked]),-1);
"""], check=True, capture_output=True, text=True)
    assert "onlyPending.setAttribute('aria-checked','true')" in source
    assert "messageDialog('确定要把【'+text+'】要加入黑名单吗？',true)" in source


def test_note_blacklist_skips_local_api_ai_and_main(monkeypatch):
    from datetime import date
    from modou.note_review import build_review
    local, api, ai = Mock(), Mock(), Mock()
    local.path = Path('unused.zip')
    main = Mock()
    main.resolve.return_value = {'status': 'unknown', 'main_id': None}
    monkeypatch.setattr('modou.main_subject.MainSubjects', lambda *args: main)
    rows = build_review('PS好价光盘\n————实时新增————\n合金弹头7 PS4｜HK100｜史低90',
                        'test.txt', date(2026, 11, 19),
                        [{'alias': '合金弹头7', 'gpc_id': -1, 'platform': 'blacklist'},
                         {'alias': '合金弹头7', 'gpc_id': 2, 'platform': 'PS4'}], local, api, ai)
    assert rows[0]['blacklisted']
    assert not local.lookup_many.called and not api.mock_calls and not ai.mock_calls and not main.resolve.called
