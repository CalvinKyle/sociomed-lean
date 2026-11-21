"""Add price_status so buyers only see team-verified prices.

Existing rows default to "unverified": after this migration the bot shows
"Price on quotation" everywhere until prices are marked `verified` in the
catalogue sheet's `pricing` tab and the catalogue is synced.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_price_status"
down_revision = "0012_pricing_currency"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "pricing",
        sa.Column("price_status", sa.String(), server_default="unverified", nullable=False),
    )


def downgrade():
    op.drop_column("pricing", "price_status")
