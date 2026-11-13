"""Rename catalog tables and primary keys without replacing data."""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

RENAMES = (("game_variants", "game_variant"), ("game_aliases", "game_alias"),
           ("data_sources", "data_source"))
KEYS = (("game_name", "name_id"), ("game_variant", "variant_id"),
        ("game_alias", "alias_id"), ("data_source", "sources_id"),
        ("m_low_record", "record_id"))


def upgrade():
    op.execute("SET LOCAL lock_timeout = '10s'")
    for old, new in RENAMES:
        op.rename_table(old, new)
    for table, key in KEYS:
        op.alter_column(table, "id", new_column_name=key)


def downgrade():
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table, key in reversed(KEYS):
        op.alter_column(table, key, new_column_name="id")
    for old, new in reversed(RENAMES):
        op.rename_table(new, old)
