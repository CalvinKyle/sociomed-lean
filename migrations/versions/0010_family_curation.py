"""Store optional parent product curation."""
from alembic import op
import sqlalchemy as sa

revision = "0010_family_curation"
down_revision = "0009_product_active"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("product_family_curation",
        sa.Column("family_id", sa.String(), primary_key=True),
        sa.Column("page", sa.Integer()), sa.Column("position", sa.Integer()),
        sa.Column("category_id", sa.String()), sa.Column("department", sa.String()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()))


def downgrade():
    op.drop_table("product_family_curation")
