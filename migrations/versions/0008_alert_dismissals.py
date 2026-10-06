"""alert dismissals

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-06 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'alert_dismissals',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('state', sa.String(length=40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'key', name='uq_alert_dismissal_user_key'),
    )
    with op.batch_alter_table('alert_dismissals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_alert_dismissals_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('alert_dismissals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_alert_dismissals_user_id'))

    op.drop_table('alert_dismissals')
