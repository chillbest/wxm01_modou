"""Add an optional GameFAQs URL to the test catalog."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().scalar(sa.text("SELECT current_database()")) != "modou_test":
        raise RuntimeError("0007仅允许modou_test")
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column("game_product_config", sa.Column("gamefaqs_link", sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError("删除链接字段须另行授权")
