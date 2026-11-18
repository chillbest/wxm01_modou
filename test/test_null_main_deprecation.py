import copy
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from modou.models import GameProductConfig
from modou.web.app import create_app
from modou.web.service import edit_row, commit_rows, prepare_row, restore_row
from modou.web.store import Store
from modou.web_review import eligibility_errors
from modou.main_subject import MainSubjects
from modou.web.links import suggest_main
from test_web_app import row, HEADERS, tmp_path
from test_blacklist_main import db


@pytest.mark.parametrize('spaces', [' ', '   ', '\u3000', ' \u3000 '])
def test_spaces_persist_as_explicit_null_and_insert_sql_null(db, tmp_path, spaces):
    app = create_app(tmp_path, duplicate_checker=lambda b: None)
    b = app.state.store.create('test.txt', 'uploads/test.txt')
    r = row(); r['final']['bangumi_main'] = None
    r['parse_baseline'] = copy.deepcopy({k: r[k] for k in ('final','quote','gpc_baseline')})
    b.update(state='ready', rows=[r]); app.state.store.write(b)
    with TestClient(app) as client:
        base = '/api/batches/' + b['id']
        assert 'main待确认' in client.get(base).json()['rows'][0]['eligibility_errors']
        saved = client.post(base+'/rows/0', headers=HEADERS,
                            json={'revision': b['revision'], 'final': {'bangumi_main': spaces}})
        assert saved.status_code == 200, saved.text
        current = client.get(base).json()['rows'][0]
        assert current['final']['bangumi_main'] is None and current['main_explicit_null']
        assert 'final.bangumi_main' in current['manual_fields']
        assert not current['eligibility_errors'] and 2 not in current['red_columns']
        current['status'] = 'confirmed'
        with db.begin() as conn:
            receipt = commit_rows(conn, [current])[0]
            product = dict(conn.execute(select(GameProductConfig.__table__).where(GameProductConfig.gpc_id == receipt['gpc_id'])).mappings().one())
            assert product['bangumi_main'] is None
        resolver = MainSubjects.__new__(MainSubjects); resolver.api = Mock()
        main = resolver.resolve(product)
        assert main['explicit_null'] and not resolver.api.mock_calls
        parsed = dict(row(), stage_hits={'alias': product}, main_resolution=main)
        inherited = prepare_row(parsed, {})
        assert inherited['main_explicit_null'] and inherited['final']['bangumi_main'] is None
        assert not eligibility_errors(inherited)
        # Editing an alias-bound main remains possible.
        edit_row({'state': 'ready', 'rows': [inherited]}, 0, {'final': {'bangumi_main': '7|8'}})
        assert not inherited['main_explicit_null']


def test_missing_empty_and_delete_remain_blocked_and_restore_clears_intent():
    r=row(); r['final']['bangumi_main']=None
    r['parse_baseline']=copy.deepcopy({k:r[k] for k in ('final','quote','gpc_baseline')})
    b={'state':'ready','rows':[r]}
    edit_row(b,0,{'final':{'bangumi_main':' '}})
    assert not eligibility_errors(r)
    restore_row(b,0)
    assert not r['main_explicit_null'] and 'main待确认' in eligibility_errors(r)
    for value in ('',None):
        edit_row(b,0,{'final':{'bangumi_main':' '}})
        edit_row(b,0,{'final':{'bangumi_main':value}})
        assert not r['main_explicit_null'] and 'main待确认' in eligibility_errors(r)
    edit_row(b,0,{'final':{'bangumi_main':' '}})
    edit_row(b,0,{'final':{'bangumi_main':'004 | 5'}})
    assert r['final']['bangumi_main']=='4|5' and not r['main_explicit_null']


def test_null_intent_survives_candidate_switch_and_stale_enrichment(tmp_path,monkeypatch):
    from modou.web import candidate_pick as picks
    from test_candidate_pick import draft, save_choice
    store=Store(tmp_path)
    b, choice=save_choice(store,draft(store),10)
    def enrich(candidate,*args):
        latest=store.read(b['id'])
        store.update(b['id'],latest['revision'],lambda value: edit_row(value,0,{'final':{'bangumi_main':' \u3000 '}}))
        return candidate,{'main_id':'99'},{'type':'Base'}
    monkeypatch.setattr(picks,'enrich',enrich)
    picks.complete(store,b['id'],0,choice[1],choice[2],choice[0],'unused')
    current=store.read(b['id'])
    assert current['rows'][0]['main_explicit_null'] and current['rows'][0]['final']['bangumi_main'] is None
    next_batch, choice=save_choice(store,current,20)
    assert next_batch['rows'][0]['main_explicit_null'] and next_batch['rows'][0]['final']['bangumi_main'] is None


def test_deprecated_main_helper_never_calls_ai_or_api():
    api,ai=Mock(),Mock()
    result=suggest_main({'outlink':'https://gamefaqs.gamespot.com/ps5/1-game'}, {},api=api,suggest=ai)
    assert result['status']=='disabled' and result['main_id'] is None
    assert not api.mock_calls and not ai.mock_calls


def test_space_handler_sends_raw_whitespace_in_browser():
    source=Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    start=source.index('const submittedMain=input.value;')
    end=source.index('if(row.manual_gamefaqs||submittedMain.includes',start)
    handler=source[start:end]
    checks="""
const assert=require('node:assert/strict');
(async()=>{for(const spaces of [' ','  ','\u3000',' \u3000 ']){
const input={value:spaces},inputDrafts=new Map(),i=0,batch={rows:[{main_explicit_null:true}]};
let sent=null,cleared=false,rendered=false;
const quickSave=async(i,payload)=>{sent=payload.final.bangumi_main;};
const clearMainDraft=value=>{cleared=value===spaces;};const render=()=>{rendered=true;};
await (async()=>{HANDLER})();
assert.equal(sent,spaces);assert.equal(cleared,true);assert.equal(rendered,true);
}})().catch(e=>{console.error(e);process.exit(1);});
""".replace('HANDLER',handler)
    subprocess.run(['node','-e',checks],check=True,capture_output=True,text=True)
