import json
import subprocess
from pathlib import Path

import pytest
from modou.product_type import ProductTypes
from modou.models import GPC_TYPES


@pytest.mark.parametrize('status,mid,expected', [
    ('self', '4', 'Base'), ('default_self', '4', 'Base'),
    ('parent', '5', '母子集'), ('suggested', '5', '母子集'),
    ('unknown', '4', None), ('failed', '4', None), ('conflict', '5', None),
    ('self', None, None),
])
def test_main_comparison(status, mid, expected):
    result = ProductTypes().resolve({'id': 4}, {'status': status, 'main_id': mid})
    assert result['type'] == expected
    assert result['candidates'] == result['evidence'] == result['interactions'] == []


@pytest.mark.parametrize('value', [None, '', 'abc', '４', True, 0, -1, '0', 4.0])
def test_invalid_subject_ids_are_unknown(value):
    resolver = ProductTypes()
    assert resolver.resolve({'id': value}, {'status': 'self', 'main_id': '4'})['type'] is None
    assert resolver.resolve({'id': 4}, {'status': 'self', 'main_id': value})['type'] is None


@pytest.mark.parametrize('kind', GPC_TYPES)
def test_saved_reviewed_types_take_precedence(kind):
    assert ProductTypes().resolve({'gpc_id': 1, 'type': kind, 'bangumi_id': '4'},
                                  {'main_id': '5'})['type'] == kind


def test_bangumi_id_and_integer_ids_and_unreviewed_type():
    resolver = ProductTypes()
    assert resolver.resolve({'bangumi_id': '4', 'id': 9, 'type': '合集'}, {'main_id': 4})['type'] == 'Base'
    assert resolver.resolve({'id': 4, 'type': 'rebase'}, {'main_id': '5'})['type'] == '母子集'
    assert resolver.resolve({'outlink': 'https://gamefaqs.gamespot.com/ps5/1-game'},
                            {'status': 'suggested', 'main_id': '4'})['type'] is None
    assert resolver.resolve({}, {'main_id': '4'})['type'] is None
    assert resolver.resolve({'id': 4})['type'] is None


def test_type_resolution_does_not_request_external_sources(monkeypatch):
    import urllib.request
    from modou import bangumi_cli
    def fail(*args, **kwargs):
        pytest.fail('type resolution must not access network or DeepSeek')
    monkeypatch.setattr(urllib.request, 'urlopen', fail)
    monkeypatch.setattr(bangumi_cli, 'ai_client', fail)
    result = ProductTypes().resolve({'id': 4, 'summary': 'Genre: Miscellaneous > Compilation',
                                    'outlink': 'https://gamefaqs.gamespot.com/ps5/1-game'},
                                   {'status': 'default_self', 'main_id': '4'})
    assert result['type'] == 'Base'


def test_dynamic_table_unknown_type_is_question_mark():
    resolver = ProductTypes()
    values = [resolver.resolve({'id': 4}, main)['type'] for main in
              ({'main_id': '4'}, {'main_id': '5'}, {'status': 'failed'})]
    helpers = Path('src/modou/web/static/review.js').read_text(encoding='utf-8').split('(() => {', 1)[0]
    checks = """
const assert=require('node:assert/strict');
const values=VALUES;
const options=[['','？'],['Base','Base'],['母子集','母子集']];
assert.equal(fieldPresentation(3,false,options,values[0]).label,'Base');
assert.equal(fieldPresentation(3,false,options,values[1]).label,'母子集');
assert.deepEqual(fieldPresentation(3,false,options,values[2]),{dropdown:true,label:'？',unknown:true});
""".replace('VALUES', json.dumps(values, ensure_ascii=False))
    subprocess.run(['node', '-e', helpers + checks], check=True, capture_output=True, text=True)
