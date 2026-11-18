"""Global alias uniqueness, including mappings to different products."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from modou.models import Base, DataSource, GameProductConfig, GameAlias


def test_alias_unique_across_products():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(DataSource.__table__.insert(), {'sources_id': 1, 'source_path': 'test'})
        conn.execute(GameProductConfig.__table__.insert(), [
            {'gpc_id': i, 'name_zh': str(i), 'platform': 'PS5', 'sources_id': 1}
            for i in (1, 2)])
        conn.execute(GameAlias.__table__.insert(), {'alias_id': 1, 'gpc_id': 1, 'alias': 'same', 'sources_id': 1})
    for target in (1, 2):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(GameAlias.__table__.insert(), {'gpc_id': target, 'alias': 'same', 'sources_id': 1})
    engine.dispose()
