"""add vendor commission rate and RFQ order value

Revision ID: 0003_commission_tracking
Revises: 0002_funnel_events
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_commission_tracking"
down_revision = "0002_funnel_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vendors", sa.Column("commission_rate", sa.Float(), nullable=True))
    op.add_column("rfq_requests", sa.Column("order_value", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("rfq_requests", "order_value")
    op.drop_column("vendors", "commission_rate")
