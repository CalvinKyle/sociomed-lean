"""add RFQ PFI approval status

Revision ID: 0006_rfq_pfi_status
Revises: 0005_vendor_entity_type
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_rfq_pfi_status"
down_revision = "0005_vendor_entity_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rfq_requests") as batch_op:
        batch_op.add_column(
            sa.Column(
                "pfi_status",
                sa.String(),
                nullable=False,
                server_default="none",
            )
        )
        batch_op.create_check_constraint(
            "ck_rfq_requests_pfi_status",
            "pfi_status IN ('none', 'pending_approval', 'approved', 'held')",
        )


def downgrade() -> None:
    with op.batch_alter_table("rfq_requests") as batch_op:
        batch_op.drop_constraint("ck_rfq_requests_pfi_status", type_="check")
        batch_op.drop_column("pfi_status")
