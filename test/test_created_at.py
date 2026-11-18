"""Source provenance supersedes per-row created_at (0012)."""
from contextlib import nullcontext
from unittest.mock import Mock
from pathlib import Path
import importlib.util
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_gpc_schema import connection
from test_web_app import row
from modou.web import service
from modou.web.service import commit_rows
from modou.bangumi_cli import import_review


def test_web_batch_accepts_0012(connection, monkeypatch):
    engine = Mock()
    engine.begin.return_value = nullcontext(connection)
    monkeypatch.setattr(service, 'engine_for', lambda values: engine)
    monkeypatch.setattr(service, 'read_config', lambda: {})
    selected = row(); selected['selected'] = True
    assert service.commit_batch({'rows': [selected]})
    assert selected['imported'] and not selected['selected']


def test_source_provenance_and_first_source_retained(connection):
    c = connection
    first = row()
    receipt = commit_rows(c, [first])
    first_source = c.scalar(text('SELECT sources_id FROM data_source'))
    first_time = c.scalar(text('SELECT recorded_at FROM data_source'))
    assert first_time.utcoffset() is not None
    for table in ('game_product_config','game_alias','m_low_record'):
        assert 'created_at' not in {col['name'] for col in inspect(c).get_columns(table)}
        assert c.scalar(text(f'SELECT sources_id FROM {table}')) == first_source
        with pytest.raises(IntegrityError):
            with c.begin_nested():
                c.execute(text(f'UPDATE {table} SET sources_id=9999'))
        with pytest.raises(IntegrityError):
            with c.begin_nested():
                c.execute(text(f'UPDATE {table} SET sources_id=NULL'))
    assert commit_rows(c, [row()]) == receipt
    newer = row()
    newer['quote']['source_path'] = 'second.txt'
    newer['quote']['lowprice_cny'] = '90'
    newer['raw_name'] = '新来源中的新别名'
    newer['final'].update(gpc_id=receipt[0]['gpc_id'], note='资料更新')
    commit_rows(c, [newer])
    second_source = c.scalar(text("SELECT sources_id FROM data_source WHERE source_path='second.txt'"))
    assert second_source != first_source
    assert c.scalar(text('SELECT sources_id FROM game_product_config')) == first_source
    assert c.scalar(text("SELECT sources_id FROM game_alias WHERE alias='新来源中的新别名'")) == second_source
    assert c.scalar(text('SELECT recorded_at FROM data_source WHERE sources_id=:id'), {'id':first_source}) == first_time
    with pytest.raises(IntegrityError):
        with c.begin_nested():
            c.execute(text('DELETE FROM data_source WHERE sources_id=:id'), {'id':first_source})


def test_manual_catalog_uses_shared_manual_source(connection):
    manual = {'raw_name':'手工别名','status':'confirmed','final':{'name_zh':'手工游戏','platform':'PS5'}}
    ids = import_review(connection, [manual])
    assert import_review(connection, [manual]) == ids
    source = connection.execute(text('SELECT sources_id, source_path, recorded_at FROM data_source')).one()
    assert source.source_path == '手动插入' and source.recorded_at is not None
    other = {'raw_name':'第二个别名','status':'confirmed','final':{'gpc_id':ids[0],'platform':'PS5'}}
    assert import_review(connection, [other]) == ids
    assert connection.scalar(text('SELECT count(*) FROM data_source')) == 1
    for table in ('game_product_config','game_alias'):
        assert connection.scalar(text(f'SELECT count(*) FROM {table} WHERE sources_id!=:id'), {'id':source.sources_id}) == 0


@pytest.mark.parametrize('database,counts', [('modou', []), ('modou_test', [0, 1])])
def test_migration_rejects_wrong_database_or_existing_rows(database, counts):
    spec = importlib.util.spec_from_file_location('catalog_sources_migration', Path('migrations/versions/0012_catalog_sources.py'))
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    migration.op = Mock()
    migration.op.get_bind.return_value.scalar.side_effect = [database, *counts]
    with pytest.raises(RuntimeError): migration.upgrade()
    migration.op.add_column.assert_not_called()
    migration.op.drop_column.assert_not_called()
