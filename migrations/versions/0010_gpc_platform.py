"""Move platform to GPC and use the three-field product identity (test only)."""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT current_database()")) != "modou_test":
        raise RuntimeError("0010仅允许modou_test")
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("LOCK TABLE game_product_config, m_low_record IN ACCESS EXCLUSIVE MODE")
    for table in ("game_product_config", "m_low_record"):
        if bind.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("0010要求GPC和报价表为空；已有数据须另行设计平台拆分迁移")
    op.add_column("game_product_config", sa.Column("platform", sa.Text(), nullable=False))
    op.drop_constraint("uq_gpc_bangumi_id", "game_product_config", type_="unique")
    op.create_unique_constraint("uq_gpc_bangumi_platform_gamefaqs", "game_product_config",
                                ["bangumi_id", "platform", "gamefaqs_link"])
    op.drop_index("ix_price_lookup", table_name="m_low_record")
    op.drop_column("m_low_record", "platform")
    op.create_index("ix_price_lookup", "m_low_record",
                    ["gpc_id", "region", "lowprice_cny", "lowprice_date"])


def downgrade():
    raise RuntimeError("平台迁回报价及恢复Bangumi单列唯一约束须另行授权")
