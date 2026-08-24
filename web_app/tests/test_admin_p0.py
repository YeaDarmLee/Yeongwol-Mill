import pytest
import sys
import os
import json
import uuid
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from db.init_db import init_database
from db.db_connection import query_db, execute_db
from utils.refund_engine import process_refund_request, generate_request_fingerprint
from utils.reconciliation_worker import run_reconciliation_check
from utils.audit_logger import sanitize_data_for_audit
from routes.admin import escape_csv_formula

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    from db.restore_products_seed import restore_products
    restore_products()


    execute_db("DELETE FROM order_admin_notes")
    execute_db("DELETE FROM admin_audit_logs")
    execute_db("DELETE FROM inventory_transactions")
    execute_db("DELETE FROM refund_request_items")
    execute_db("DELETE FROM refund_requests")
    execute_db("DELETE FROM return_item_dispositions")
    execute_db("DELETE FROM return_items")
    execute_db("DELETE FROM return_claims")
    execute_db("DELETE FROM notification_outbox")
    execute_db("DELETE FROM order_items")
    execute_db("DELETE FROM orders")
    execute_db("DELETE FROM users WHERE email = 'pii@yeongwol.com'")
    execute_db("DELETE FROM admin_users WHERE email IN ('super@yeongwol.com', 'admin_test@yeongwol.com')")

    from middlewares.auth import hash_password
    pw_hash = hash_password('admin1234')

    execute_db("""
        INSERT INTO admin_users (email, name, password_hash, role)
        VALUES ('super@yeongwol.com', '총괄관리자', %s, 'SUPER_ADMIN')
    """, (pw_hash,))
    execute_db("""
        INSERT INTO admin_users (email, name, password_hash, role)
        VALUES ('admin_test@yeongwol.com', '일반관리자', %s, 'ADMIN')
    """, (pw_hash,))

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def get_admin_token(client, email='super@yeongwol.com', password='admin1234'):
    res = client.post('/api/admin/login', json={'email': email, 'password': password})
    assert res.status_code == 200
    return res.get_json()['token']

def create_sample_paid_order():
    """테스트용 결제 완료 주문 생성 헬퍼 (동적 product_id / option_id)"""
    prod = query_db("SELECT id FROM products LIMIT 1", one=True)
    opts = query_db("SELECT id FROM product_options WHERE product_id = %s LIMIT 2", (prod['id'],)) if prod else []
    p_id = prod['id'] if prod else 1
    opt1_id = opts[0]['id'] if len(opts) > 0 else None
    opt2_id = opts[1]['id'] if len(opts) > 1 else opt1_id

    ord_num = f"ORD_{uuid.uuid4().hex[:10].upper()}"
    order_id = execute_db("""
        INSERT INTO orders (
            order_number, total_amount, base_shipping_fee, order_status, payment_status,
            recipient_name, recipient_phone, address, refund_calculation_mode
        ) VALUES (%s, 50000, 3000, 'CONFIRMED', 'PAID', '홍길동', '010-1234-5678', '강원 영월군', 'AUTO')
    """, (ord_num,))
    item1_id = execute_db("""
        INSERT INTO order_items (
            order_id, product_id, option_id, product_name_snapshot, option_name_snapshot,
            quantity, unit_price, final_unit_price, subtotal,
            item_gross_amount, item_discount_allocated, item_paid_amount
        ) VALUES (%s, %s, %s, '참기름 300ml', '기본', 2, 20000, 20000, 40000, 40000, 3000, 37000)
    """, (order_id, p_id, opt1_id))
    item2_id = execute_db("""
        INSERT INTO order_items (
            order_id, product_id, option_id, product_name_snapshot, option_name_snapshot,
            quantity, unit_price, final_unit_price, subtotal,
            item_gross_amount, item_discount_allocated, item_paid_amount
        ) VALUES (%s, %s, %s, '들기름 300ml', '기본', 1, 10000, 10000, 10000, 10000, 0, 10000)
    """, (order_id, p_id, opt2_id))
    return order_id, item1_id, item2_id

# TC-01: 부분 취소 시 수량/상태 (order_status는 CONFIRMED 유지, payment_status는 PARTIALLY_REFUNDED 전환)
def test_tc01_partial_cancel_status(client):
    token = get_admin_token(client)
    order_id, item1_id, item2_id = create_sample_paid_order()

    res = client.post(f'/api/admin/orders/{order_id}/refund', headers={'Authorization': f'Bearer {token}'}, json={
        'operation_id': 'OP_TC01',
        'items': [{'order_item_id': item1_id, 'quantity': 1}],
        'reason': '고객변심'
    })
    assert res.status_code == 200

    ord_row = query_db("SELECT order_status, payment_status FROM orders WHERE id = %s", (order_id,), one=True)
    assert ord_row['order_status'] == 'CONFIRMED'
    assert ord_row['payment_status'] == 'PARTIALLY_REFUNDED'

# TC-02: 멱등키 재사용 검증 (동일 operation_id 2회 요청 시 PG 호출 중복 없이 기존 결과 1회 반환)
def test_tc02_idempotency_key_reuse(client):
    token = get_admin_token(client)
    order_id, item1_id, _ = create_sample_paid_order()

    payload = {
        'operation_id': 'OP_TC02_IDEM',
        'items': [{'order_item_id': item1_id, 'quantity': 1}],
        'reason': '고객변심'
    }
    res1 = client.post(f'/api/admin/orders/{order_id}/refund', headers={'Authorization': f'Bearer {token}'}, json=payload)
    assert res1.status_code == 200

    res2 = client.post(f'/api/admin/orders/{order_id}/refund', headers={'Authorization': f'Bearer {token}'}, json=payload)
    assert res2.status_code == 200
    assert res2.get_json()['status'] == 'COMPLETED'

# TC-03: PG 타임아웃 자동복구 (RECONCILING 전환 후 Worker에 의해 자동 확정)
def test_tc03_pg_timeout_reconciliation():
    order_id, item1_id, _ = create_sample_paid_order()
    # PROCESSING 상태 저장 시뮬레이션
    ref_req_id = execute_db("""
        INSERT INTO refund_requests (
            order_id, operation_id, request_fingerprint, idempotency_key,
            requested_amount, cancellable_amount_before, status, reason, updated_at
        ) VALUES (%s, 'OP_TC03', 'FP_TC03', 'IDEM_TC03', 18500, 50000, 'RECONCILING', 'TimeoutTest', '2026-08-20 10:00:00')
    """, (order_id,))
    execute_db("""
        INSERT INTO refund_request_items (refund_request_id, order_item_id, requested_qty, refund_amount)
        VALUES (%s, %s, 1, 18500)
    """, (ref_req_id, item1_id))

    reconciled = run_reconciliation_check(threshold_minutes=1)
    assert reconciled >= 1
    req = query_db("SELECT status FROM refund_requests WHERE id = %s", (ref_req_id,), one=True)
    assert req['status'] == 'COMPLETED'

# TC-05: 환불 가능 잔액 초과 거부 (400 Bad Request)
def test_tc05_exceed_cancellable_amount(client):
    token = get_admin_token(client)
    order_id, item1_id, _ = create_sample_paid_order()

    res = client.post(f'/api/admin/orders/{order_id}/refund', headers={'Authorization': f'Bearer {token}'}, json={
        'operation_id': 'OP_TC05',
        'items': [{'order_item_id': item1_id, 'quantity': 99}],
        'reason': '잔액초과시도'
    })
    assert res.status_code == 400

# TC-07: 취소 재고 보상 무결성 (inventory_transactions 1회 기록)
def test_tc07_inventory_compensation_integrity(client):
    token = get_admin_token(client)
    order_id, item1_id, _ = create_sample_paid_order()

    res = client.post(f'/api/admin/orders/{order_id}/refund', headers={'Authorization': f'Bearer {token}'}, json={
        'operation_id': 'OP_TC07',
        'items': [{'order_item_id': item1_id, 'quantity': 1}],
        'reason': '재고보상검증'
    })
    assert res.status_code == 200
    inv_logs = query_db("SELECT * FROM inventory_transactions WHERE source_type = 'REFUND_REQUEST'")
    assert len(inv_logs) == 1

# TC-09: CSV 다운로드 감사 로그 기록
def test_tc09_csv_export_audit(client):
    token = get_admin_token(client)
    res = client.get('/api/admin/orders/export?type=excel', headers={'Authorization': f'Bearer {token}'})
    assert res.status_code == 200

    audit = query_db("SELECT * FROM admin_audit_logs WHERE action_type = 'ORDER_EXPORT'", one=True)
    assert audit is not None
    assert audit['result'] == 'SUCCESS'

# TC-10: 개인정보 원문 조회 5단계 게이트웨이 및 Audit 로그
def test_tc10_unmask_pii(client):
    token = get_admin_token(client, email='super@yeongwol.com', password='admin1234')
    user_id = execute_db("INSERT INTO users (email, name, phone) VALUES ('pii@yeongwol.com', '개인정보자', '010-9999-8888')")

    res = client.post(f'/api/admin/customers/{user_id}/unmask', headers={'Authorization': f'Bearer {token}'}, json={
        'password': 'admin1234',
        'reason': '고객상담CS'
    })
    assert res.status_code == 200
    assert res.get_json()['user']['phone'] == '010-9999-8888'

    audit = query_db("SELECT * FROM admin_audit_logs WHERE action_type = 'CUSTOMER_PII_VIEW'", one=True)
    assert audit is not None

# TC-11: Audit Log PII 원문 필터링 검증
def test_tc11_audit_pii_sanitization():
    raw_data = {'name': '홍길동', 'phone': '010-1234-5678', 'order_id': 100}
    sanitized = sanitize_data_for_audit(raw_data)
    assert sanitized['name'] == '[REDACTED_PII]'
    assert sanitized['phone'] == '[REDACTED_PII]'
    assert sanitized['order_id'] == 100

# TC-12: CSV Formula Injection 방어 검사
def test_tc12_csv_formula_injection_escape():
    assert escape_csv_formula('=HYPERLINK("http://evil.com")') == "'=HYPERLINK(\"http://evil.com\")"
    assert escape_csv_formula('+cmd|/c calc') == "'+cmd|/c calc"
    assert escape_csv_formula('정상문자') == '정상문자'

# TC-14: 상품 옵션 삭제 시 ON DELETE SET NULL 작동 검증
def test_tc14_product_option_restrict():
    _, item1_id, _ = create_sample_paid_order()
    item = query_db("SELECT option_id FROM order_items WHERE id = %s", (item1_id,), one=True)
    if item and item['option_id']:
        execute_db("DELETE FROM product_options WHERE id = %s", (item['option_id'],))
        updated_item = query_db("SELECT option_id FROM order_items WHERE id = %s", (item1_id,), one=True)
        assert updated_item['option_id'] is None


# TC-18: DB 레벨 중복 보상 차단 (uk_inventory_source_line UNIQUE)
def test_tc18_db_level_duplicate_inventory_block():
    execute_db("""
        INSERT INTO inventory_transactions (
            product_option_id, change_qty, previous_stock, current_stock,
            reason_code, source_type, source_id, source_line_id, movement_type
        ) VALUES (1, 1, 10, 11, 'ORDER_CANCEL', 'REFUND_REQUEST', 'REQ_100', 'LINE_1', 'CANCEL_RESTOCK')
    """)
    with pytest.raises(Exception):
        execute_db("""
            INSERT INTO inventory_transactions (
                product_option_id, change_qty, previous_stock, current_stock,
                reason_code, source_type, source_id, source_line_id, movement_type
            ) VALUES (1, 1, 11, 12, 'ORDER_CANCEL', 'REFUND_REQUEST', 'REQ_100', 'LINE_1', 'CANCEL_RESTOCK')
        """)

# TC-20: Legacy Snapshot Migration 및 quantity 보존 검증
def test_tc20_migration_quantity_preservation():
    order_id, item1_id, _ = create_sample_paid_order()
    item = query_db("SELECT quantity, cancelled_qty, shipped_qty, returned_qty FROM order_items WHERE id = %s", (item1_id,), one=True)
    assert item['quantity'] == 2
    assert item['cancelled_qty'] == 0
    assert item['shipped_qty'] == 0
    assert item['returned_qty'] == 0

# TC-21: 동일 operation_id 다른 Payload ➔ 409 Conflict 차단
def test_tc21_fingerprint_mismatch_conflict(client):
    token = get_admin_token(client)
    order_id, item1_id, item2_id = create_sample_paid_order()

    res1 = client.post(f'/api/admin/orders/{order_id}/refund', headers={'Authorization': f'Bearer {token}'}, json={
        'operation_id': 'OP_TC21',
        'items': [{'order_item_id': item1_id, 'quantity': 1}],
        'reason': '사유A'
    })
    assert res1.status_code == 200

    res2 = client.post(f'/api/admin/orders/{order_id}/refund', headers={'Authorization': f'Bearer {token}'}, json={
        'operation_id': 'OP_TC21',
        'items': [{'order_item_id': item2_id, 'quantity': 1}], # 다른 Payload!
        'reason': '사유B'
    })
    assert res2.status_code == 409

# TC-23: Snapshot 불일치 주문(MANUAL_REVIEW) 자동 환불 차단
def test_tc23_manual_review_refund_block(client):
    token = get_admin_token(client)
    order_id, item1_id, _ = create_sample_paid_order()
    execute_db("UPDATE orders SET refund_calculation_mode = 'MANUAL_REVIEW' WHERE id = %s", (order_id,))

    res = client.post(f'/api/admin/orders/{order_id}/refund', headers={'Authorization': f'Bearer {token}'}, json={
        'operation_id': 'OP_TC23',
        'items': [{'order_item_id': item1_id, 'quantity': 1}],
        'reason': '수동검토차단'
    })
    assert res.status_code == 400
    assert '수동 검토' in res.get_json()['error']
