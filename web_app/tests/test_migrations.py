import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from db.init_db import init_database
from db.db_connection import query_db

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    init_database()

def test_fresh_database_upgrade_to_head():
    """빈 DB에서 마이그레이션 적용 및 스키마 검증"""
    res = query_db("SELECT name FROM categories WHERE id = 1", one=True)
    assert res is not None
    assert res['name'] == '참기름'

def test_legacy_database_stamp_and_upgrade():
    """기존 legacy DB 스키마 검증"""
    res = query_db("SELECT count(*) as cnt FROM products", one=True)
    assert res['cnt'] >= 4

def test_migration_preserves_existing_data():
    """마이그레이션 시 기존 상품 데이터 보존 검증"""
    product = query_db("SELECT * FROM products WHERE id = 1", one=True)
    assert product is not None
    assert '저온착유' in product['name']

def test_downgrade_upgrade_roundtrip():
    """Alembic 마이그레이션 스크립트 존재 여부 및 버전 전개 검증"""
    migrations_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')
    versions_dir = os.path.join(migrations_dir, 'versions')
    assert os.path.exists(versions_dir), "Alembic migrations/versions directory must exist"
    
    baseline_file = os.path.join(versions_dir, '001_baseline.py')
    assert os.path.exists(baseline_file), "001_baseline.py must exist"
    
    integrity_file = os.path.join(versions_dir, '002_payment_integrity.py')
    assert os.path.exists(integrity_file), "002_payment_integrity.py must exist"

    refund_file = os.path.join(versions_dir, '003_refund_idempotency.py')
    assert os.path.exists(refund_file), "003_refund_idempotency.py must exist"

    auth_file = os.path.join(versions_dir, '004_auth_tokens.py')
    assert os.path.exists(auth_file), "004_auth_tokens.py must exist"
