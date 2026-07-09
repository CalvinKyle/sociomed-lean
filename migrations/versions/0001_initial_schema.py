"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("clinical_speciality", sa.String(), nullable=True),
        sa.Column("related_ids", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("product_id"),
    )
    op.create_table(
        "vendors",
        sa.Column("vendor_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("region", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("vendor_id"),
    )
    op.create_table(
        "buyer_leads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("buyer_name", sa.String(), nullable=False),
        sa.Column("organization", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("use_case", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rfq_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("buyer_name", sa.String(), nullable=False),
        sa.Column("organization", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("product_id", sa.String(), nullable=True),
        sa.Column("product_name", sa.String(), nullable=False),
        sa.Column("vendor_id", sa.String(), nullable=True),
        sa.Column("vendor_name", sa.String(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("delivery_location", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "inventory",
        sa.Column("inventory_id", sa.String(), nullable=False),
        sa.Column("sku", sa.String(), nullable=True),
        sa.Column("product_id", sa.String(), nullable=True),
        sa.Column("vendor_id", sa.String(), nullable=True),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("uom", sa.String(), nullable=True),
        sa.Column("stock_qty", sa.Integer(), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.product_id"]),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.vendor_id"]),
        sa.PrimaryKeyConstraint("inventory_id"),
    )
    op.create_table(
        "aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.product_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "pricing",
        sa.Column("pricing_id", sa.String(), nullable=False),
        sa.Column("inventory_id", sa.String(), nullable=True),
        sa.Column("min_qty", sa.Integer(), nullable=False),
        sa.Column("max_qty", sa.Integer(), nullable=True),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["inventory_id"], ["inventory.inventory_id"]),
        sa.PrimaryKeyConstraint("pricing_id"),
    )


def downgrade() -> None:
    op.drop_table("pricing")
    op.drop_table("aliases")
    op.drop_table("inventory")
    op.drop_table("rfq_requests")
    op.drop_table("buyer_leads")
    op.drop_table("vendors")
    op.drop_table("products")
