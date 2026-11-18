"""Remove the test catalog's main-subject foreign key."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT current_database()")) != "modou_test":
        raise RuntimeError("0009仅允许modou_test")
    op.execute("SET LOCAL lock_timeout = '10s'")
    for fk in sa.inspect(bind).get_foreign_keys("game_product_config", schema="public"):
        if fk["constrained_columns"] == ["bangumi_main"]:
            op.drop_constraint(fk["name"], "game_product_config", schema="public", type_="foreignkey")


def downgrade():
    raise RuntimeError("恢复主版本外键须另行授权并处理已有数据")
