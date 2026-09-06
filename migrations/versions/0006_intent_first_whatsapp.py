"""add intent-first procurement metadata and buyer profiles

Revision ID: 0006_intent_first_whatsapp
Revises: 0005_vendor_entity_type
Create Date: 2026-09-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_intent_first_whatsapp"
down_revision = "0005_vendor_entity_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("product_family_id", sa.String(), nullable=True))
    op.add_column(
        "products",
        sa.Column(
            "equipment_review_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("pricing", sa.Column("price_valid_until", sa.Date(), nullable=True))

    op.add_column(
        "rfq_requests",
        sa.Column(
            "procurement_stage",
            sa.String(),
            nullable=False,
            server_default="formal_purchase",
        ),
    )
    op.add_column(
        "rfq_requests",
        sa.Column("formal_quote", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("rfq_requests", sa.Column("required_by", sa.String(), nullable=True))
    op.add_column("rfq_requests", sa.Column("payment_preference", sa.String(), nullable=True))
    op.add_column("rfq_requests", sa.Column("destination_country", sa.String(), nullable=True))
    op.add_column(
        "rfq_requests",
        sa.Column(
            "equipment_review_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("rfq_requests", sa.Column("manual_review_reason", sa.String(), nullable=True))

    op.create_table(
        "buyer_profiles",
        sa.Column("phone", sa.String(), primary_key=True),
        sa.Column("contact_name", sa.String(), nullable=False),
        sa.Column("organization", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("delivery_location", sa.String(), nullable=True),
        sa.Column(
            "preferred_currency",
            sa.String(),
            nullable=False,
            server_default="UGX",
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("buyer_profiles")
    op.drop_column("rfq_requests", "manual_review_reason")
    op.drop_column("rfq_requests", "equipment_review_required")
    op.drop_column("rfq_requests", "destination_country")
    op.drop_column("rfq_requests", "payment_preference")
    op.drop_column("rfq_requests", "required_by")
    op.drop_column("rfq_requests", "formal_quote")
    op.drop_column("rfq_requests", "procurement_stage")
    op.drop_column("pricing", "price_valid_until")
    op.drop_column("products", "equipment_review_required")
    op.drop_column("products", "product_family_id")
