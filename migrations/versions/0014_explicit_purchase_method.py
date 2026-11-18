"""Store direct purchases explicitly and reject blank methods."""
from alembic import op
import sqlalchemy as sa
revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().scalar(sa.text('SELECT current_database()')) != 'modou_test':
        raise RuntimeError('0014仅允许modou_test')
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute('LOCK TABLE m_low_record IN ACCESS EXCLUSIVE MODE')
    op.execute("UPDATE m_low_record SET lowprice_method = '直接购买' WHERE lowprice_method = ''")
    op.create_check_constraint('ck_price_method_nonempty', 'm_low_record', 'length(trim(lowprice_method)) > 0')
    op.execute("COMMENT ON COLUMN m_low_record.lowprice_method IS '报价获取方式；直接购买存储为直接购买，禁止空字符串'")


def downgrade():
    raise RuntimeError('恢复空字符串语义须独立确认')
