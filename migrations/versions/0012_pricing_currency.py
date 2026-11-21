"""Preserve native currency on price tiers."""
from alembic import op
import sqlalchemy as sa

revision = "0012_pricing_currency"
down_revision = "0011_browse_menu"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pricing", sa.Column("currency", sa.String(), server_default="UGX", nullable=False))


def downgrade():
    op.drop_column("pricing", "currency")
