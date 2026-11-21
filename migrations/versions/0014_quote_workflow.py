"""Quote review and immutable rolling approval history."""
from alembic import op
import sqlalchemy as sa
revision = '0014_quote_workflow'
down_revision = '0013_price_status'
branch_labels = None
depends_on = None
FIELDS = {'quoted_at': sa.DateTime, 'approved_at': sa.DateTime, 'approved_by': sa.String,
          'lpo_reference': sa.String, 'lpo_issued_at': sa.DateTime,
          'technical_reviewed_at': sa.DateTime, 'technical_reviewed_by': sa.String}

def upgrade():
    for name, typ in FIELDS.items():
        op.add_column('rfq_requests', sa.Column(name, typ(), nullable=True))
    op.create_table('rfq_approval_events', sa.Column('id', sa.Integer, primary_key=True),
                    sa.Column('rfq_id', sa.Integer, sa.ForeignKey('rfq_requests.id'), nullable=False),
                    sa.Column('approved_at', sa.DateTime, nullable=False),
                    sa.Column('approved_by', sa.String, nullable=False))
    op.create_index('ix_rfq_approval_events_approved_at', 'rfq_approval_events', ['approved_at'])

def downgrade():
    op.drop_table('rfq_approval_events')
    for name in reversed(FIELDS):
        op.drop_column('rfq_requests', name)
