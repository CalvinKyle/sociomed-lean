"""Add backward-compatible product visibility."""
from alembic import op
import sqlalchemy as sa

revision = "0009_product_active"
down_revision = "0008_catalog_sync_versioning"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("products", sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade():
    op.drop_column("products", "active")
