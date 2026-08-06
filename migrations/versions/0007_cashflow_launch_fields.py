"""add cashflow launch qualification and quotation snapshots

Revision ID: 0007_cashflow_launch
Revises: 0006_rfq_pfi_status
Create Date: 2026-08-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_cashflow_launch"
down_revision = "0006_rfq_pfi_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(
            sa.Column("item_type", sa.String(), nullable=False, server_default="generic")
        )

    with op.batch_alter_table("rfq_requests") as batch_op:
        batch_op.add_column(
            sa.Column("procurement_stage", sa.String(), nullable=False, server_default="market_sourcing")
        )
        batch_op.add_column(sa.Column("required_delivery_date", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("pfi_issued_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("manual_review_required", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column("manual_review_reason", sa.String(), nullable=True, server_default="legacy_unqualified_rfq")
        )
        batch_op.add_column(
            sa.Column("requires_credit", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("technical_review_required", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("special_fulfilment_required", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("payment_confirmation_reference", sa.String(), nullable=True))
        batch_op.create_check_constraint(
            "ck_rfq_requests_procurement_stage",
            "procurement_stage IN ('budgeting', 'approval_stage', 'ready_to_purchase', 'tender', 'market_sourcing')",
        )

    with op.batch_alter_table("rfq_line_items") as batch_op:
        batch_op.add_column(sa.Column("inventory_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("brand", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("sku", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("item_type", sa.String(), nullable=False, server_default="generic")
        )
        batch_op.add_column(
            sa.Column("is_own_inventory", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("currency", sa.String(), nullable=False, server_default="UGX"))
        batch_op.add_column(sa.Column("price_source", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("stock_verification_status", sa.String(), nullable=False, server_default="unknown")
        )
        batch_op.add_column(
            sa.Column("quoted_at", sa.DateTime(), nullable=False, server_default=sa.func.now())
        )

    op.execute(
        """
        UPDATE rfq_line_items
        SET currency = COALESCE(
            (SELECT rfq_requests.currency FROM rfq_requests WHERE rfq_requests.id = rfq_line_items.rfq_id),
            'UGX'
        ),
        price_source = CASE WHEN unit_price IS NOT NULL THEN 'legacy_snapshot' ELSE NULL END
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("rfq_line_items") as batch_op:
        batch_op.drop_column("quoted_at")
        batch_op.drop_column("stock_verification_status")
        batch_op.drop_column("price_source")
        batch_op.drop_column("currency")
        batch_op.drop_column("is_own_inventory")
        batch_op.drop_column("item_type")
        batch_op.drop_column("sku")
        batch_op.drop_column("brand")
        batch_op.drop_column("inventory_id")

    with op.batch_alter_table("rfq_requests") as batch_op:
        batch_op.drop_constraint("ck_rfq_requests_procurement_stage", type_="check")
        batch_op.drop_column("payment_confirmation_reference")
        batch_op.drop_column("special_fulfilment_required")
        batch_op.drop_column("technical_review_required")
        batch_op.drop_column("requires_credit")
        batch_op.drop_column("manual_review_reason")
        batch_op.drop_column("manual_review_required")
        batch_op.drop_column("pfi_issued_at")
        batch_op.drop_column("required_delivery_date")
        batch_op.drop_column("procurement_stage")

    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("item_type")
