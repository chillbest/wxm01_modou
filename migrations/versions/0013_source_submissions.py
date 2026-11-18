"""Allow the same source path in separate submissions; preserve existing rows."""
from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text('SELECT current_database()')) != 'modou_test':
        raise RuntimeError('0013仅允许modou_test')
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute('LOCK TABLE data_source IN ACCESS EXCLUSIVE MODE')
    constraints = sa.inspect(bind).get_unique_constraints('data_source')
    for constraint in constraints:
        if constraint['column_names'] == ['source_path']:
            op.drop_constraint(constraint['name'], 'data_source', type_='unique')
    op.execute("COMMENT ON COLUMN data_source.recorded_at IS '来源入库时间'")


def downgrade():
    raise RuntimeError('来源地址可能已重复，恢复唯一约束须独立确认')
