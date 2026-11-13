"""Read confirmed alias mappings. The only allowed database is modou_test."""
from sqlalchemy import URL, create_engine, select, text
from sqlalchemy.engine import make_url

from .models import GameAlias, GameName, GameVariant
from .parsing import CatalogEntry


def test_database_url(values):
    explicit = values.get("MODOU_TEST_DATABASE_URL")
    url = make_url(explicit) if explicit else URL.create(
        "postgresql+psycopg", username="modou", password=values.get("POSTGRES_PASSWORD"),
        host="192.168.1.23", port=15432, database="modou_test")
    if url.drivername != "postgresql+psycopg" or url.database != "modou_test" or url.query:
        raise ValueError("仅允许无连接覆盖参数的PostgreSQL modou_test连接")
    # Reject libpq environment/options overrides by constructing explicit arguments.
    return url


def load_aliases(connection):
    rows = connection.execute(select(
        GameAlias.alias, GameAlias.name_id, GameAlias.variant_id,
        GameName.name_zh, GameName.name_en, GameVariant.platform, GameVariant.edition,
    ).select_from(GameAlias).join(GameName, GameName.name_id == GameAlias.name_id).outerjoin(
        GameVariant, (GameVariant.variant_id == GameAlias.variant_id) &
        (GameVariant.name_id == GameAlias.name_id)).order_by(GameAlias.alias_id)).mappings()
    return [CatalogEntry(name_zh=row["name_zh"], name_en=row["name_en"],
                         aliases=[row["alias"]], name_id=row["name_id"],
                         variant_id=row["variant_id"], platform=row["platform"], edition=row["edition"])
            for row in rows]


def read_test_catalog(values):
    url = test_database_url(values)  # Validate before any network connection.
    engine = create_engine(url, connect_args={"connect_timeout": 8, "dbname": "modou_test",
                                           "options": "-c default_transaction_read_only=on"})
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            if connection.scalar(text("SELECT current_database()")) != "modou_test":
                raise ValueError("拒绝非测试库")
            return load_aliases(connection)
    finally:
        engine.dispose()
