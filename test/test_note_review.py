import copy
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from test_gpc_schema import connection
from modou.models import Base
from modou.note_review import build_review, import_quotes
from modou.bangumi_cli import read_review, write_review
from modou.parsing import read_note


class Local:
    path = Path('dump-2026-11-10.zip')
    def lookup_many(self, queries):
        return {q.casefold(): [{'id': 4, 'name_cn': '合金弹头7', 'infobox': [{'key': '平台', 'value': 'PS4'}]}] for q in queries}


class API:
    def search(self, query):
        raise AssertionError('本地唯一命中不应调用API')


@pytest.fixture(autouse=True)
def isolated_main_resolution(monkeypatch):
    # These tests isolate note extraction; main lookup has its own integration tests.
    class Main:
        def __init__(self, dump, api): pass
        def resolve(self, selected):
            sid = selected.get('id') or selected.get('bangumi_id')
            return {'status': 'self' if sid else 'unknown', 'main_id': str(sid) if sid else None}
    monkeypatch.setattr('modou.main_subject.MainSubjects', Main)


def rows():
    return build_review('PS好价光盘\n————实时新增————\n合金弹头7 PS4｜HK100｜史低90',
                        'data/example.txt', date(2026, 11, 13), [], Local(), API())


def confirmed():
    data = rows()
    data[0]['status'] = 'confirmed'
    data[0]['final'] = {'type': 'Base', 'name_zh': '合金弹头7', 'name_en': 'Metal Slug 7', 'bangumi_id': '4', 'bangumi_main': None}
    return data


def test_note_evidence_and_review_gate():
    row = rows()[0]
    assert row['source'] == 'local'
    assert row['status'] == 'pending'
    assert row['quote']['platform'] == 'PS4'
    assert row['quote']['lowprice_cny'] == '100'
    assert '史低90' in row['extracted']['notes']
    assert row['final']['bangumi_id'] is None


def test_orm_matches_0006(connection):
    assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_atomic_import_and_reuse(connection):
    data = confirmed()
    ids = import_quotes(connection, data)
    assert import_quotes(connection, data) == ids
    assert connection.scalar(text('select type from game_product_config')) == 'Base'
    record = connection.execute(text('select * from m_low_record')).mappings().one()
    assert connection.scalar(text('select platform from game_product_config')) == 'PS4'
    assert record['lowprice_cny'] == 100
    assert connection.scalar(text('select count(*) from game_alias')) == 1
    assert connection.scalar(text('select published_at from data_source')) == date(2026, 11, 13)


def test_reject_pending_and_invalid_quote_before_write(connection):
    with pytest.raises(ValueError):
        import_quotes(connection, rows())
    data = confirmed()
    bad = copy.deepcopy(data[0]); bad['quote']['lowprice_cny'] = '-1'
    with pytest.raises(ValueError):
        import_quotes(connection, data + [bad])
    assert connection.scalar(text('select count(*) from game_product_config')) == 0
    data[0]['status'] = 'rejected'
    assert import_quotes(connection, data) == []


def test_db_failure_rolls_back_batch(connection):
    data = confirmed()
    bad = copy.deepcopy(data[0]); bad['final']['bangumi_id'] = '5'; bad['final']['gpc_id'] = 999
    with pytest.raises(Exception):
        with connection.begin_nested():
            import_quotes(connection, data + [bad])
    for table in ('game_product_config', 'game_alias', 'data_source', 'm_low_record'):
        assert connection.scalar(text('select count(*) from ' + table)) == 0


@pytest.mark.parametrize('filename,count', [('11.3｜Ps好价光盘.txt',49), ('11.7｜Ps好价光盘.txt',53), ('11.10｜Ps好价光盘.txt',50)])
def test_real_notes_to_pending_review(filename, count):
    class NoMatch:
        path = Path('test-only.zip')
        def lookup_many(self, queries):
            return {}
    class Offline:
        def search(self, query):
            raise RuntimeError('offline')
    path = Path('Doc') / filename
    if not path.exists():
        pytest.skip('历史Doc笔记样本当前不存在')
    note = read_note(path)
    result = build_review(note, 'Doc/' + filename, date(2026,11,13), [], NoMatch(), Offline())
    assert len(result) == count
    assert all(r['status'] == 'pending' and r['quote']['lowprice_cny'] is not None for r in result)
    assert all(r['errors'] for r in result)


def test_ai_requests_batch_lines_without_note_noise():
    import json
    class NoLocal:
        path = Path('dump.zip')
        def lookup_many(self, queries):
            return {}
    class Candidates:
        def search(self, query):
            return [{'id': 4, 'name_cn': '游戏本体', 'summary': '版本说明', 'images': {'large': 'NO_IMAGE'},
                     'tags': ['NO_TAG'], 'rating': 'NO_RATING', 'collection': 'NO_COLLECTION',
                     'infobox': [{'key': '别名', 'value': '游戏别称'}, {'key': '平台', 'value': 'PS5'}, {'key': '售价', 'value': 'NO_PRICE'}]},
                    {'id': 5, 'name_cn': '游戏DLC', 'infobox': [{'key': '平台', 'value': 'PS4'}]}]
    calls = []
    def ai(context):
        calls.append(context)
        field = {'outlink': None} if context['task'] == 'gamefaqs' else {'candidate': None}
        return {'results': [dict(item_id=i['item_id'], **field) for i in context['items']]}
    lines = ['🔹艾尔登法环+dlc｜🇭🇰295｜积-50', '🔸其他游戏｜🇭🇰180']
    note = 'PS好价光盘\n整篇开场白不应发送\n————实时新增————\n' + '\n'.join(lines)
    result = build_review(note, 'test.txt', date(2026,11,3), [], NoLocal(), Candidates(), ai)
    assert len(result) == 2 and len(calls) == 1
    for request in calls:
        assert [i['note'] for i in request['items']] == lines
        encoded = json.dumps(request, ensure_ascii=False)
        assert '整篇开场白' not in encoded
        assert all(noise not in encoded for noise in ('NO_IMAGE', 'NO_TAG', 'NO_RATING', 'NO_COLLECTION'))
        assert '版本说明' not in encoded and 'NO_PRICE' not in encoded
        assert request['items'][0]['candidates']['BGM-API_候选1']['infobox']['平台'] == 'PS5'
    assert 'images' in result[0]['candidates'][0]  # Local audit evidence is intact.


@pytest.mark.parametrize('source,title,enabled', [
    ('data/11.3A｜Ps好价光盘.txt', '普通标题', True),
    ('https://example.com/123', '11.3｜ps好价光盘', True),
    ('https://example.com/PS光盘', '普通标题', False),
    ('data/PS游戏.txt', '普通标题', False),
    ('data/光盘.txt', '普通标题', False),
])
def test_ps_disc_title_rule(source, title, enabled):
    class NoLocal:
        path = Path('dump.zip')
        def lookup_many(self, queries):
            return {}
    class Empty:
        def search(self, query):
            return []
    aliases = [{'alias': '星空', 'gpc_id': 1}]  # No platform evidence: cannot bypass filter.
    result = build_review(title + '\n————实时新增————\n星空｜HK180', source, date(2026,11,3), aliases, NoLocal(), Empty())
    assert result[0]['ps_disc_filter'] == enabled
    assert bool(result[0]['stage_hits']) == (not enabled)


def test_single_line_reparse_preserves_context_and_limits_identification():
    class OneLocal(Local):
        def lookup_many(self, queries):
            assert len(queries) == 1
            assert '合金弹头7' in queries[0]
            return super().lookup_many(queries)
    note = 'PS好价光盘\n————实时新增————\n合金弹头7 PS4｜HK100｜史低90\n其他游戏 PS5｜HK200'
    result = build_review(note, 'data/example.txt', date(2026,11,13), [], OneLocal(), API(), only_line=3)
    assert len(result) == 1
    assert result[0]['extracted']['line_number'] == 3
    assert result[0]['ps_disc_filter']
    assert result[0]['quote']['platform'] == 'PS4'
