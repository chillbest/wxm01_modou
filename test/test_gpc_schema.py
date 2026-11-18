"""Explicit, opt-in PostgreSQL checks for the 0016 test-only schema."""
import os
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from modou.catalog_memory import test_database_url as guarded_url
from modou.local_config import read_config


@pytest.fixture
def connection(request):
    if os.environ.get("MODOU_GPC_SCHEMA_TEST") != "1":
        pytest.skip("仅显式启用0016专项验证")
    engine = create_engine(guarded_url(read_config()), connect_args={"dbname": "modou_test", "connect_timeout": 8})
    with engine.connect() as conn:
        transaction = conn.begin()
        assert conn.scalar(text("select current_database()")) == "modou_test"
        assert conn.scalar(text("select version_num from alembic_version")) == "0016"
        # Data exercises use an empty transactional schema, never business rows/sequences.
        # The schema contract itself inspects the actual migrated public tables.
        if request.node.name != 'test_schema_contract':
            from uuid import uuid4
            from modou.models import Base
            schema = 'outlink_test_' + uuid4().hex
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            Base.metadata.create_all(conn)
        try:
            yield conn
        finally:
            transaction.rollback()
    engine.dispose()


def rejected(conn, sql):
    with pytest.raises(IntegrityError):
        with conn.begin_nested():
            conn.execute(text(sql))


def test_schema_contract(connection):
    inspector = inspect(connection)
    expected = {
        "game_product_config": ["gpc_id", "name_zh", "name_en", "bangumi_id", "bangumi_main", "note", "display_name", "outlink", "type", "platform", "sources_id"],
        "game_alias": ["alias_id", "gpc_id", "alias", "sources_id"],
        "data_source": ["sources_id", "source_path", "published_at", "recorded_at", "review_batch_id"],
        "m_low_record": ["record_id", "gpc_id", "sources_id", "region", "lowprice_cny", "lowprice_method", "lowprice_date"],
    }
    assert set(inspector.get_table_names()) == set(expected) | {"alembic_version"}
    for table, columns in expected.items():
        actual = inspector.get_columns(table)
        assert [c["name"] for c in actual] == columns
        nullable = {"name_en", "bangumi_id", "bangumi_main", "note", "display_name", "outlink", "type"} if table == "game_product_config" else {"published_at", "review_batch_id"} if table == "data_source" else set()
        assert {c["name"] for c in actual if c["nullable"]} == nullable
        assert str(actual[0]["type"]) == "BIGINT"
        for fk in inspector.get_foreign_keys(table):
            assert fk["options"].get("ondelete", "NO ACTION") == "NO ACTION"
    assert {tuple(f["constrained_columns"]) for f in inspector.get_foreign_keys("game_product_config")} == {("sources_id",)}
    from modou.models import GameProductConfig
    assert not GameProductConfig.__table__.c.bangumi_main.foreign_keys
    indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("m_low_record")}
    assert indexes["ix_price_lookup"] == ["gpc_id", "region", "lowprice_cny", "lowprice_date"]
    assert indexes["ix_price_source"] == ["sources_id"]
    assert str(inspector.get_columns("data_source")[2]["type"]) == "DATE"
    assert str(inspector.get_columns("m_low_record")[4]["type"]) == "NUMERIC(10, 2)"


def test_constraints_and_defaults(connection):
    connection.execute(text("INSERT INTO data_source(source_path,published_at) VALUES ('data/example.txt','2026-11-13')"))
    c = connection
    assert c.scalar(text("INSERT INTO game_product_config(sources_id,platform,name_zh,bangumi_id) VALUES (1,'PS5','2077','123') RETURNING gpc_id")) == 1
    c.execute(text("INSERT INTO game_product_config(sources_id,platform,name_zh,bangumi_id,bangumi_main) VALUES (1,'PS5','2077终极版','124','123')"))
    c.execute(text("INSERT INTO game_product_config(sources_id,platform,name_zh) VALUES (1,'PS5','2077'),(1,'PS5','2077')"))
    c.execute(text("INSERT INTO game_product_config(sources_id,platform,name_zh,bangumi_main) VALUES (1,'PS5','孤立','missing')"))
    rejected(c, "INSERT INTO game_product_config DEFAULT VALUES")
    assert c.scalar(text("INSERT INTO game_alias(sources_id,gpc_id,alias) VALUES (1,1,'2077') RETURNING alias_id")) == 1
    c.execute(text("INSERT INTO game_alias(sources_id,gpc_id,alias) VALUES (1,2,'2077')"))
    rejected(c, "INSERT INTO game_alias(sources_id,gpc_id,alias) VALUES (1,1,'2077')")
    rejected(c, "INSERT INTO game_alias(sources_id,gpc_id,alias) VALUES (1,999,'unknown')")
    assert c.scalar(text("SELECT recorded_at IS NOT NULL FROM data_source WHERE sources_id=1"))
    c.execute(text("INSERT INTO data_source(source_path) VALUES ('data/example.txt')"))
    assert c.scalar(text("SELECT count(*) FROM data_source WHERE source_path='data/example.txt'")) == 2
    sql = "INSERT INTO m_low_record(gpc_id,sources_id,region,lowprice_cny,lowprice_method,lowprice_date) VALUES (1,1,'港版',199.99,'直接购买','2026-11-13')"
    assert c.scalar(text(sql + " RETURNING record_id")) == 1
    c.execute(text(sql))  # No database-level quote deduplication.
    rejected(c, sql.replace("直接购买", ""))
    rejected(c, sql.replace("199.99", "0"))
    rejected(c, sql.replace("199.99", "-1"))
    rejected(c, sql.replace("VALUES (1,", "VALUES (999,"))
    rejected(c, sql.replace("VALUES (1,1,", "VALUES (1,999,"))
    rejected(c, "DELETE FROM game_product_config WHERE gpc_id=1")
    rejected(c, "DELETE FROM game_product_config WHERE gpc_id=2")
    rejected(c, "DELETE FROM data_source WHERE sources_id=1")


def test_outlink_roundtrip(connection):
    connection.execute(text("INSERT INTO data_source(source_path,published_at) VALUES ('data/example.txt','2026-11-13')"))
    from modou.models import GameProductConfig
    from sqlalchemy import Text
    column = GameProductConfig.__table__.c.outlink
    assert column.nullable and isinstance(column.type, Text)
    assert connection.scalar(text("SELECT outlink FROM game_product_config LIMIT 1")) is None
    url = "https://gamefaqs.gamespot.com/ps5/324823-ghost-of-tsushima-iki-island"
    connection.execute(text("INSERT INTO game_product_config(sources_id,platform,gpc_id,name_zh,outlink) VALUES (1,'PS5',-1,'链接验证',:url)"), {"url": url})
    assert connection.scalar(text("SELECT outlink FROM game_product_config WHERE gpc_id=-1")) == url
    connection.execute(text("UPDATE game_product_config SET outlink=NULL WHERE gpc_id=-1"))
    assert connection.scalar(text("SELECT outlink FROM game_product_config WHERE gpc_id=-1")) is None


def test_product_type_contract(connection):
    connection.execute(text("INSERT INTO data_source(source_path,published_at) VALUES ('data/example.txt','2026-11-13')"))
    from modou.models import GameProductConfig, GPC_TYPES
    from sqlalchemy import Text
    col = GameProductConfig.__table__.c.type
    assert col.nullable and isinstance(col.type, Text)
    actual = next(c for c in inspect(connection).get_columns("game_product_config") if c["name"] == "type")
    assert actual["default"] is None
    connection.execute(text("INSERT INTO game_product_config(sources_id,platform,gpc_id,name_zh) VALUES (1,'PS5',-1,'分类验证')"))
    assert connection.scalar(text("SELECT type FROM game_product_config WHERE gpc_id=-1")) is None
    for value in GPC_TYPES:
        connection.execute(text("UPDATE game_product_config SET type=:value WHERE gpc_id=-1"), {"value": value})
        assert connection.scalar(text("SELECT type FROM game_product_config WHERE gpc_id=-1")) == value
    for value in ("base", "Rebase", "expansion", "DLC", "", "unknown"):
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(text("UPDATE game_product_config SET type=:value WHERE gpc_id=-1"), {"value": value})
    connection.execute(text("UPDATE game_product_config SET type=NULL WHERE gpc_id=-1"))
    assert connection.scalar(text("SELECT type FROM game_product_config WHERE gpc_id=-1")) is None


def test_platform_and_composite_identity(connection):
    connection.execute(text("INSERT INTO data_source(source_path,published_at) VALUES ('data/example.txt','2026-11-13')"))
    from modou.models import GameProductConfig, PriceRecord
    assert not GameProductConfig.__table__.c.platform.nullable
    assert "platform" not in PriceRecord.__table__.c
    unique = {u["name"]: u["column_names"] for u in inspect(connection).get_unique_constraints("game_product_config")}
    assert "uq_gpc_bangumi_id" not in unique
    assert unique["uq_gpc_bangumi_platform_outlink"] == ["bangumi_id", "platform", "outlink"]
    sql = "INSERT INTO game_product_config(sources_id,gpc_id,name_zh,bangumi_id,platform,outlink) VALUES (1,:id,'联合唯一','123',:platform,:link)"
    for id, platform, link in ((-1,'PS5','url1'),(-2,'PS4','url1'),(-3,'PS5','url2'),(-4,'Switch 2',None),(-5,'Switch 2',None)):
        connection.execute(text(sql), dict(id=id, platform=platform, link=link))
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(text(sql), dict(id=-6, platform='PS5', link='url1'))
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(text(sql), dict(id=-7, platform=None, link='url1'))
    connection.execute(text("INSERT INTO game_product_config(sources_id,gpc_id,name_zh,bangumi_id,platform,outlink) VALUES (1,-8,'空ID',NULL,'PS5','url1'),(1,-9,'空ID',NULL,'PS5','url1')"))
