"""M01：三张业务表。"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("data_sources", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("source_url", sa.Text(), nullable=False, unique=True))
    op.create_table("game_aliases", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("game_name_zh", sa.Text(), nullable=False), sa.Column("alias", sa.Text(), nullable=False), sa.UniqueConstraint("game_name_zh", "alias"))
    op.create_index("ix_alias", "game_aliases", ["alias"])
    op.create_table("low_price_record",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name_zh", sa.Text(), nullable=False), sa.Column("name_en", sa.Text()),
        sa.Column("platform", sa.Text(), nullable=False), sa.Column("region", sa.Text(), nullable=False), sa.Column("edition", sa.Text(), nullable=False),
        sa.Column("lowprice_cny", sa.Numeric(10, 2), nullable=False), sa.Column("lowprice_method", sa.Text(), nullable=False), sa.Column("lowprice_date", sa.Date(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.CheckConstraint("platform IN ('PS5', 'PS4')", name="ck_platform"), sa.CheckConstraint("lowprice_cny > 0", name="ck_positive_price"),
        sa.UniqueConstraint("name_zh", "platform", "region", "edition", "lowprice_cny", "lowprice_date", "lowprice_method", "source_id", name="uq_observation"))
    op.create_index("ix_price_lookup", "low_price_record", ["name_zh", "platform", "edition", "region", "lowprice_cny", "lowprice_date"])
    op.create_index("ix_price_english", "low_price_record", ["name_en"])
    op.create_index("ix_price_source", "low_price_record", ["source_id"])


def downgrade():
    op.drop_table("low_price_record")
    op.drop_table("game_aliases")
    op.drop_table("data_sources")
