"""Use source provenance instead of per-row timestamps (test only)."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT current_database()")) != "modou_test":
        raise RuntimeError("0012仅允许modou_test")
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("LOCK TABLE data_source, game_product_config, game_alias, m_low_record IN ACCESS EXCLUSIVE MODE")
    for table in ("game_product_config", "game_alias", "m_low_record"):
        if bind.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("0012要求目标三表为空；已有数据须单独确认来源和时间处理")
    for table in ("game_product_config", "game_alias"):
        op.add_column(table, sa.Column("sources_id", sa.BigInteger(), nullable=False))
        op.create_foreign_key(f"fk_{table}_sources_id", table, "data_source", ["sources_id"], ["sources_id"])
    for table in ("game_product_config", "game_alias", "m_low_record"):
        op.drop_column(table, "created_at")


def downgrade():
    raise RuntimeError("恢复独立时间及删除来源字段须另行授权")
