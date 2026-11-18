import copy
import threading
import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_web_app import row, HEADERS
from test_web_batches import tmp_path
from modou.web.app import create_app
from modou.web.store import Store, Conflict
from modou.web import candidate_pick as picks
from modou.main_subject import MainSubjects, cached_edges


def draft(store):
    batch = store.create('demo.txt', 'uploads/demo.txt')
    r = row()
    r['candidates'] = [{'id': 10, 'name_cn': '候选甲', 'name': 'Game A', 'platforms': ['PS5']},
                       {'id': 20, 'name_cn': '候选乙', 'name': 'Game B', 'platforms': ['PS5']}]
    r['parse_baseline'] = copy.deepcopy({k: r[k] for k in ('final', 'quote', 'gpc_baseline')})
    batch.update(state='ready', rows=[r])
    store.write(batch)
    return batch


def save_choice(store, batch, sid):
    picked = []
    def change(b): picked.extend(picks.choose(b, 0, {'subject_id': sid}))
    saved = store.update(batch['id'], batch['revision'], change)
    return saved, picked


def test_fast_endpoint_returns_while_enrichment_is_blocked(tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()
    def slow(candidate, platform, dump):
        started.set()
        assert release.wait(5)
        return candidate, {'main_id': '10', 'status': 'self'}, {'type': 'Base'}
    monkeypatch.setattr(picks, 'enrich', slow)
    def forbidden(_): pytest.fail('candidate save must not wait for duplicate DB checks')
    app = create_app(tmp_path, duplicate_checker=forbidden)
    b = draft(app.state.store)
    try:
        with TestClient(app) as client:
            try:
                response = client.post(f'/api/batches/{b["id"]}/rows/0/candidate', headers=HEADERS,
                                       json={'revision': 0, 'row_revision': 0, 'subject_id': 10})
                assert response.status_code == 200
                assert started.wait(1)
                r = response.json()['rows'][0]
                assert r['final']['bangumi_id'] == '10'
                assert r['candidate_lookup']['status'] == 'pending'
                assert not release.is_set()
            finally:
                release.set()
    finally:
        release.set()
    assert app.state.store.read(b['id'])['rows'][0]['final']['bangumi_main'] == '10'


def test_old_completion_never_overwrites_new_choice(tmp_path, monkeypatch):
    store = Store(tmp_path)
    b, first = save_choice(store, draft(store), 10)
    started, release = threading.Event(), threading.Event()
    def slow(c, *args):
        started.set(); assert release.wait(5)
        return c, {'main_id': '999'}, {'type': 'Base'}
    monkeypatch.setattr(picks, 'enrich', slow)
    worker = threading.Thread(target=picks.complete, args=(store, b['id'], 0, first[1], first[2], first[0], 'unused'))
    worker.start()
    try:
        assert started.wait(1)
        b, second = save_choice(store, store.read(b['id']), 20)
    finally:
        release.set(); worker.join(5)
    final = store.read(b['id'])['rows'][0]
    assert final['final']['bangumi_id'] == '20'
    assert final['final']['bangumi_main'] is None
    assert final['candidate_lookup']['token'] == second[1]


def test_manual_changes_after_lookup_start_are_preserved(tmp_path, monkeypatch):
    store = Store(tmp_path)
    b, selected = save_choice(store, draft(store), 10)
    def enrich(c, *args):
        def edit(b):
            picks.edit_row(b, 0, {'final': {'bangumi_main': '77'}})
        store.update(b['id'], store.read(b['id'])['revision'], edit)
        return c, {'main_id': '99'}, {'type': 'Base'}
    monkeypatch.setattr(picks, 'enrich', enrich)
    picks.complete(store, b['id'], 0, selected[1], selected[2], selected[0], 'unused')
    r = store.read(b['id'])['rows'][0]
    assert r['final']['bangumi_main'] == '77'
    assert r['candidate_lookup']['status'] == 'superseded'


def test_queued_job_cancels_before_network_after_manual_edit(tmp_path, monkeypatch):
    store = Store(tmp_path)
    b, selected = save_choice(store, draft(store), 10)
    def edit(b): picks.edit_row(b, 0, {'final': {'note': 'manual'}})
    store.update(b['id'], b['revision'], edit)
    monkeypatch.setattr(picks, 'enrich', lambda *a: pytest.fail('obsolete job made a network request'))
    picks.complete(store, b['id'], 0, selected[1], selected[2], selected[0], 'unused')
    r = store.read(b['id'])['rows'][0]
    assert r['final']['note'] == 'manual'
    assert r['candidate_lookup']['status'] == 'superseded'


def test_background_hydration_reuses_local_gpc_fields(tmp_path, monkeypatch):
    store = Store(tmp_path)
    b, selected = save_choice(store, draft(store), 10)
    def enriched(c, *args):
        return dict(c, gpc_id=42, name_zh='本地名', note='本地备注'), {'main_id': '10'}, {'type': 'Base'}
    monkeypatch.setattr(picks, 'enrich', enriched)
    picks.complete(store, b['id'], 0, selected[1], selected[2], selected[0], 'unused')
    r = store.read(b['id'])['rows'][0]
    assert r['final']['gpc_id'] == 42 and r['final']['note'] == '本地备注'
    assert r['gpc_baseline']['name_zh'] == '本地名'


def test_next_choice_does_not_inherit_previous_automatic_main(tmp_path, monkeypatch):
    store = Store(tmp_path)
    b, selected = save_choice(store, draft(store), 10)
    monkeypatch.setattr(picks, 'enrich', lambda c, *a: (c, {'main_id': '10'}, {'type': 'Base'}))
    picks.complete(store, b['id'], 0, selected[1], selected[2], selected[0], 'unused')
    latest = store.read(b['id'])
    assert latest['rows'][0]['final']['bangumi_main'] == '10'
    next_batch, _ = save_choice(store, latest, 20)
    assert next_batch['rows'][0]['final']['bangumi_main'] is None


def test_temporary_red_clears_after_enrichment(tmp_path, monkeypatch):
    store = Store(tmp_path)
    b = draft(store)
    picks.refresh_review_state(b['rows'][0])
    assert b['rows'][0]['red_columns'] == []
    store.write(b)
    b, selected = save_choice(store, b, 10)
    assert {2, 3}.issubset(b['rows'][0]['red_columns'])
    monkeypatch.setattr(picks, 'enrich', lambda c, *a: (c, {'main_id': '10'}, {'type': 'Base'}))
    picks.complete(store, b['id'], 0, selected[1], selected[2], selected[0], 'unused')
    assert store.read(b['id'])['rows'][0]['red_columns'] == []


def test_return_to_original_reuses_main_type_and_clears_red(tmp_path):
    store = Store(tmp_path)
    b = draft(store)
    b['rows'][0]['candidates'].append({'id': 4, 'name_cn': '原始候选'})
    picks.refresh_review_state(b['rows'][0]);store.write(b)
    b, _ = save_choice(store, b, 10)
    b, selected = save_choice(store, b, 4)
    r = b['rows'][0]
    assert r['final']['bangumi_main'] == '4' and r['final']['type'] == 'Base'
    assert r['red_columns'] == []
    assert selected[0]['bangumi_main'] == '4'


def test_restore_cancels_lookup_and_ignores_late_completion(tmp_path, monkeypatch):
    from modou.web.service import restore_row
    store = Store(tmp_path)
    b, selected = save_choice(store, draft(store), 10)
    def enriched(c, *args):
        latest = store.read(b['id'])
        store.update(b['id'], latest['revision'], lambda b: restore_row(b, 0))
        return c, {'main_id': '999'}, {'type': '母子集'}
    monkeypatch.setattr(picks, 'enrich', enriched)
    picks.complete(store, b['id'], 0, selected[1], selected[2], selected[0], 'unused')
    r = store.read(b['id'])['rows'][0]
    assert r['final'] == r['parse_baseline']['final']
    assert r['red_columns'] == [] and 'candidate_lookup' not in r


@pytest.mark.parametrize('flag', ['selected', 'imported', 'already_imported'])
def test_locked_rows_cannot_choose(tmp_path, flag):
    store = Store(tmp_path); b = draft(store)
    b['rows'][0][flag] = True
    with pytest.raises(ValueError): picks.choose(b, 0, {'subject_id': 10})


def test_forged_candidate_is_rejected(tmp_path):
    store = Store(tmp_path); b = draft(store)
    with pytest.raises(ValueError): picks.choose(b, 0, {'subject_id': 999})


def test_background_revision_does_not_reject_following_choice(tmp_path, monkeypatch):
    jobs = []
    class DeferredPool:
        def __init__(self, **kwargs): pass
        def submit(self, fn, *args): jobs.append((fn, args))
        def shutdown(self, **kwargs): pass
    monkeypatch.setattr('modou.web.app.ThreadPoolExecutor', DeferredPool)
    monkeypatch.setattr(picks, 'enrich', lambda c, *a: (c, {'main_id': '10'}, {'type': 'Base'}))
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    b = draft(app.state.store)
    with TestClient(app) as client:
        url = f'/api/batches/{b["id"]}/rows/0/candidate'
        first = client.post(url, headers=HEADERS, json={'row_revision': 0, 'subject_id': 10}).json()
        lookup = first['rows'][0]['candidate_lookup']
        fn, args = jobs.pop(); fn(*args)
        payload = {'row_revision': 1, 'revision': first['revision'], 'subject_id': 20,
                   'lookup_status': 'pending', 'lookup_token': lookup['token']}
        second = client.post(url, headers=HEADERS, json=payload)
        assert second.status_code == 200
        assert second.json()['rows'][0]['final']['bangumi_id'] == '20'
        # A stale manual edit is not equivalent to the one background completion.
        assert client.post(url, headers=HEADERS, json=payload).status_code == 409


def test_gamefaqs_choice_does_not_call_ai_or_fetch_webpage(monkeypatch):
    monkeypatch.setattr(picks, 'hydrate_candidate', lambda c, p: c)
    c = {'outlink': 'https://gamefaqs.gamespot.com/ps4/123-game'}
    monkeypatch.setattr('modou.web.links.suggest_main', lambda *a: pytest.fail('unexpected AI'))
    monkeypatch.setattr('modou.web.links.gamefaqs', lambda *a: pytest.fail('unexpected webpage fetch'))
    result, main, types = picks.enrich(c, 'PS4', 'unused')
    assert main['status'] == 'unknown' and main['main_id'] is None


def test_relation_cache_reuses_and_invalidates(tmp_path):
    p = tmp_path / 'dump.zip'
    def write(sid):
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('subject-relations.jsonlines', '{"relation_type":4017,"subject_id":'+str(sid)+',"related_subject_id":1}')
    cached_edges.cache_clear()
    write(2)
    first = MainSubjects(p, None)
    with patch('modou.main_subject.read_edges', side_effect=AssertionError('reopened dump')):
        assert MainSubjects(p, None).edges is first.edges
    write(300)
    assert MainSubjects(p, None).edges == frozenset({('300', '1')})


def test_frontend_switches_before_save_and_latest_choice_wins():
    import subprocess
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    helper = source[source.index('function sameTarget('):source.index('function selectionCounts(')]
    controller = source[source.index('async function pickKnownCandidate('):source.index('function renderProposals(')]
    harness = r'''
const assert=require('node:assert/strict');
let batch={id:'x',revision:0,rows:[{revision:0,final:{bangumi_id:'4'},manual_fields:[]}]};
const candidatePending=new Map();let candidateSequence=0,queue=Promise.resolve(),pending=0,busy=false;
const events=[],requests=[];let release;
function render(i){events.push(candidatePending.get(i)?.row.final.bangumi_id||batch.rows[i].final.bangumi_id);}
function show(){}function syncChecks(){}
function post(path,data){requests.push(data);return new Promise(r=>{release=r;});}
async function adopt(saved){batch=saved;}
'''
    checks = r'''
(async()=>{
const first=pickKnownCandidate(0,{id:10,name_cn:'A'});
assert.equal(events.at(-1),'10');assert.equal(requests.length,0);
await new Promise(setImmediate);assert.equal(requests.length,1);
const second=pickKnownCandidate(0,{id:20,name_cn:'B'});
assert.equal(events.at(-1),'20');
release({id:'x',revision:1,rows:[{revision:1,final:{bangumi_id:'10'},manual_fields:[]}]});
await first;await new Promise(setImmediate);
assert.equal(events.at(-1),'20');assert.equal(requests[1].subject_id,20);
release({id:'x',revision:2,rows:[{revision:2,final:{bangumi_id:'20'},manual_fields:[]}]});
await second;assert.equal(events.at(-1),'20');assert.equal(candidatePending.size,0);
assert.equal(pending,0);assert.equal(busy,false);
})().catch(e=>{console.error(e);process.exit(1);});
'''
    subprocess.run(['node', '-e', harness + helper + controller + checks], check=True, capture_output=True, text=True)
