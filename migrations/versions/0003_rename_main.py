"""主表统一更名为m_low_record，保留数据和外键。"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("low_price_record", "m_low_record")


def downgrade():
    op.rename_table("m_low_record", "low_price_record")
