"""GPC alias memory contract (replaces legacy name/variant assertions)."""
from datetime import date
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_gpc_schema import connection
from modou.catalog_memory import load_aliases, test_database_url as guarded_url
from modou.parsing import parse_note


def test_gpc_alias_does_not_supply_platform(connection):
    connection.execute(text("insert into data_source(source_path) values ('test/catalog-memory.txt')"))
    connection.execute(text("insert into game_product_config(sources_id,platform,name_zh,bangumi_id) values (1,'PS5','game','10')"))
    connection.execute(text("insert into game_alias(sources_id,gpc_id,alias) select 1,gpc_id,'alias' from game_product_config"))
    catalog = load_aliases(connection)
    item = parse_note('title\nalias｜HK100', catalog=catalog).items[0]
    assert item.gpc_id is not None
    assert item.platform == "PS5"
    assert item.name_zh == 'game'


def test_same_alias_multiple_gpc_is_ambiguous(connection):
    connection.execute(text("insert into data_source(source_path) values ('test/catalog-memory.txt')"))
    connection.execute(text("insert into game_product_config(sources_id,platform,name_zh) values (1,'PS5','same'),(1,'PS5','same')"))
    connection.execute(text("insert into game_alias(sources_id,gpc_id,alias) select 1,gpc_id,'alias' from game_product_config"))
    with Session(bind=connection) as session:
        catalog = load_aliases(session)
    item = parse_note('title\nalias｜HK100', catalog=catalog).items[0]
    assert item.match_status == 'ambiguous'
    assert item.gpc_id is None


def test_formal_database_rejected():
    with pytest.raises(ValueError):
        guarded_url({'MODOU_TEST_DATABASE_URL':'postgresql+psycopg://u:p@localhost/modou'})
