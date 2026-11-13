import os
from alembic import context
from sqlalchemy import create_engine
from modou.models import Base

url = context.config.attributes.get("database_url") or os.environ["DATABASE_URL"]
if not url.startswith("postgresql+psycopg://"):
    raise ValueError("DATABASE_URL必须使用postgresql+psycopg://")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    context.configure(connection=context.config.attributes["connection"], target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
