"""fase6_events

Revision ID: 1f9c4a7b2d11
Revises: b8061541169b
Create Date: 2026-06-13 12:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "1f9c4a7b2d11"
down_revision: str | None = "b8061541169b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("materia_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["materia_id"], ["materias.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_events_user_id"), "events", ["user_id"], unique=False)
    op.create_index(op.f("ix_events_materia_id"), "events", ["materia_id"], unique=False)
    op.create_index(op.f("ix_events_date"), "events", ["date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_events_date"), table_name="events")
    op.drop_index(op.f("ix_events_materia_id"), table_name="events")
    op.drop_index(op.f("ix_events_user_id"), table_name="events")
    op.drop_table("events")
