"""Require each alias to identify one product globally."""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text('SELECT current_database()')) != 'modou_test':
        raise RuntimeError('0017仅允许modou_test')
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.create_unique_constraint('uq_alias', 'game_alias', ['alias'])
    op.drop_constraint('uq_alias_gpc', 'game_alias', type_='unique')


def downgrade():
    raise RuntimeError('别名唯一约束回退须独立确认')
