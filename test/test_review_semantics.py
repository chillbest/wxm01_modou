import copy
import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from modou.bangumi import english_name
from modou.web.service import prepare_row, normalize_draft, refresh_review_state, edit_row, commit_rows
from modou.web.proposals import proposed_inserts
from modou.models import PriceRecord
from test_web_app import row
from test_submission_review import engine


@pytest.mark.parametrize('info', [
    [{'key':'别名','value':[{'k':'罗马字','v':'Sora no Kiseki the 2nd'},{'k':'英文','v':'Trails in the Sky 2nd Chapter'}]}],
    '|别名 = {\n[罗马字|Sora no Kiseki the 2nd]\n[英文|Trails in the Sky 2nd Chapter]\n}\n|平台 = PS5',
])
def test_english_alias_precedes_original_and_romanization(info):
    assert english_name({'name':'空の軌跡 the 2nd','infobox':info}) == 'Trails in the Sky 2nd Chapter'


@pytest.mark.parametrize('name,expected',[('Game 2: A & B!', 'Game 2: A & B!'),('空の軌跡 the 2nd',None),('123!?',None)])
def test_english_original_fallback(name,expected):
    assert english_name({'name':name}) == expected


@pytest.mark.parametrize('name', ['Pokémon', 'Pokémo\u0301n', 'Été', 'Łódź 2: ★', 'Æsir'])
def test_english_original_accepts_latin_diacritics(name):
    assert english_name({'name':name}) == name


@pytest.mark.parametrize('name', ['Game 日本', 'Game Ελληνικά', 'Game Русский', 'Game\u200b', '\u0301Game', '123!?'])
def test_english_original_rejects_other_scripts_and_invalid_marks(name):
    assert english_name({'name':name}) is None


@pytest.mark.parametrize('info', [
    [{'key':'别名','value':[{'k':'','v':'Unmarked Alias'},{'k':'罗马字','v':'Romanized Alias'}]}],
    '|别名 = {\n[Unmarked Alias]\n[罗马字|Romanized Alias]\n}',
])
def test_english_name_accepts_unmarked_alias_without_candidate_field_fallback(info):
    candidate = {'name':'日本語', 'name_en':'Extra Fallback', 'infobox':info}
    assert english_name(candidate) == 'Unmarked Alias'
    candidate['name'] = 'Pokémon'
    assert english_name(candidate) == 'Unmarked Alias'


@pytest.mark.parametrize('info', [
    [{'key':'英文名','value':'Pokémon'}],
    [{'key':'别名','value':[{'k':'英文','v':'Pokémon'}]}],
    '|别名 = {\n[英文|Pokémon]\n}',
])
def test_english_alias_accepts_diacritics_and_precedes_original(info):
    assert english_name({'name':'Original', 'infobox':info}) == 'Pokémon'


def test_existing_gpc_english_name_is_preserved():
    assert english_name({'gpc_id':1, 'name_en':'Stored Title', 'name':'Original'}) == 'Stored Title'


def candidate_row():
    r=row();c={'id':4,'name':'空の軌跡 the 2nd','type':4,'infobox':[{'key':'别名','value':[{'k':'英文','v':'Trails in the Sky 2nd Chapter'}]}]}
    r.update(stage_hits={'api':c},candidates=[c],type_resolution={'type':'Base'})
    return r


def test_bangumi_category_never_becomes_gpc_type():
    r=candidate_row();prepared=prepare_row(r,{},suggest_missing=False)
    assert prepared['final']['type']=='Base'
    assert prepared['final']['name_en']=='Trails in the Sky 2nd Chapter'
    r['type_resolution']={'type':None}
    assert prepare_row(r,{},suggest_missing=False)['final']['type'] is None


def test_old_draft_repair_preserves_manual_name_and_evidence():
    r=candidate_row();r['final'].update(type=4,name_en='空の軌跡 the 2nd')
    r['parse_baseline']=copy.deepcopy({'final':r['final'],'quote':r['quote']})
    evidence=copy.deepcopy(r['candidates']);normalize_draft(r)
    assert r['final']['type']=='Base' and r['parse_baseline']['final']['type']=='Base'
    assert r['final']['name_en']=='Trails in the Sky 2nd Chapter'
    assert r['candidates']==evidence
    r['final']['name_en']='Karl edit';r['manual_fields']=['final.name_en']
    normalize_draft(r);assert r['final']['name_en']=='Karl edit'


def test_unknown_english_edit_keeps_red_history_and_manual_stripes():
    r=row();refresh_review_state(r)
    assert r['name_en_unknown']
    b={'state':'ready','rows':[r]}
    edit_row(b,0,{'final':{'name_en':'English Title'}})
    assert r['name_en_unknown'] and 'final.name_en' in r['manual_fields']
    refresh_review_state(r)
    assert r['name_en_unknown'] and 'final.name_en' in r['manual_fields']


def test_preview_optional_columns_alias_and_stored_primary_keys():
    e=engine()
    with e.begin() as c:
        r=row();r['final']['type']=None
        preview=proposed_inserts(c,r)
        gpc=preview[0]['values'];assert gpc['type'] is None
        assert not {'note','display_name','outlink'} & gpc.keys()
        assert set(preview[1]['values'])=={'alias'}
        r['final'].update(type='Base',note='note',display_name='display')
        assert proposed_inserts(c,r)[0]['values']['note']=='note'
        receipt=commit_rows(c,[r])[0];r.update(imported=True,receipt=receipt)
        stored=proposed_inserts(c,r)
        assert [p['values'][key] for p,key in zip(stored,['gpc_id','alias_id','record_id'])]==[receipt['gpc_id'],1,receipt['record_id']]
        assert all(p['operation']=='新增' for p in stored)
        assert all(v is not None and v!='' for p in stored for v in p['values'].values())
        assert stored[-1]['values']['lowprice_method']=='直接购买'
        r['receipt']={'record_id':receipt['record_id'],'added':[]}
        assert all(p['operation']=='复用' for p in proposed_inserts(c,r))
        with pytest.raises(IntegrityError):
            with c.begin_nested():
                c.execute(text("UPDATE m_low_record SET lowprice_method=''"))


def test_direct_purchase_old_draft_and_migration_wrong_database():
    r=row();r['quote']['lowprice_method']='';normalize_draft(r)
    assert r['quote']['lowprice_method']=='直接购买'
    spec=importlib.util.spec_from_file_location('explicit_method',Path('migrations/versions/0014_explicit_purchase_method.py'))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    op=MagicMock();op.get_bind.return_value.scalar.return_value='production';migration.op=op
    with pytest.raises(RuntimeError,match='modou_test'):migration.upgrade()
    op.execute.assert_not_called()


def test_compact_proposals_dom_offline():
    source=Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    fn=source.split('(() => {',1)[0]+source[source.index('function renderProposals('):source.index('function wireReparse(')]
    harness="""
const assert=require('node:assert/strict');
function el(tag,text){return {tag,textContent:text,children:[],dataset:{},classList:{toggle(){}},append(...v){this.children.push(...v)},querySelector(){return null;}};}
const trace=el('div'),d=el('div'),entry={dataset:{editing:'false'},querySelector:s=>s==='.trace'?trace:s==='.web-d'?d:null};
const entries=[entry],batch={rows:[{final:{},manual_fields:[],proposed_inserts:[{table:'game_product_config',values:{name_en:null,type:null,note:null,bangumi_main:null}},{table:'game_alias',values:{alias:'alias',gpc_id:8}},{table:'m_low_record',values:{lowprice_method:'直接购买'}}]}]};
function quickSave(){};
"""
    checks="""
renderProposals(0);const panel=d.children[0];assert.equal(panel.children[0].textContent,'拟增：');assert.equal(panel.dataset.stored,'false');
assert.deepEqual(panel.children.slice(1).map(x=>x.dataset.table),['game_alias','game_product_config','m_low_record']);
const table=panel.children[1].children[0].children[0];assert.deepEqual(table.children[0].children.map(x=>x.textContent),['alias']);
const gp=panel.children[2].children[0].children[0];assert.equal(gp.children[1].children[0].children[0].textContent,'？');
assert.equal(gp.children[1].children[1].textContent,'？');assert.equal(gp.children[1].children[2].children[0].textContent,'');
batch.rows[0].proposed_inserts.forEach(p=>{p.stored=true;p.operation=p.table==='game_product_config'?'复用':'新增'});d.children=[];renderProposals(0);assert.equal(d.children[0].dataset.stored,'true');assert.deepEqual(d.children[0].children.slice(1).map(s=>s.children[0].textContent),['别名表（game_alias）新增','GPC表（Game Product Configuration）复用','报价表（m_low_record）新增']);batch.rows[0].proposed_inserts.forEach(p=>p.stored=false);
entry.dataset.editing='true';d.children=[];renderProposals(0);
const input=d.children[0].children[2].children[0].children[0].children[1].children[0].children[0];assert.equal(input.tag,'input');assert.equal(input.value,'');
"""
    harness=harness.replace('dataset:{},classList','setAttribute(){},dataset:{},classList')
    subprocess.run(['node','-e',harness+fn+checks],check=True,capture_output=True,text=True)


@pytest.mark.skipif(__import__('os').environ.get('MODOU_METHOD_TEST')!='1',reason='PostgreSQL专项需显式启用')
def test_postgres_method_migration_uses_real_constraint_without_touching_business_data():
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    from modou.web.service import engine_for, read_config
    e=engine_for(read_config())
    with e.connect() as c:
        tx=c.begin()
        try:
            assert c.scalar(text('select current_database()'))=='modou_test'
            c.execute(text('CREATE TEMP TABLE m_low_record(record_id bigint PRIMARY KEY,lowprice_method text NOT NULL) ON COMMIT DROP'))
            c.execute(text("INSERT INTO m_low_record VALUES (91,''),(92,'直接购买'),(93,'积-50')"))
            spec=importlib.util.spec_from_file_location('method_pg',Path('migrations/versions/0014_explicit_purchase_method.py'))
            m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            m.op=Operations(MigrationContext.configure(c));m.upgrade()
            assert c.execute(text('SELECT * FROM m_low_record ORDER BY record_id')).all()==[(91,'直接购买'),(92,'直接购买'),(93,'积-50')]
            for invalid in ['', '  ']:
                with pytest.raises(IntegrityError):
                    with c.begin_nested():c.execute(text('UPDATE m_low_record SET lowprice_method=:v WHERE record_id=91'),{'v':invalid})
        finally:tx.rollback()
    e.dispose()
