"""Behavior regressions for e4b7c2a9; no external services or business DB writes."""
import copy
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from modou.bangumi import english_name, resolve
from modou.models import DataSource, GameProductConfig, GameAlias, PriceRecord
from modou.observations import get_or_create_source
from modou.review_html import render_html
from modou.review_table import release_year, subject_label
from modou.web import candidate_pick as picks
from modou.web.app import create_app
from modou.web.service import alias_bound, edit_row, public_batch, commit_rows
from modou.web.store import Store
from test_web_app import row, HEADERS, tmp_path
from test_submission_review import engine


@pytest.mark.parametrize('info', [
    '|别名={\n[Nioh 3]\n}',
    [{'key': '别名', 'value': [{'v': 'Nioh 3'}]}],
    [{'key': '别名', 'value': 'Nioh 3'}],
])
def test_nioh_unmarked_english_alias(info):
    assert english_name({'name': '仁王3', 'infobox': info}) == 'Nioh 3'


def test_unmarked_english_does_not_override_tagged_english_or_accept_romanization():
    aliases = [{'v': 'Unmarked'}, {'k': '英文', 'v': 'English Title'}]
    assert english_name({'name': '日文', 'infobox': [{'key': '别名', 'value': aliases}]}) == 'English Title'
    assert english_name({'name': '日文', 'infobox': '|别名={\n[罗马字|Nioh]\n}'}) is None


def test_ps_disc_local_unique_must_search_and_keep_distinct_versions_ambiguous():
    old = {'id': 47653, 'name_cn': '鬼武者', 'platforms': ['PS2', 'PS4'], 'date': '2001-01-25'}
    new = {'id': 555555, 'name_cn': '鬼武者 剑之道', 'platforms': ['PS5'], 'date': '2026'}
    calls = []
    api = SimpleNamespace(search=lambda q: calls.append(q) or [new])
    result = resolve('鬼武者', '', [], [old], api, ps_disc=True, defer_ai=True)
    assert calls == ['鬼武者']
    assert {c['id'] for c in result['candidates']} == {47653, 555555}
    assert result['stage_hits'] == {}
    assert result['stage_trace'][1]['candidates'][0]['date'] == '2001-01-25'
    calls.clear()
    alias = dict(old, alias='鬼武者', gpc_id=42, bangumi_id='47653', platform='PS4')
    result = resolve('鬼武者', '', [alias], [old], api, ps_disc=True, defer_ai=True)
    assert result['stage_hits']['alias']['gpc_id'] == 42 and not calls


def test_ps_disc_same_subject_local_and_api_remains_unique():
    game = {'id': 1, 'name': 'Game', 'platforms': ['PS5']}
    result = resolve('Game', '', [], [game], SimpleNamespace(search=lambda _: [game]), ps_disc=True)
    assert len(result['candidates']) == 1 and result['stage_hits']['local']['id'] == 1


def test_candidate_platform_selects_ps5_and_preserves_explicit_manual_override():
    candidate = {'id': 579543, 'name': 'LEGO Batman', 'infobox': [
        {'key': '平台', 'value': [{'v': v} for v in ['PC', 'PS5', 'Xbox Series X/S', 'Nintendo Switch 2']]}]}
    r = row(); r['quote']['platform'] = None; r['final']['bangumi_id'] = None
    r['candidates'] = [candidate]
    b = {'state': 'ready', 'rows': [r]}
    picks.choose(b, 0, {'subject_id': 579543})
    assert r['quote']['platform'] == 'PS5'
    assert r['candidate_lookup']['applied_quote'] == {'platform': 'PS5'}
    edit_row(b, 0, {'quote': {'platform': 'PS4'}})
    r['candidates'].append(dict(candidate, id=2))
    picks.choose(b, 0, {'subject_id': 2})
    assert r['quote']['platform'] == 'PS4'


def alias_row():
    r = row(); r['final']['gpc_id'] = 42
    r['stage_hits'] = {'alias': dict(r['final'], platform='PS5')}
    return r


@pytest.mark.parametrize('payload', [
    {'final': {'type': '母子集'}},
    {'final': {'name_en': 'Tampered'}}, {'final': {'gpc_id': None}},
    {'quote': {'platform': 'PS4'}}, {'quote': {'lowprice_cny': '1'}},
    {'quote': {'region': '美版'}}, {'quote': {'lowprice_method': '积-50'}},
])
def test_alias_binding_rejects_other_column_edits(payload):
    b = {'state': 'ready', 'rows': [alias_row()]}
    before = copy.deepcopy(b)
    with pytest.raises(ValueError, match='备注/显示名及main'):
        edit_row(b, 0, payload)
    assert b == before


def test_alias_binding_allows_column_two_and_unlocks_after_target_change():
    b = {'state': 'ready', 'rows': [alias_row()]}; r = b['rows'][0]
    assert public_batch(b)['rows'][0]['alias_bound']
    edit_row(b, 0, {'final': {'note': 'B2备注', 'display_name': '显示名'}})
    r['candidates'] = [{'id': 123, 'name': 'Another', 'platforms': ['PS4']}]
    picks.choose(b, 0, {'subject_id': 123})
    assert not alias_bound(r) and r['quote']['platform'] == 'PS4'
    edit_row(b, 0, {'final': {'type': 'Base'}})


def test_short_id_collision_retries_and_legacy_link_survives_restart(tmp_path, monkeypatch):
    store = Store(tmp_path / 'batches')
    legacy = store.create('old.txt', 'uploads/old.txt')
    legacy.update(id='a' * 32, state='ready', rows=[row()])
    store.write(legacy)
    values = iter(['12345678' + '0' * 24, '12345678' + '1' * 24, 'abcdef01' + '0' * 24])
    monkeypatch.setattr('modou.web.store.uuid.uuid4', lambda: SimpleNamespace(hex=next(values)))
    # Store.write uses UUIDs for temporary names as well: isolate only generation.
    def write(batch):
        store.path(batch['id']).write_text(json.dumps(batch), encoding='utf-8')
    monkeypatch.setattr(store, 'write', write)
    first = store.create('first.txt', 'uploads/first.txt')
    second = store.create('second.txt', 'uploads/second.txt')
    assert first['id'] == '12345678' and second['id'] == 'abcdef01'
    assert re.fullmatch('[a-f0-9]{8}', first['id'])
    monkeypatch.undo()
    for _ in range(2):
        app = create_app(tmp_path, duplicate_checker=lambda _: None)
        with TestClient(app) as client:
            assert client.get('/review/' + legacy['id']).status_code == 200
            assert client.get('/review/' + first['id']).status_code == 200
    with pytest.raises(ValueError):
        Store(tmp_path / 'batches').path('../outside')


def test_batch_api_reports_final_total_even_before_all_rows_publish(tmp_path):
    app = create_app(tmp_path, duplicate_checker=lambda _: None)
    b = app.state.store.create('demo.txt', 'uploads/demo.txt')
    rows = [row(), row()]; rows[0]['imported'] = True; rows[1]['already_imported'] = True
    b.update(state='reviewable', rows=rows, total_rows=20); app.state.store.write(b)
    with TestClient(app) as client:
        batch = client.get('/api/batches').json()[0]
        assert batch['imported_count'] == 2 and batch['total_rows'] == 20


def test_source_shared_by_catalog_alias_and_quote_and_distinct_between_batches():
    e = engine(); created = '2020-01-02T03:04:00+00:00'
    with e.begin() as c:
        first = commit_rows(c, [row()], review_batch_id='12345678', batch_created_at=created)[0]
        sid = c.scalar(select(PriceRecord.sources_id))
        assert c.scalar(select(GameProductConfig.sources_id)) == sid
        assert c.scalar(select(GameAlias.sources_id)) == sid
    with e.begin() as c:
        r = row(); r['quote']['lowprice_cny'] = '90'
        commit_rows(c, [r], review_batch_id='12345678', batch_created_at=created)
        assert c.scalar(select(func.count()).select_from(DataSource)) == 1
        source = c.execute(select(DataSource.__table__)).mappings().one()
        assert source['recorded_at'].replace(tzinfo=timezone.utc) == datetime.fromisoformat(created)
        r['quote']['lowprice_cny'] = '80'
        commit_rows(c, [r], review_batch_id='abcdef01', batch_created_at=created)
        assert c.scalar(select(func.count()).select_from(DataSource)) == 2
        r['quote']['source_path'] = 'other.txt'
        commit_rows(c, [r], review_batch_id='87654321', batch_created_at=created)
        assert c.scalar(select(func.count()).select_from(DataSource)) == 2
        assert c.scalar(select(GameProductConfig.sources_id).where(GameProductConfig.gpc_id == first['gpc_id'])) == sid


def test_missing_batch_time_fails_without_fabricating_source():
    e = engine()
    with e.begin() as c, Session(bind=c) as session:
        with pytest.raises(ValueError, match='创建时间'):
            get_or_create_source(session, 'a', review_batch_id='12345678')
        assert c.scalar(select(func.count()).select_from(DataSource)) == 0


def test_year_prefix_in_hit_trace_but_not_b_row():
    r = row(); candidate = {'id': 614361, 'name_cn': '黑旗 记忆重置', 'date': '2026-10-01'}
    r['candidates'] = [candidate]; r['stage_hits'] = {'api': candidate}
    r['stage_trace'] = [{'stage': 'BangumiAPI', 'result': '命中', 'reason': '唯一候选',
                         'candidates': [{'id': 614361, 'name_cn': '黑旗 记忆重置'}]}]
    html = render_html([r], 'demo', None, online=True)
    b_row = html.split('class="b-row"', 1)[1].split('</tr>', 1)[0]
    assert '2026 · ' not in b_row
    assert '2026 · 黑旗 记忆重置' in html
    assert release_year({'infobox': '|发行日期= 2026年5月22日'}) == '2026'
    assert '2026 · ' in subject_label(candidate, include_year=True)


def test_frontend_candidate_year_and_home_labels():
    helpers = Path('src/modou/web/static/review.js').read_text(encoding='utf-8').split('(() => {', 1)[0]
    home = Path('src/modou/web/static/home.js').read_text(encoding='utf-8')
    label = home[home.index('function batchLabel('):home.index('async function poll(')]
    checks = """
const assert=require('node:assert/strict');
assert.equal(candidateYear({date:'2026-05-22'}),'2026');
assert.equal(candidateYear({infobox:[{key:'发行日期',value:'2026年5月22日'}]}),'2026');
assert.equal(candidateYear({}), '');
assert.equal(batchLabel({state:'ready',filename:'demo.txt',imported_count:1,total_rows:20}),'入库1/20：《demo.txt》');
assert.equal(batchLabel({state:'queued',filename:'demo.txt'}),'排队中：《demo.txt》');
assert.equal(batchLabel({state:'reviewable',filename:'demo.txt',imported_count:1}),'入库1/解析中：《demo.txt》');
"""
    subprocess.run(['node', '-e', helpers + label + checks], check=True, capture_output=True)


def test_sticky_title_only_appears_after_heading_scrolls_away_and_centers_in_gap():
    js = Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    update = js[js.index('function updateStickyTitle()'):js.index('\nlet titleFrame=')]
    checks = """
const assert=require('node:assert/strict');
let headingBottom=80, rightLeft=400;const modes=new Set();
const titlebar={getBoundingClientRect:()=>({bottom:headingBottom})};
const stickyTitle={hidden:false,style:{},classList:{toggle:(k,v)=>v?modes.add(k):modes.delete(k)}};
const toolbar={getBoundingClientRect:()=>({left:20,top:0})};
const onlyPending={getBoundingClientRect:()=>({left:rightLeft})};
const document={querySelector:()=>({getBoundingClientRect:()=>({right:100,top:10,bottom:40})})};
updateStickyTitle();assert.equal(stickyTitle.hidden,true);
headingBottom=-1;updateStickyTitle();assert.equal(stickyTitle.hidden,false);
assert.equal(Number.parseFloat(stickyTitle.style.left)+Number.parseFloat(stickyTitle.style.width)/2,(100+400)/2-20);
assert.equal(modes.has('web-title-own-row'),false);
rightLeft=150;updateStickyTitle();assert.equal(modes.has('web-title-own-row'),true);
headingBottom=80;updateStickyTitle();assert.equal(stickyTitle.hidden,true);
"""
    subprocess.run(['node', '-e', update + checks], check=True, capture_output=True)
