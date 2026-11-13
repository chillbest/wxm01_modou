import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modou.models import Base, DataSource, GameAlias, GameName, GameVariant, PriceRecord
from modou.pricing import lowest_prices, search_games


@pytest.fixture(scope="session")
def pg_engine():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from sqlalchemy.engine import make_url
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    url = os.getenv("MODOU_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要专用PostgreSQL测试库")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.database == "modou_test", "仅允许modou_test"
    engine = create_engine(url, connect_args={"connect_timeout": 8})
    expected = set(Base.metadata.tables) | {"alembic_version"}
    assert set(inspect(engine).get_table_names()) <= expected, "测试库含未知表"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) == expected
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        for table in Base.metadata.sorted_tables:
            assert connection.scalar(select(func.count()).select_from(table)) == 0
    yield engine
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            assert connection.scalar(select(func.count()).select_from(table)) == 0
    engine.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def session(request):
    if request.param == "postgresql":
        engine = request.getfixturevalue("pg_engine")
    else:
        engine = create_engine("sqlite://")
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(engine)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                yield session
        finally:
            if transaction.is_active:
                transaction.rollback()
    if request.param == "sqlite":
        engine.dispose()


def variant(session, name="测试游戏", platform="PS5", edition="标准版"):
    game = session.scalar(select(GameName).where(GameName.name_zh == name))
    if game is None:
        game = GameName(name_zh=name, name_en="Example")
        session.add(game)
        session.flush()
    spec = session.scalar(select(GameVariant).where(GameVariant.name_id == game.name_id,
        GameVariant.platform == platform, GameVariant.edition == edition))
    if spec is None:
        spec = GameVariant(name_id=game.name_id, platform=platform, edition=edition)
        session.add(spec)
        session.flush()
    return spec


def add(session, identity, price, **changes):
    spec = variant(session, changes.pop("name_zh", "测试游戏"),
                   changes.pop("platform", "PS5"), changes.pop("edition", "标准版"))
    url = changes.pop("source_url", "https://www.xiaohongshu.com/explore/example")
    source = session.scalar(select(DataSource).where(DataSource.source_url == url))
    if source is None:
        source = DataSource(source_url=url)
        session.add(source)
        session.flush()
    fields = dict(record_id=identity, variant_id=spec.variant_id, sources_id=source.sources_id, region="港版",
        lowprice_cny=Decimal(str(price)), lowprice_date=date(2026, 11, 1), lowprice_method="积/v3")
    fields.update(changes)
    session.add(PriceRecord(**fields))
    session.flush()


def test_all_quotes_and_lowest(session):
    for identity, price in enumerate([180, 160, 170, 140, 155], 1):
        add(session, identity, price)
    assert session.scalar(select(func.count()).select_from(PriceRecord)) == 5
    assert lowest_prices(session, "测试游戏", "PS5", "标准版")[0][0].lowprice_cny == 140
    assert session.scalar(select(func.count()).select_from(PriceRecord)) == 5


def test_ties_groups_and_isolation(session):
    add(session, 1, 100)
    add(session, 2, 100, region="台版", lowprice_date=date(2026, 11, 2))
    add(session, 3, 100, region="台版", lowprice_date=date(2026, 11, 2), lowprice_method="凑-50")
    add(session, 4, 90, region="日版")
    add(session, 5, 80, region="欧版")
    add(session, 6, 110, region="国行")
    add(session, 7, 1, platform="PS4")
    add(session, 8, 1, edition="完全版")
    rows = lowest_prices(session, "测试游戏", "PS5", "标准版")
    assert [(r.record_id, group) for r, group, _, _ in rows] == [(6, "国行版"), (3, "港版"), (5, "海外版")]
    assert rows[2][0].region == "欧版"
    assert rows[1][0].lowprice_method == "凑-50"
    assert rows[0][2].startswith("https://")
    assert lowest_prices(session, "不存在", "PS5", "标准版") == []


def test_search(session):
    add(session, 1, 100)
    add(session, 2, 90, platform="PS4")
    session.add(GameAlias(alias_id=1, name_id=variant(session).name_id, alias="小测"))
    session.flush()
    for keyword in ["测试", "example", "小测"]:
        assert len(search_games(session, keyword)) == 2
    assert search_games(session, "%") == []
    assert search_games(session, " ") == []


@pytest.mark.parametrize("changes", [{"platform": "Xbox"}, {"lowprice_cny": 0}])
def test_constraints(session, changes):
    add(session, 1, 100)
    with pytest.raises(IntegrityError):
        add(session, 2, 100, **changes)


def test_schema():
    for model, key in [(GameName, "name_id"), (GameVariant, "variant_id"),
                       (GameAlias, "alias_id"), (DataSource, "sources_id"),
                       (PriceRecord, "record_id")]:
        assert list(model.__table__.primary_key.columns.keys()) == [key]
        assert "id" not in model.__table__.columns
    assert set(Base.metadata.tables) == {"game_name", "game_variant", "m_low_record", "game_alias", "data_source"}
    assert list(PriceRecord.__table__.columns.keys()) == ["record_id", "variant_id", "sources_id", "region", "lowprice_cny", "lowprice_method", "lowprice_date"]
    assert list(DataSource.__table__.columns.keys()) == ["sources_id", "source_url", "published_at", "recorded_at"]
    assert len(GameVariant.__table__.columns) == 6


@pytest.mark.parametrize("kind", ["source", "alias", "variant"])
def test_reference_uniqueness(session, kind):
    add(session, 1, 100)
    spec = variant(session)
    with pytest.raises(IntegrityError):
        if kind == "source":
            session.add(DataSource(source_url="https://www.xiaohongshu.com/explore/example"))
        elif kind == "alias":
            session.add_all([GameAlias(name_id=spec.name_id, alias="别名") for _ in (1, 2)])
        else:
            session.add(GameVariant(name_id=spec.name_id, platform=spec.platform, edition=spec.edition))
        session.flush()


def test_different_sources_and_dates_preserved(session):
    add(session, 1, 100)
    add(session, 2, 100, source_url="https://www.xiaohongshu.com/explore/second")
    add(session, 3, 100, lowprice_date=date(2026, 11, 2))
    assert session.scalar(select(func.count()).select_from(PriceRecord)) == 3
    assert lowest_prices(session, "测试游戏", "PS5", "标准版")[0][0].record_id == 3


def test_source_foreign_key(session):
    with pytest.raises(IntegrityError):
        session.add(PriceRecord(variant_id=999, sources_id=999, region="港版", lowprice_cny=100, lowprice_date=date(2026, 11, 1), lowprice_method="直接购买"))
        session.flush()


def test_save_observation_dedup(session):
    from modou.observations import save_observation
    fields = dict(variant_id=variant(session, name="测试").variant_id, region="港版", lowprice_cny=Decimal("100"), lowprice_date=date(2026, 11, 1), lowprice_method="积/v3")
    first = save_observation(session, source_url="https://www.xiaohongshu.com/explore/one", **fields)
    assert save_observation(session, source_url="https://www.xiaohongshu.com/explore/one", **fields).record_id == first.record_id
    assert save_observation(session, source_url="https://www.xiaohongshu.com/explore/two", **fields).record_id != first.record_id
    assert session.scalar(select(func.count()).select_from(PriceRecord)) == 2
    assert session.scalar(select(func.count()).select_from(DataSource)) == 2


def test_shared_source(session):
    add(session, 1, 100)
    add(session, 2, 90)
    assert session.scalar(select(func.count()).select_from(DataSource)) == 1
    assert session.get(PriceRecord, 1).sources_id == session.get(PriceRecord, 2).sources_id


def test_alias_variant_scope(session):
    ps5 = variant(session)
    variant(session, platform="PS4")
    session.add(GameAlias(name_id=ps5.name_id, variant_id=ps5.variant_id, alias="规格昵称"))
    session.flush()
    assert [row.platform for row in search_games(session, "规格昵称")] == ["PS5"]


def test_alias_owner_constraint(session):
    first = variant(session)
    second = variant(session, name="另一个游戏")
    with pytest.raises(IntegrityError):
        session.add(GameAlias(name_id=first.name_id, variant_id=second.variant_id, alias="错误关联"))
        session.flush()


def test_ambiguous_alias_allowed(session):
    for name in ["游戏甲", "游戏乙"]:
        spec = variant(session, name=name)
        session.add(GameAlias(name_id=spec.name_id, alias="同名别名"))
    session.flush()
    assert len(search_games(session, "同名别名")) == 2


def test_variant_alias_unique(session):
    spec = variant(session)
    with pytest.raises(IntegrityError):
        session.add_all([GameAlias(name_id=spec.name_id, variant_id=spec.variant_id, alias="规格别名") for _ in (1, 2)])
        session.flush()


def test_catalog_without_quote(session):
    spec = variant(session)
    assert search_games(session, "测试游戏") == [("测试游戏", "PS5")]
    assert lowest_prices(session, "测试游戏", "PS5", "标准版") == []
    assert spec.name_id is not None
