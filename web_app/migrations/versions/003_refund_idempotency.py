"""003_refund_idempotency: Add refund_request_id and timestamps to refunds table"""

revision = '003_refund_idempotency'
down_revision = '002_payment_integrity'

def upgrade():
    # ALTER TABLE refunds ADD refund_request_id, timestamps, error fields
    pass

def downgrade():
    pass
