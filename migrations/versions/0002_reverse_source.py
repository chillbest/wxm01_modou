"""来源表通过record_id引用报价；仅允许空业务表升级。"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # 锁定后检查，防止检查至DDL期间写入；遇到数据即整体回滚。
    connection.execute(sa.text("LOCK TABLE low_price_record, data_sources, game_aliases IN ACCESS EXCLUSIVE MODE"))
    for table in ("low_price_record", "data_sources", "game_aliases"):
        if connection.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("0002仅允许空业务表，停止迁移")
    inspector = sa.inspect(connection)
    foreign_key = inspector.get_foreign_keys("low_price_record")[0]["name"]
    source_unique = next(c["name"] for c in inspector.get_unique_constraints("data_sources") if c["column_names"] == ["source_url"])
    op.drop_constraint(foreign_key, "low_price_record", type_="foreignkey")
    op.drop_constraint("uq_observation", "low_price_record", type_="unique")
    op.drop_index("ix_price_source", table_name="low_price_record")
    op.drop_column("low_price_record", "source_id")
    op.drop_constraint(source_unique, "data_sources", type_="unique")
    op.add_column("data_sources", sa.Column("record_id", sa.BigInteger(), nullable=False))
    op.create_foreign_key("fk_source_record", "data_sources", "low_price_record", ["record_id"], ["id"])
    op.create_unique_constraint("uq_source_record", "data_sources", ["record_id"])


def downgrade():
    raise RuntimeError("关联方向变更不支持自动降级；需明确的数据迁移方案")
