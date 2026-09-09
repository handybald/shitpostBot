"""baseline: schema as of the pre-issue-#2 codebase

This migration intentionally does nothing. It exists as a stable anchor
point so that databases created before Alembic was introduced can be
"stamped" at this revision without Alembic trying to (re-)create tables
that already exist. Fresh installations get the full schema straight from
`Base.metadata.create_all()` and are stamped directly at `head`.

Revision ID: 0001
Revises:
Create Date: 2026-09-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
