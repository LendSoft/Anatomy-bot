"""Расписания учебных групп и сведения о преподавателях.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "group_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_name", sa.String(128), nullable=False, unique=True),
        sa.Column("stored_path", sa.String(1024), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("vk_attachment_id", sa.String(128)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_group_schedules_group_name", "group_schedules", ["group_name"])

    op.create_table(
        "teachers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("position", sa.String(255), nullable=False),
        sa.Column("area", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_teachers_full_name", "teachers", ["full_name"])


def downgrade() -> None:
    op.drop_index("ix_teachers_full_name", table_name="teachers")
    op.drop_table("teachers")
    op.drop_index("ix_group_schedules_group_name", table_name="group_schedules")
    op.drop_table("group_schedules")