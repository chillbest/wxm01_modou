"""Rebuild the empty test database as GPC; business code remains on 0005."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

OLD_TABLES = ("m_low_record", "game_alias", "game_variant", "game_name", "data_source")


def upgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT current_database()")) != "modou_test":
        raise RuntimeError("0006仅允许modou_test；禁止升级正式库")
    op.execute("SET LOCAL lock_timeout = '10s'")
    connection.execute(sa.text("LOCK TABLE " + ", ".join(OLD_TABLES) + " IN ACCESS EXCLUSIVE MODE"))
    for name in OLD_TABLES:
        if connection.scalar(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{name}" LIMIT 1)')):
            raise RuntimeError("0006仅允许空业务表重建；发现数据，已停止")
    for name in OLD_TABLES:
        op.drop_table(name)
    op.create_table("game_product_config",
        sa.Column("gpc_id", sa.BigInteger(), primary_key=True),
        sa.Column("name_zh", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text()),
        sa.Column("bangumi_id", sa.Text()),
        sa.Column("bangumi_main", sa.Text(), sa.ForeignKey("game_product_config.bangumi_id")),
        sa.Column("note", sa.Text()),
        sa.Column("display_name", sa.Text()),
        sa.UniqueConstraint("bangumi_id", name="uq_gpc_bangumi_id"))
    op.create_index("ix_gpc_name_zh", "game_product_config", ["name_zh"])
    op.create_index("ix_gpc_name_en", "game_product_config", ["name_en"])
    op.create_table("game_alias",
        sa.Column("alias_id", sa.BigInteger(), primary_key=True),
        sa.Column("gpc_id", sa.BigInteger(), sa.ForeignKey("game_product_config.gpc_id"), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.UniqueConstraint("gpc_id", "alias", name="uq_alias_gpc"))
    op.create_index("ix_alias", "game_alias", ["alias"])
    op.create_table("data_source",
        sa.Column("sources_id", sa.BigInteger(), primary_key=True),
        sa.Column("source_path", sa.Text(), nullable=False, unique=True),
        sa.Column("published_at", sa.Date()),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("m_low_record",
        sa.Column("record_id", sa.BigInteger(), primary_key=True),
        sa.Column("gpc_id", sa.BigInteger(), sa.ForeignKey("game_product_config.gpc_id"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("sources_id", sa.BigInteger(), sa.ForeignKey("data_source.sources_id"), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("lowprice_cny", sa.Numeric(10, 2), nullable=False),
        sa.Column("lowprice_method", sa.Text(), nullable=False),
        sa.Column("lowprice_date", sa.Date(), nullable=False),
        sa.CheckConstraint("lowprice_cny > 0", name="ck_positive_price"))
    op.create_index("ix_price_lookup", "m_low_record", ["gpc_id", "platform", "region", "lowprice_cny", "lowprice_date"])
    op.create_index("ix_price_source", "m_low_record", ["sources_id"])


def downgrade():
    raise RuntimeError("0006不支持自动降级；恢复须使用备份并另行授权")
