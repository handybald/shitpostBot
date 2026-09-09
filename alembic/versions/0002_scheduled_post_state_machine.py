"""add state-machine columns to scheduled_posts

Adds the columns needed for the reliable, restart-safe, idempotent
publishing state machine described in issue #2: last_attempt_at,
next_attempt_at and claimed_at. `retry_count` and `error_message` already
existed on this table. Purely additive - no data is dropped or rewritten.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_attempt_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("claimed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.drop_column("claimed_at")
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("last_attempt_at")
