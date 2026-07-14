"""add vendor is_own_inventory flag and rfq pfi_reference

Revision ID: 0005_vendor_entity_type
Revises: 0004_rfq_line_items
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_vendor_entity_type"
down_revision = "0004_rfq_line_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendors",
        sa.Column("is_own_inventory", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("rfq_requests", sa.Column("pfi_reference", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("rfq_requests", "pfi_reference")
    op.drop_column("vendors", "is_own_inventory")
