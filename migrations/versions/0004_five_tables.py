"""Normalize the empty catalog into five business tables."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE m_low_record, data_sources, game_aliases IN ACCESS EXCLUSIVE MODE"))
    for name in ("m_low_record", "data_sources", "game_aliases"):
        if connection.scalar(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{name}" LIMIT 1)')):
            raise RuntimeError("0004仅允许空业务表升级；发现数据，迁移已停止")
    # Explicitly authorized empty-table replacement; transactionally rollback on failure.
    op.drop_table("data_sources")
    op.drop_table("m_low_record")
    op.drop_table("game_aliases")
    op.create_table("game_name",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name_zh", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text()))
    op.create_index("ix_game_name_name_zh", "game_name", ["name_zh"])
    op.create_index("ix_game_name_name_en", "game_name", ["name_en"])
    op.create_table("game_variants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name_id", sa.BigInteger(), sa.ForeignKey("game_name.id"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("edition", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text()), sa.Column("remark", sa.Text()),
        sa.UniqueConstraint("name_id", "platform", "edition", name="uq_variant_spec"),
        sa.UniqueConstraint("id", "name_id", name="uq_variant_owner"),
        sa.CheckConstraint("platform IN ('PS5', 'PS4')", name="ck_platform"))
    op.create_table("data_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source_url", sa.Text(), nullable=False, unique=True),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("game_aliases",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name_id", sa.BigInteger(), sa.ForeignKey("game_name.id"), nullable=False),
        sa.Column("variant_id", sa.BigInteger(), sa.ForeignKey("game_variants.id")),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["variant_id", "name_id"], ["game_variants.id", "game_variants.name_id"], name="fk_alias_variant_owner"))
    op.create_index("ix_alias", "game_aliases", ["alias"])
    op.create_index("uq_alias_game", "game_aliases", ["name_id", "alias"], unique=True, postgresql_where=sa.text("variant_id IS NULL"))
    op.create_index("uq_alias_variant", "game_aliases", ["name_id", "variant_id", "alias"], unique=True, postgresql_where=sa.text("variant_id IS NOT NULL"))
    op.create_table("m_low_record",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("variant_id", sa.BigInteger(), sa.ForeignKey("game_variants.id"), nullable=False),
        sa.Column("sources_id", sa.BigInteger(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("lowprice_cny", sa.Numeric(10, 2), nullable=False),
        sa.Column("lowprice_method", sa.Text(), nullable=False),
        sa.Column("lowprice_date", sa.Date(), nullable=False),
        sa.CheckConstraint("lowprice_cny > 0", name="ck_positive_price"))
    op.create_index("ix_price_lookup", "m_low_record", ["variant_id", "region", "lowprice_cny", "lowprice_date"])
    op.create_index("ix_price_source", "m_low_record", ["sources_id"])


def downgrade():
    raise RuntimeError("0004不支持自动降级；不得丢弃目录或报价数据")
