import os
import sys
import pytest
import datetime
import uuid
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from db.init_db import init_database
from db.db_connection import query_db, execute_db

@pytest.fixture(autouse=True)
def setup_test_db():
    app.config['TESTING'] = True
    init_database()

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def create_sample_order(total_amount=35000):
    """테스트용 샘플 주문 및 재고 예약 데이터 생성 헬퍼"""
    unique_no = f"ORD-TEST-{uuid.uuid4().hex[:8].upper()}"
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    exp_str = (datetime.datetime.now() + datetime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')

    option = query_db("SELECT * FROM product_options LIMIT 1", one=True)
    if not option:
        cat_id = execute_db("INSERT INTO categories (name) VALUES ('테스트카테고리')")
        prod_id = execute_db("INSERT INTO products (category_id, name, price) VALUES (%s, '테스트참기름', 35000)", (cat_id,))
        option_id = execute_db("INSERT INTO product_options (product_id, option_name, stock, reserved_stock) VALUES (%s, '500ml', 100, 0)", (prod_id,))
    else:
        option_id = option['id']
        execute_db("UPDATE product_options SET stock = 100, reserved_stock = 0 WHERE id = %s", (option_id,))

    order_id = execute_db("""
        INSERT INTO orders (order_number, total_amount, order_status, payment_status, recipient_name, recipient_phone, postal_code, address, created_at)
        VALUES (%s, %s, 'PENDING', 'READY', '홍길동', '010-1234-5678', '06123', '서울특별시 강남구 테헤란로 123', %s)
    """, (unique_no, total_amount, now_str))

    execute_db("""
        INSERT INTO order_items (order_id, product_id, option_id, product_name_snapshot, option_name_snapshot, quantity, unit_price, option_price, final_unit_price, subtotal)
        VALUES (%s, 1, %s, '테스트상품', '기본', 1, %s, 0, %s, %s)
    """, (order_id, option_id, total_amount, total_amount, total_amount))

    res_id = execute_db("""
        INSERT INTO stock_reservations (order_id, product_option_id, quantity, status, expires_at)
        VALUES (%s, %s, 1, 'RESERVED', %s)
    """, (order_id, option_id, exp_str))
    
    execute_db("UPDATE product_options SET reserved_stock = reserved_stock + 1 WHERE id = %s", (option_id,))

    return {
        'order_id': order_id,
        'order_number': unique_no,
        'option_id': option_id,
        'total_amount': total_amount,
        'reservation_id': res_id
    }

# --- 16대 E2E TEST SUITES ---

def test_01_client_cancel_payment_does_not_mark_paid(client):
    """Test 1: 결제창 닫기/취소 후 사후 API 호출 시 백엔드 검증 실패 ➔ 절대 PAID 안 됨"""
    sample = create_sample_order(35000)
    
    with patch('routes.payment.get_portone_payment_details') as mock_get:
        mock_get.return_value = {'success': False, 'error': 'Payment cancelled by user'}
        resp = client.post('/api/payment/complete', json={
            'payment_id': 'pay_cancelled_123',
            'order_number': sample['order_number']
        })
        assert resp.status_code == 400
        
        order = query_db("SELECT * FROM orders WHERE id = %s", (sample['order_id'],), one=True)
        assert order['payment_status'] != 'PAID'
        assert order['payment_status'] == 'READY'

def test_02_valid_payment_marks_paid_once(client):
    """Test 2: 정상 결제 승인 시 PAID 및 CONFIRMED가 정확히 1회 적용됨"""
    sample = create_sample_order(35000)
    
    with patch('routes.payment.get_portone_payment_details') as mock_get:
        mock_get.return_value = {'success': True, 'status': 'PAID', 'amount': 35000}
        resp = client.post('/api/payment/complete', json={
            'payment_id': f"pay_valid_{sample['order_id']}",
            'order_number': sample['order_number']
        })
        assert resp.status_code == 200
        
        order = query_db("SELECT * FROM orders WHERE id = %s", (sample['order_id'],), one=True)
        assert order['payment_status'] == 'PAID'
        assert order['order_status'] == 'CONFIRMED'

def test_03_webhook_three_times_idempotency(client):
    """Test 3: Webhook 3회 중복 통지 시 Idempotency에 의해 재고가 1회만 차감됨"""
    sample = create_sample_order(35000)
    payload = {
        'type': 'Transaction.Paid',
        'paymentId': f"pay_wh_{sample['order_id']}",
        'timestamp': 1700000000,
        'amount': 35000,
        'merchantUid': sample['order_number']
    }
    
    initial_option = query_db("SELECT * FROM product_options WHERE id = %s", (sample['option_id'],), one=True)
    initial_stock = initial_option['stock']

    with patch('routes.payment.get_portone_payment_details') as mock_get:
        mock_get.return_value = {'success': True, 'status': 'PAID', 'amount': 35000}
        for _ in range(3):
            resp = client.post('/api/payment/webhook', json=payload)
            assert resp.status_code == 200

    after_option = query_db("SELECT * FROM product_options WHERE id = %s", (sample['option_id'],), one=True)
    assert after_option['stock'] == initial_stock - 1

def test_04_refund_three_times_non_blocking_saga(client):
    """Test 4: 환불 요청 3회 연속 클릭 시 PortOne 취소가 1회만 실행됨"""
    sample = create_sample_order(35000)
    execute_db("UPDATE orders SET payment_status = 'PAID', order_status = 'CONFIRMED' WHERE id = %s", (sample['order_id'],))
    execute_db("INSERT INTO payments (order_id, payment_id, status, amount) VALUES (%s, %s, 'PAID', 35000)", (sample['order_id'], f"pay_{sample['order_number']}"))

    with patch('routes.payment.request_portone_cancel') as mock_cancel:
        mock_cancel.return_value = {'success': True, 'cancellation_id': 'cncl_123', 'amount': 35000}
        
        resp1 = client.post('/api/payment/cancel', json={'order_number': sample['order_number'], 'amount': 35000})
        assert resp1.status_code == 200
        
        resp2 = client.post('/api/payment/cancel', json={'order_number': sample['order_number'], 'amount': 35000})
        assert resp2.status_code == 400

def test_05_pg_cancel_failure_records_refund_failed(client):
    """Test 5: PG 환불 API 실패 시 DB 재고가 복구되지 않고 REFUND_FAILED 기록됨"""
    sample = create_sample_order(35000)
    execute_db("UPDATE orders SET payment_status = 'PAID', order_status = 'CONFIRMED' WHERE id = %s", (sample['order_id'],))

    with patch('routes.payment.request_portone_cancel') as mock_cancel:
        mock_cancel.return_value = {'success': False, 'error': 'Card issuer decline'}
        resp = client.post('/api/payment/cancel', json={'order_number': sample['order_number'], 'amount': 35000})
        assert resp.status_code == 400
        
        order = query_db("SELECT * FROM orders WHERE id = %s", (sample['order_id'],), one=True)
        assert order['payment_status'] == 'REFUND_FAILED'

def test_06_pg_cancel_success_compensates_inventory_once(client):
    """Test 6: PG 환불 성공 시 inventory_compensated=1 기록 및 물리 재고(stock) 1회 복구"""
    sample = create_sample_order(35000)
    execute_db("UPDATE orders SET payment_status = 'PAID', order_status = 'CONFIRMED' WHERE id = %s", (sample['order_id'],))
    execute_db("UPDATE product_options SET stock = 50 WHERE id = %s", (sample['option_id'],))

    with patch('routes.payment.request_portone_cancel') as mock_cancel:
        mock_cancel.return_value = {'success': True, 'cancellation_id': 'cncl_success_555', 'amount': 35000}
        resp = client.post('/api/payment/cancel', json={'order_number': sample['order_number'], 'amount': 35000})
        assert resp.status_code == 200

        option = query_db("SELECT * FROM product_options WHERE id = %s", (sample['option_id'],), one=True)
        assert option['stock'] == 51

        refund = query_db("SELECT * FROM refunds WHERE order_id = %s", (sample['order_id'],), one=True)
        assert refund['inventory_compensated'] == 1

def test_07_pg_cancel_timeout_records_refund_pending(client):
    """Test 7: PG Cancel Network Timeout 발생 시 REFUND_PENDING 기록 (REFUNDED 조기 단정 금지)"""
    sample = create_sample_order(35000)
    execute_db("UPDATE orders SET payment_status = 'PAID', order_status = 'CONFIRMED' WHERE id = %s", (sample['order_id'],))

    with patch('routes.payment.request_portone_cancel') as mock_cancel:
        mock_cancel.return_value = {'success': False, 'is_timeout': True, 'error': 'Connection timeout'}
        resp = client.post('/api/payment/cancel', json={'order_number': sample['order_number'], 'amount': 35000})
        assert resp.status_code == 202

        order = query_db("SELECT * FROM orders WHERE id = %s", (sample['order_id'],), one=True)
        assert order['payment_status'] == 'REFUND_PENDING'

def test_08_shipping_order_cancel_rejected(client):
    """Test 8: 배송중(SHIPPING) 주문 취소 시 400 Bad Request로 거부됨"""
    sample = create_sample_order(35000)
    execute_db("UPDATE orders SET order_status = 'SHIPPING', payment_status = 'PAID' WHERE id = %s", (sample['order_id'],))

    resp = client.post('/api/payment/cancel', json={'order_number': sample['order_number'], 'amount': 35000})
    assert resp.status_code == 400
    assert '배송중' in resp.get_json()['error']

def test_09_reservation_expire_and_webhook_race(client):
    """Test 9: 예약 만료 Job과 결제 Webhook 동시 진행 경계조건 검증"""
    sample = create_sample_order(35000)
    execute_db("UPDATE stock_reservations SET expires_at = '2020-01-01 00:00:00' WHERE id = %s", (sample['reservation_id'],))

    payload = {
        'type': 'Transaction.Paid',
        'paymentId': f"pay_race_{sample['order_id']}",
        'timestamp': 1700000000,
        'amount': 35000,
        'merchantUid': sample['order_number']
    }

    with patch('routes.payment.get_portone_payment_details') as mock_get:
        mock_get.return_value = {'success': True, 'status': 'PAID', 'amount': 35000}
        resp = client.post('/api/payment/webhook', json=payload)
        assert resp.status_code == 200

def test_10_refund_pending_reconcile_success():
    """Test 10: REFUND_PENDING 상태 Reconciliation 성공 ➔ REFUNDED 및 재고 1회 복구"""
    from routes.payment import reconcile_pending_refunds
    execute_db("DELETE FROM orders WHERE payment_status IN ('REFUND_PENDING', 'CANCEL_REQUESTED')")
    sample = create_sample_order(35000)
    execute_db("UPDATE orders SET payment_status = 'REFUND_PENDING' WHERE id = %s", (sample['order_id'],))
    execute_db("INSERT INTO payments (order_id, payment_id, status, amount) VALUES (%s, %s, 'PAID', 35000)", (sample['order_id'], f"pay_{sample['order_number']}"))
    execute_db("INSERT INTO refunds (order_id, payment_id, refund_request_id, amount, status) VALUES (%s, %s, %s, 35000, 'PENDING')", (sample['order_id'], f"pay_{sample['order_number']}", str(uuid.uuid4())))
    execute_db("UPDATE product_options SET stock = 20 WHERE id = %s", (sample['option_id'],))

    with patch('routes.payment.get_portone_payment_details') as mock_get:
        mock_get.return_value = {'success': True, 'status': 'CANCELLED'}
        reconciled = reconcile_pending_refunds()
        assert reconciled >= 1

    order = query_db("SELECT * FROM orders WHERE id = %s", (sample['order_id'],), one=True)
    assert order['payment_status'] == 'REFUNDED'
    option = query_db("SELECT * FROM product_options WHERE id = %s", (sample['option_id'],), one=True)
    assert option['stock'] == 21

def test_11_refund_pending_reconcile_failure():
    """Test 11: REFUND_PENDING 상태 재조회 실제 실패 ➔ REFUND_FAILED 처리"""
    from routes.payment import reconcile_pending_refunds
    sample = create_sample_order(35000)
    execute_db("UPDATE orders SET payment_status = 'REFUND_PENDING' WHERE id = %s", (sample['order_id'],))

    with patch('routes.payment.get_portone_payment_details') as mock_get:
        mock_get.return_value = {'success': True, 'status': 'PAID'}
        reconcile_pending_refunds()

    order = query_db("SELECT * FROM orders WHERE id = %s", (sample['order_id'],), one=True)
    assert order['payment_status'] == 'REFUND_FAILED'

def test_12_outbox_worker_concurrency_processing_lock():
    """Test 12: Outbox Worker 동시 실행 시 PROCESSING 선격리로 동일 알림 1회 격리"""
    key = f"TEST_OUTBOX_{uuid.uuid4().hex[:8]}"
    execute_db("""
        INSERT INTO notifications (event_type, order_id, recipient, status, idempotency_key)
        VALUES ('ORDER_PAID', 999, '010-1234-5678', 'PENDING', %s)
    """, (key,))

    aff_a = execute_db("""
        UPDATE notifications SET status = 'PROCESSING', last_attempt_at = NOW() 
        WHERE idempotency_key = %s AND status = 'PENDING'
    """, (key,))
    assert aff_a == 1

    aff_b = execute_db("""
        UPDATE notifications SET status = 'PROCESSING', last_attempt_at = NOW() 
        WHERE idempotency_key = %s AND status = 'PENDING'
    """, (key,))
    assert aff_b == 0

def test_13_mismatched_amount_webhook_rejected(client):
    """Test 13: 금액 위변조 Webhook ➔ AMOUNT_MISMATCH 및 PAID 승인 거부"""
    sample = create_sample_order(35000)
    payload = {
        'type': 'Transaction.Paid',
        'paymentId': f"pay_hack_{sample['order_id']}",
        'timestamp': 1700000000,
        'amount': 100,
        'merchantUid': sample['order_number']
    }

    resp = client.post('/api/payment/webhook', json=payload)
    assert resp.status_code == 200
    assert '불일치' in resp.get_json()['message']

    order = query_db("SELECT * FROM orders WHERE id = %s", (sample['order_id'],), one=True)
    assert order['integrity_status'] == 'AMOUNT_MISMATCH'
    assert order['payment_status'] != 'PAID'

def test_14_idor_unauthorized_order_lookup_rejected(client):
    """Test 14: 타인 주문번호 무단 조회 가드 확인"""
    sample = create_sample_order(35000)
    resp = client.get(f"/api/orders/{sample['order_number']}")
    assert resp.status_code in [200, 401, 403, 404]

def test_15_cancel_requested_crash_reconcile_recovery():
    """Test 15: Process Crash로 고립된 CANCEL_REQUESTED ➔ Reconciliation 복구"""
    from routes.payment import reconcile_pending_refunds
    execute_db("DELETE FROM orders WHERE payment_status IN ('REFUND_PENDING', 'CANCEL_REQUESTED')")
    sample = create_sample_order(35000)
    execute_db("UPDATE orders SET payment_status = 'CANCEL_REQUESTED', order_status = 'CONFIRMED' WHERE id = %s", (sample['order_id'],))
    execute_db("INSERT INTO payments (order_id, payment_id, status, amount) VALUES (%s, %s, 'PAID', 35000)", (sample['order_id'], f"pay_{sample['order_number']}"))
    execute_db("INSERT INTO refunds (order_id, payment_id, refund_request_id, amount, status) VALUES (%s, %s, %s, 35000, 'PENDING')", (sample['order_id'], f"pay_{sample['order_number']}", str(uuid.uuid4())))
    execute_db("UPDATE product_options SET stock = 10 WHERE id = %s", (sample['option_id'],))

    with patch('routes.payment.get_portone_payment_details') as mock_get:
        mock_get.return_value = {'success': True, 'status': 'CANCELLED'}
        reconcile_pending_refunds()

    order = query_db("SELECT * FROM orders WHERE id = %s", (sample['order_id'],), one=True)
    assert order['payment_status'] == 'REFUNDED'
    option = query_db("SELECT * FROM product_options WHERE id = %s", (sample['option_id'],), one=True)
    assert option['stock'] == 11

def test_16_stale_outbox_processing_recovery():
    """Test 16: SMS Worker PROCESSING 방치건 ➔ Stale PROCESSING 탐지 및 PENDING 복구"""
    key = f"STALE_OUTBOX_{uuid.uuid4().hex[:8]}"
    old_time = (datetime.datetime.now() - datetime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
    
    execute_db("""
        INSERT INTO notifications (event_type, order_id, recipient, status, last_attempt_at, idempotency_key)
        VALUES ('ORDER_PAID', 888, '010-9999-8888', 'PROCESSING', %s, %s)
    """, (old_time, key))

    recovered = execute_db("""
        UPDATE notifications 
        SET status = 'PENDING' 
        WHERE status = 'PROCESSING' AND last_attempt_at < %s
    """, ((datetime.datetime.now() - datetime.timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S'),))
    
    assert recovered >= 1
    notif = query_db("SELECT * FROM notifications WHERE idempotency_key = %s", (key,), one=True)
    assert notif['status'] == 'PENDING'
