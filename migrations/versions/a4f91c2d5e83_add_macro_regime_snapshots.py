"""add macro regime snapshots

Revision ID: a4f91c2d5e83
Revises: 00f5798d2664
Create Date: 2026-04-21 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4f91c2d5e83'
down_revision: Union[str, Sequence[str], None] = '00f5798d2664'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'macro_regime_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('regime', sa.String(length=32), nullable=False),
        sa.Column('spy_score', sa.Float(), nullable=False),
        sa.Column('vix_score', sa.Float(), nullable=False),
        sa.Column('curve_score', sa.Float(), nullable=False),
        sa.Column('raw_inputs', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('macro_regime_snapshots', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_macro_regime_snapshots_ts'), ['ts'], unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_macro_regime_snapshots_regime'), ['regime'], unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('macro_regime_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_macro_regime_snapshots_regime'))
        batch_op.drop_index(batch_op.f('ix_macro_regime_snapshots_ts'))

    op.drop_table('macro_regime_snapshots')
