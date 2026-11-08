"""Investigation request and result columns (agent query, diagnosis, report).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

COLUMNS = ("query", "service", "root_cause", "diagnosis", "confidence", "latency_ms", "report")


def upgrade() -> None:
    op.add_column("investigations", sa.Column("query", sa.Text(), nullable=True))
    op.add_column("investigations", sa.Column("service", sa.String(length=100), nullable=True))
    op.add_column("investigations", sa.Column("root_cause", sa.String(length=100), nullable=True))
    op.add_column("investigations", sa.Column("diagnosis", sa.Text(), nullable=True))
    op.add_column("investigations", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("investigations", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column(
        "investigations",
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("investigations", column)
