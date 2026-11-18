import copy

import pytest

from modou.web_review import eligibility_errors


def complete():
    return {'final': {'name_zh': '游戏', 'name_en': 'Game', 'bangumi_id': '4', 'bangumi_main': '4', 'type': 'Base'},
            'quote': {'platform': 'PS5', 'region': '港版', 'lowprice_cny': '100.00',
                      'lowprice_method': '直接购买', 'lowprice_date': '2026-11-03', 'source_path': 'example.txt'}}


def test_direct_purchase_and_optional_fields_are_eligible():
    assert eligibility_errors(complete()) == []


@pytest.mark.parametrize('field,value', [('type', None), ('bangumi_main', None), ('bangumi_main', 'https://bgm.tv/subject/4')])
def test_unknown_product_fields_block_approval(field, value):
    row = complete()
    row['final'][field] = value
    assert eligibility_errors(row)


@pytest.mark.parametrize('field,value', [('platform', '?'), ('region', '?'), ('lowprice_cny', 'NaN'),
    ('lowprice_cny', 'Infinity'), ('lowprice_cny', '0'), ('lowprice_cny', '1.001'),
    ('lowprice_method', '其他优惠'), ('lowprice_method', None), ('lowprice_date', '2026-02-30')])
def test_invalid_quote_fields_block_approval(field, value):
    row = copy.deepcopy(complete())
    row['quote'][field] = value
    assert eligibility_errors(row)


@pytest.mark.parametrize('value',[None,'','   '])
def test_missing_english_name_blocks_import(value):
    r=complete();r['final']['name_en']=value
    assert '英文名待确认' in eligibility_errors(r)


def test_single_import_button_is_highlighted_only_when_enabled():
    from pathlib import Path
    import subprocess
    s=Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    helper=s[s.index('function singleImportState('):s.index('function centeredOriginalFits(')]
    checks="""
const assert=require('node:assert/strict');
let row={final:{name_en:'Game'},eligibility_errors:[]};
assert.deepEqual(singleImportState(row,false,false,false),{disabled:false,highlight:true});
for(const value of [null,'','   ']){row.final.name_en=value;assert.deepEqual(singleImportState(row,false,false,false),{disabled:true,highlight:false});}
row.final.name_en='Game';assert.equal(singleImportState(row,true,false,false).highlight,false);
row.eligibility_errors=['main待确认'];assert.equal(singleImportState(row,false,false,false).disabled,true);
"""
    subprocess.run(['node','-e',helper+checks],check=True,capture_output=True,text=True)
