"""004_auth_tokens: Create refresh_tokens and revoked_access_tokens tables"""

revision = '004_auth_tokens'
down_revision = '003_refund_idempotency'

def upgrade():
    # CREATE TABLE refresh_tokens, revoked_access_tokens
    pass

def downgrade():
    pass
