"""Store optional browse menu tree."""
from alembic import op
import sqlalchemy as sa

revision = "0011_browse_menu"
down_revision = "0010_family_curation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("browse_menu_node", sa.Column("node_id", sa.String(), primary_key=True),
        *[sa.Column(name, sa.String()) for name in ("parent_node_id", "label", "node_type", "category_id", "department", "next_action")],
        sa.Column("page", sa.Integer()), sa.Column("position", sa.Integer()))


def downgrade():
    op.drop_table("browse_menu_node")
