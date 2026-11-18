import pytest
from sqlalchemy import text
from test_gpc_schema import connection
from modou.bangumi_cli import import_review


def test_guarded_review_import(connection):
    row = {'raw_name': '测试别名', 'status': 'pending',
           'final': {'platform': 'PS5', 'name_zh': '测试游戏', 'name_en': None, 'bangumi_id': '4', 'bangumi_main': None}}
    with pytest.raises(ValueError, match='未审核'):
        import_review(connection, [row])
    row['status'] = 'confirmed'
    ids = import_review(connection, [row])
    assert import_review(connection, [row]) == ids
    assert connection.scalar(text('select count(*) from game_alias')) == 1
    rejected = dict(row, status='rejected', raw_name='否决别名')
    assert import_review(connection, [rejected]) == []
    assert connection.scalar(text('select count(*) from game_alias')) == 1
    bad = dict(row, final=dict(row['final'], bangumi_id='5', gpc_id=999))
    with pytest.raises(Exception):
        with connection.begin_nested():
            import_review(connection, [bad])
    assert connection.scalar(text('select count(*) from game_product_config')) == 1


@pytest.mark.parametrize('value', ['Base', 'rebase', 'Expansion', '母子集', '合集'])
def test_review_import_type(connection, value):
    row = {'raw_name': '分类别名', 'status': 'confirmed',
           'final': {'platform': 'PS5', 'name_zh': '分类游戏', 'bangumi_id': '42', 'type': value}}
    ids = import_review(connection, [row])
    assert connection.scalar(text('select type from game_product_config where gpc_id=:id'), {'id': ids[0]}) == value
    assert import_review(connection, [row]) == ids
    mismatch = dict(row, final=dict(row['final'], type='rebase' if value != 'rebase' else 'Base'))
    with pytest.raises(ValueError, match='冲突'):
        import_review(connection, [mismatch])
    mismatch['final']['gpc_id'] = ids[0]
    with pytest.raises(ValueError, match='冲突'):
        import_review(connection, [mismatch])
    assert connection.scalar(text('select type from game_product_config where gpc_id=:id'), {'id': ids[0]}) == value


@pytest.mark.parametrize('value', ['base', 'DLC', '', 'unknown', 1, []])
def test_review_type_rejected_before_database(value):
    from modou.bangumi_cli import validate_rows
    row = {'raw_name': '分类', 'status': 'confirmed', 'final': {'platform': 'PS5', 'name_zh': '游戏', 'type': value}}
    with pytest.raises(ValueError, match='type必须'):
        validate_rows([row])


def test_gamefaqs_import_and_conflict(connection):
    link = 'https://gamefaqs.gamespot.com/ps5/324823-ghost-of-tsushima-iki-island'
    row = {'raw_name': '壹岐岛', 'status': 'confirmed', 'final': {'platform': 'PS5', 'name_zh': '壹岐岛', 'outlink': link}}
    ids = import_review(connection, [row])
    assert connection.scalar(text('select outlink from game_product_config where gpc_id=:id'), {'id': ids[0]}) == link
    row['final']['gpc_id'] = ids[0]
    assert import_review(connection, [row]) == ids
    row['final']['outlink'] = 'https://gamefaqs.gamespot.com/ps5/1-other'
    with pytest.raises(ValueError, match='身份'):
        import_review(connection, [row])
    row['status'] = 'rejected'
    assert import_review(connection, [row]) == []


def test_invalid_gamefaqs_before_database():
    from modou.bangumi_cli import validate_rows
    row = {'raw_name': '游戏', 'status': 'confirmed', 'final': {'platform': 'PS5', 'name_zh': '游戏', 'outlink': 'javascript:alert(1)'}}
    with pytest.raises(ValueError, match='外链必须'):
        validate_rows([row])


def test_gamefaqs_identity_creates_distinct_product(connection):
    row = {'raw_name': '已有游戏', 'status': 'confirmed', 'final': {'platform': 'PS5', 'name_zh': '已有游戏', 'bangumi_id': '43'}}
    ids = import_review(connection, [row])
    row['final']['outlink'] = 'https://gamefaqs.gamespot.com/ps5/1-game'
    new_ids = import_review(connection, [row])
    assert new_ids != ids
    assert connection.scalar(text('select outlink from game_product_config where gpc_id=:id'), {'id': ids[0]}) is None
    assert connection.scalar(text('select outlink from game_product_config where gpc_id=:id'), {'id': new_ids[0]}) == row['final']['outlink']
