"""Add reviewed product classification to the test catalog."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().scalar(sa.text("SELECT current_database()")) != "modou_test":
        raise RuntimeError("0008仅允许modou_test")
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column("game_product_config", sa.Column("type", sa.Text(), nullable=True))
    op.create_check_constraint("ck_gpc_type", "game_product_config",
                               "type IN ('Base', 'rebase', 'Expansion', '母子集', '合集')")


def downgrade():
    raise RuntimeError("删除产品类型字段须另行授权")
