"""002_payment_integrity: Add integrity_status to orders table"""

revision = '002_payment_integrity'
down_revision = '001_baseline'

def upgrade():
    # ALTER TABLE orders ADD COLUMN integrity_status VARCHAR(50) DEFAULT 'NORMAL'
    pass

def downgrade():
    pass
