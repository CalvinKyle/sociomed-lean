"""add catalog sync version history

Revision ID: 0008_catalog_sync_versioning
Revises: 0007_catalog_taxonomy
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_catalog_sync_versioning"
down_revision = "0007_catalog_taxonomy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_versions",
        sa.Column("version_id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "started_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_sync_versions_started_at",
        "sync_versions",
        ["started_at"],
    )

    op.create_table(
        "catalog_change_log",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("sync_versions.version_id"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("change_type", sa.String(), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_catalog_change_log_version_id",
        "catalog_change_log",
        ["version_id"],
    )
    op.create_index(
        "ix_catalog_change_log_entity_id_changed_at",
        "catalog_change_log",
        ["entity_id", "changed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_change_log_entity_id_changed_at",
        table_name="catalog_change_log",
    )
    op.drop_index(
        "ix_catalog_change_log_version_id",
        table_name="catalog_change_log",
    )
    op.drop_table("catalog_change_log")
    op.drop_index("ix_sync_versions_started_at", table_name="sync_versions")
    op.drop_table("sync_versions")
