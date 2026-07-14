"""add rfq_line_items

Revision ID: 0004_rfq_line_items
Revises: 0003_commission_tracking
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_rfq_line_items"
down_revision = "0003_commission_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rfq_line_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=True),
        sa.Column("product_name", sa.String(), nullable=False),
        sa.Column("vendor_id", sa.String(), nullable=True),
        sa.Column("vendor_name", sa.String(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("uom", sa.String(), nullable=True),
        sa.Column("unit_price", sa.Integer(), nullable=True),
        sa.Column("line_total", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["rfq_id"], ["rfq_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rfq_line_items_rfq_id", "rfq_line_items", ["rfq_id"])

    op.execute(
        """
        INSERT INTO rfq_line_items
            (rfq_id, product_id, product_name, vendor_id, vendor_name,
             quantity, unit_price, line_total, created_at)
        SELECT id, product_id, product_name, vendor_id, vendor_name,
               quantity, NULL, order_value, created_at
        FROM rfq_requests
        """
    )


def downgrade() -> None:
    op.drop_index("ix_rfq_line_items_rfq_id", table_name="rfq_line_items")
    op.drop_table("rfq_line_items")
