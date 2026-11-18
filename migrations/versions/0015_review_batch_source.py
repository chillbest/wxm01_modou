"""Identify review sources by durable batch, preserving legacy source records."""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().scalar(sa.text('SELECT current_database()')) != 'modou_test':
        raise RuntimeError('0015仅允许modou_test')
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute('LOCK TABLE data_source IN ACCESS EXCLUSIVE MODE')
    op.add_column('data_source', sa.Column('review_batch_id', sa.Text(), nullable=True,
                                         comment='动态审核批次标识，兼容8位及历史32位'))
    op.create_unique_constraint('uq_source_review_batch', 'data_source', ['review_batch_id'])
    op.execute("COMMENT ON COLUMN data_source.recorded_at IS '审核批次创建时间；非审核来源为创建来源时间；历史时间保留'")


def downgrade():
    raise RuntimeError('移除审核来源关联须独立确认')
