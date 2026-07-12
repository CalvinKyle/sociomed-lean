"""add funnel events and RFQ status timestamps

Revision ID: 0002_funnel_events
Revises: 0001_initial_schema
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_funnel_events"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rfq_requests",
        sa.Column("status_updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "funnel_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("rfq_id", sa.Integer(), nullable=True),
        sa.Column("event_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["rfq_id"], ["rfq_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_funnel_events_event_type_created_at",
        "funnel_events",
        ["event_type", "created_at"],
    )
    op.create_index("ix_funnel_events_rfq_id", "funnel_events", ["rfq_id"])


def downgrade() -> None:
    op.drop_index("ix_funnel_events_rfq_id", table_name="funnel_events")
    op.drop_index("ix_funnel_events_event_type_created_at", table_name="funnel_events")
    op.drop_table("funnel_events")
    op.drop_column("rfq_requests", "status_updated_at")
