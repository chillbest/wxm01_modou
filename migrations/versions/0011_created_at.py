"""Add insertion timestamps to products, aliases and prices (test only)."""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT current_database()")) != "modou_test":
        raise RuntimeError("0011仅允许modou_test")
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("LOCK TABLE game_product_config, game_alias, m_low_record IN ACCESS EXCLUSIVE MODE")
    tables = ("game_product_config", "game_alias", "m_low_record")
    for table in tables:
        if bind.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("0011要求目标三表为空；不能用迁移时间冒充历史入库时间")
    for table in tables:
        op.add_column(table, sa.Column("created_at", sa.DateTime(timezone=True),
                                      nullable=False, server_default=sa.func.now()))


def downgrade():
    raise RuntimeError("删除入库时间字段须另行授权")
