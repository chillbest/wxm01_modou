"""Read confirmed alias mappings. The only allowed database is modou_test."""
from sqlalchemy import URL, create_engine, select, text
from sqlalchemy.engine import make_url

from .models import GameAlias, GameProductConfig
from .parsing import CatalogEntry


def test_database_url(values):
    explicit = values.get("MODOU_TEST_DATABASE_URL")
    url = make_url(explicit) if explicit else URL.create(
        "postgresql+psycopg", username="modou", password=values.get("POSTGRES_PASSWORD"),
        host="192.168.1.23", port=15432, database="modou_test")
    if url.drivername != "postgresql+psycopg" or url.database != "modou_test" or url.query:
        raise ValueError("浠呭厑璁告棤杩炴帴瑕嗙洊鍙傛暟鐨凱ostgreSQL modou_test杩炴帴")
    # Reject libpq environment/options overrides by constructing explicit arguments.
    return url


def load_aliases(connection):
    rows = connection.execute(select(GameAlias.alias, GameProductConfig.gpc_id,
                                     GameProductConfig.name_zh, GameProductConfig.name_en).join(
        GameProductConfig, GameProductConfig.gpc_id == GameAlias.gpc_id).where(GameProductConfig.gpc_id != -1)).mappings()
    return [CatalogEntry(name_zh=r['name_zh'], name_en=r['name_en'], aliases=[r['alias']],
                         gpc_id=r['gpc_id']) for r in rows]


def read_test_catalog(values):
    url = test_database_url(values)  # Validate before any network connection.
    engine = create_engine(url, connect_args={"connect_timeout": 8, "dbname": "modou_test",
                                           "options": "-c default_transaction_read_only=on"})
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            if connection.scalar(text("SELECT current_database()")) != "modou_test":
                raise ValueError("鎷掔粷闈炴祴璇曞簱")
            if connection.scalar(text("SELECT version_num FROM alembic_version")) not in ("0006", "0007", "0008", "0009", "0010", "0011", "0012", "0013", "0014", "0015", "0016", "0017"):
                raise ValueError("需要0006结构")
            return load_aliases(connection)
    finally:
        engine.dispose()
