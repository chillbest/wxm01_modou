"""General purpose GPC external link; preserve values and uniqueness semantics."""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().scalar(sa.text('SELECT current_database()')) != 'modou_test':
        raise RuntimeError('0016仅允许modou_test')
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.alter_column('game_product_config', 'gamefaqs_link', new_column_name='outlink',
                    existing_type=sa.Text(), existing_nullable=True,
                    comment='游戏产品外链；完整HTTP/HTTPS URL，不限定网站')
    op.execute('ALTER TABLE game_product_config RENAME CONSTRAINT uq_gpc_bangumi_platform_gamefaqs TO uq_gpc_bangumi_platform_outlink')


def downgrade():
    raise RuntimeError('外链字段回退须独立确认')
