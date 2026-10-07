"""recurring expenses and expense source

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-06 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'recurring_expenses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=10), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('day_of_month', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('generated_through', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('recurring_expenses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recurring_expenses_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_type', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('source_id', sa.String(length=36), nullable=True))
        batch_op.create_unique_constraint('uq_expense_source_date', ['source_type', 'source_id', 'spent_on'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_constraint('uq_expense_source_date', type_='unique')
        batch_op.drop_column('source_id')
        batch_op.drop_column('source_type')

    with op.batch_alter_table('recurring_expenses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recurring_expenses_user_id'))

    op.drop_table('recurring_expenses')
