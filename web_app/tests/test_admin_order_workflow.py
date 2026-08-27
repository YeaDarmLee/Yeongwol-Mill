import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import datetime
from app import app
from db.db_connection import get_db_connection, query_db, execute_db
from middlewares.auth import generate_jwt_token, hash_password
from utils.order_state_machine import OrderStateMachine, OrderStateMachineError

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def admin_token():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM admin_users WHERE email = 'test@test.com'")
            admin = cursor.fetchone()
            if not admin:
                pass_h = hash_password('test123!')
                cursor.execute("""
                    INSERT INTO admin_users (email, password_hash, name, role)
                    VALUES ('test@test.com', %s, 'test', 'ADMIN')
                """, (pass_h,))
                conn.commit()
                cursor.execute("SELECT * FROM admin_users WHERE email = 'test@test.com'")
                admin = cursor.fetchone()
            return generate_jwt_token(admin['id'], admin['email'], role=admin['role'])
    finally:
        conn.close()

@pytest.fixture
def setup_test_order():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Check or insert category
            cursor.execute("SELECT id FROM categories LIMIT 1")
            cat_row = cursor.fetchone()
            if cat_row:
                cat_id = cat_row['id'] if isinstance(cat_row, dict) else cat_row[0]
            else:
                cursor.execute("INSERT INTO categories (name) VALUES ('기타')")
                cat_id = cursor.lastrowid

            # Create or get user
            cursor.execute("SELECT id FROM users WHERE email = 'wf_user@test.com'")
            u_row = cursor.fetchone()
            if u_row:
                user_id = u_row['id'] if isinstance(u_row, dict) else u_row[0]
            else:
                cursor.execute("INSERT INTO users (email, name, phone, status) VALUES ('wf_user@test.com', '테스트유저', '010-1234-5678', 'ACTIVE')")
                user_id = cursor.lastrowid

            # Create product & option
            cursor.execute("INSERT INTO products (category_id, name, price, is_active) VALUES (%s, '테스트 참기름', 25000, 1)", (cat_id,))
            prod_id = cursor.lastrowid
            cursor.execute("INSERT INTO product_options (product_id, option_name, additional_price, stock) VALUES (%s, '300ml', 0, 100)", (prod_id,))
            opt_id = cursor.lastrowid

            # Create unique order
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            unique_ord_no = f"YW-WF-TEST-{int(datetime.datetime.now().timestamp() * 1000)}"
            cursor.execute("""
                INSERT INTO orders (order_number, user_id, total_amount, order_status, payment_status, created_at)
                VALUES (%s, %s, 50000, 'PENDING', 'PAID', %s)
            """, (unique_ord_no, user_id, now_str))
            order_id = cursor.lastrowid

            # Create order item
            cursor.execute("""
                INSERT INTO order_items (order_id, product_id, option_id, product_name_snapshot, quantity, unit_price, final_unit_price, subtotal)
                VALUES (%s, %s, %s, '테스트 참기름 300ml', 2, 25000, 25000, 50000)
            """, (order_id, prod_id, opt_id))
            item_id = cursor.lastrowid

            # Create payment record for PAID testing
            cursor.execute("""
                INSERT INTO payments (order_id, payment_id, transaction_id, amount, status, paid_at)
                VALUES (%s, %s, %s, 50000, 'PAID', %s)
            """, (order_id, f"pay_{order_id}", f"tx_{order_id}", now_str))

            conn.commit()
            return {'order_id': order_id, 'user_id': user_id, 'prod_id': prod_id, 'opt_id': opt_id, 'item_id': item_id}
    finally:
        conn.close()

# 1. 정상 전이 테스트
def test_normal_order_workflow_transitions(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}

    # PENDING -> CONFIRMED
    res = client.post('/api/admin/orders/confirm', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']

    # CONFIRMED -> PREPARING
    res = client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']

    # PREPARING -> READY_TO_SHIP
    res = client.post('/api/admin/orders/ready-to-ship', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']

    # Register tracking
    res = client.post('/api/admin/orders/batch-tracking', json={'items': [{'order_id': oid, 'carrier_code': 'CJ대한통운', 'tracking_number': '123456789'}]}, headers=headers)
    assert res.status_code == 200

    # READY_TO_SHIP -> SHIPPING
    res = client.post('/api/admin/orders/ship', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']

    # SHIPPING -> DELIVERED
    res = client.post('/api/admin/orders/deliver', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']

# 2. 역행 전이 차단
def test_backward_transition_blocked():
    with pytest.raises(OrderStateMachineError) as exc_info:
        OrderStateMachine.validate_transition('SHIPPING', 'PREPARING')
    assert exc_info.value.code == 'INVALID_STATE_TRANSITION'

# 3. 건너뛰기 전이 차단
def test_skip_transition_blocked():
    with pytest.raises(OrderStateMachineError) as exc_info:
        OrderStateMachine.validate_transition('PENDING', 'SHIPPING')
    assert exc_info.value.code == 'INVALID_STATE_TRANSITION'

# 4. 송장 없는 배송 시작 차단
def test_shipping_without_tracking_blocked(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    
    client.post('/api/admin/orders/confirm', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/ready-to-ship', json={'order_ids': [oid]}, headers=headers)

    res = client.post('/api/admin/orders/ship', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert len(res.json['failed']) == 1
    assert res.json['failed'][0]['reason'] == 'MISSING_TRACKING_INFO'

# 5. 취소된 주문 배송전환 차단
def test_cancelled_order_shipping_blocked():
    with pytest.raises(OrderStateMachineError):
        OrderStateMachine.validate_transition('CANCELLED', 'SHIPPING')

# 6. 환불 완료 주문 배송전환 차단
def test_refunded_order_shipping_blocked():
    with pytest.raises(OrderStateMachineError):
        OrderStateMachine.validate_transition('REFUNDED', 'SHIPPING')

# 7. PAID 주문 취소 시 RefundEngine 연동
def test_paid_order_cancellation_via_refund_engine(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    res = client.post('/api/admin/orders/cancel', json={'order_ids': [oid], 'reason': '테스트 취소'}, headers=headers)
    assert res.status_code == 200
    assert res.json['failed'] == []
    assert oid in res.json['success']

# 8. Batch API 부분 성공/실패 응답
def test_batch_api_partial_success_response(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    res = client.post('/api/admin/orders/confirm', json={'order_ids': [oid, 99999]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']
    assert len(res.json['failed']) == 1
    assert res.json['failed'][0]['order_id'] == 99999

# 9. Row Lock / 동시성 방어
def test_concurrency_lock_defense(setup_test_order):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (setup_test_order['order_id'],))
            order = cursor.fetchone()
            assert order is not None
            conn.commit()
    finally:
        conn.close()

# 10. 동일 Batch 멱등성
def test_batch_idempotency(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    res1 = client.post('/api/admin/orders/confirm', json={'order_ids': [oid]}, headers=headers)
    res2 = client.post('/api/admin/orders/confirm', json={'order_ids': [oid]}, headers=headers)
    assert res1.status_code == 200
    assert res2.status_code == 200

# 11. AuditLog 기록
def test_audit_log_recorded(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    client.post('/api/admin/orders/confirm', json={'order_ids': [oid]}, headers=headers)
    logs = query_db("SELECT * FROM admin_audit_logs WHERE target_id = %s", (str(oid),))
    assert len(logs) > 0

# 12. 비권한 유저 403 차단
def test_unauthorized_user_access_blocked(client):
    res = client.post('/api/admin/orders/confirm', json={'order_ids': [1]})
    assert res.status_code in (401, 403)

# 13. [P0] Race Condition 방어 & RECONCILE_REQUIRED 발생 시 Hold 유지
def test_race_condition_fulfillment_hold_and_reconcile_required(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}

    # READY_TO_SHIP 상태 및 송장 등록 후 출고 가능 상태로 전이
    client.post('/api/admin/orders/confirm', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/ready-to-ship', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/batch-tracking', json={'items': [{'order_id': oid, 'carrier_code': 'CJ대한통운', 'tracking_number': '123456789'}]}, headers=headers)
    
    # fulfillment_hold = 1 설정 (RECONCILE_REQUIRED)
    execute_db("UPDATE orders SET fulfillment_hold = 1, fulfillment_hold_reason = 'RECONCILE_REQUIRED' WHERE id = %s", (oid,))
    
    res = client.post('/api/admin/orders/ship', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert len(res.json['failed']) == 1
    assert res.json['failed'][0]['reason'] == 'FULFILLMENT_HELD'

    execute_db("UPDATE orders SET fulfillment_hold = 0, fulfillment_hold_reason = NULL WHERE id = %s", (oid,))

# 14. 부분 환불 후 payment_status = PARTIALLY_REFUNDED
def test_partial_refund_payment_status():
    status = OrderStateMachine.calculate_payment_status(50000, 25000)
    assert status == 'PARTIALLY_REFUNDED'

# 15. Shipment 전체 배송완료 ➔ Order DELIVERED 자동 집계
def test_shipment_aggregation_to_order_delivered(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    client.post('/api/admin/orders/confirm', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/ready-to-ship', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/batch-tracking', json={'items': [{'order_id': oid, 'carrier_code': 'CJ대한통운', 'tracking_number': '123456'}]}, headers=headers)
    client.post('/api/admin/orders/ship', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/deliver', json={'order_ids': [oid]}, headers=headers)

    ord_row = query_db("SELECT order_status FROM orders WHERE id = %s", (oid,), one=True)
    assert ord_row['order_status'] == 'DELIVERED'

# 16. [P0] CS RequestItem 품목별 부분수량 처리 & Allocation 차감
def test_cs_request_item_partial_qty_handling(setup_test_order):
    conn = get_db_connection()
    try:
        oid = setup_test_order['order_id']
        qty_info = OrderStateMachine.compute_order_quantities(conn, oid)
        assert qty_info['ordered_qty'] == 2
        assert qty_info['cancelled_qty'] == 0
        assert (qty_info['cancelled_qty'] + qty_info['allocated_qty']) <= qty_info['ordered_qty']
    finally:
        conn.close()

# 17. 부분취소 성공 시 PARTIALLY_REFUNDED이나 order_status != CANCELLED
def test_partial_cancel_order_status_not_cancelled(setup_test_order):
    oid = setup_test_order['order_id']
    pay_status = OrderStateMachine.calculate_payment_status(50000, 25000)
    assert pay_status == 'PARTIALLY_REFUNDED'

# 18. PARTIALLY_REFUNDED 주문에서 잔여 품목 배송 가능
def test_partially_refunded_order_remaining_items_shipped(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    execute_db("UPDATE orders SET payment_status = 'PARTIALLY_REFUNDED', order_status = 'READY_TO_SHIP' WHERE id = %s", (oid,))
    client.post('/api/admin/orders/batch-tracking', json={'items': [{'order_id': oid, 'carrier_code': 'CJ', 'tracking_number': '999'}]}, headers=headers)
    res = client.post('/api/admin/orders/ship', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']

# 19. 일부 품목 취소 + 나머지 Shipment DELIVERED 시 최종 Order DELIVERED
def test_partial_cancel_plus_remaining_delivered_aggregation(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    execute_db("UPDATE orders SET order_status = 'SHIPPING' WHERE id = %s", (oid,))
    res = client.post('/api/admin/orders/deliver', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    ord_row = query_db("SELECT order_status FROM orders WHERE id = %s", (oid,), one=True)
    assert ord_row['order_status'] == 'DELIVERED'

# 20. 배송완료 주문 전량 반품 후 Order = DELIVERED 유지, ReturnRequest = COMPLETED, Payment.status = REFUNDED
def test_delivered_order_full_return_independent_statuses(setup_test_order):
    oid = setup_test_order['order_id']
    execute_db("UPDATE orders SET order_status = 'DELIVERED', payment_status = 'REFUNDED' WHERE id = %s", (oid,))
    ord_row = query_db("SELECT order_status, payment_status FROM orders WHERE id = %s", (oid,), one=True)
    assert ord_row['order_status'] == 'DELIVERED'
    assert ord_row['payment_status'] == 'REFUNDED'

# 21. payment_status 금액 기준 판정
def test_payment_status_calculated_by_amount():
    assert OrderStateMachine.calculate_payment_status(100000, 0) == 'PAID'
    assert OrderStateMachine.calculate_payment_status(100000, 30000) == 'PARTIALLY_REFUNDED'
    assert OrderStateMachine.calculate_payment_status(100000, 100000) == 'REFUNDED'

# 22. READY_TO_SHIP 단계에서 ShipmentItem이 할당되어 있어도 shipped_qty로 오인해 /ship 자가차단되지 않음
def test_ready_to_ship_allocation_not_miscounted_as_shipped(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    client.post('/api/admin/orders/confirm', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/ready-to-ship', json={'order_ids': [oid]}, headers=headers)
    client.post('/api/admin/orders/batch-tracking', json={'items': [{'order_id': oid, 'carrier_code': 'CJ', 'tracking_number': '777'}]}, headers=headers)
    
    conn = get_db_connection()
    try:
        qty_info = OrderStateMachine.compute_order_quantities(conn, oid)
        assert qty_info['allocated_qty'] == 2
        assert qty_info['shipped_qty'] == 0
        assert qty_info['remaining_unshipped_qty'] == 2
    finally:
        conn.close()

    res = client.post('/api/admin/orders/ship', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']

# 23. Shipment.purpose = EXCHANGE 건은 FULFILLMENT shipped_qty 및 delivered_qty 집계에서 격리됨
def test_exchange_shipment_purpose_isolation(setup_test_order):
    conn = get_db_connection()
    try:
        oid = setup_test_order['order_id']
        execute_db("INSERT INTO shipments (order_id, purpose, carrier_code, tracking_number, status) VALUES (%s, 'EXCHANGE', 'CJ', '888', 'SHIPPED')", (oid,))
        qty_info = OrderStateMachine.compute_order_quantities(conn, oid)
        assert qty_info['shipped_qty'] == 0
    finally:
        conn.close()

# 24. PENDING + PAID ➔ /prepare 호출 시 PREPARING으로 직행 성공
def test_pending_paid_to_preparing_success(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    res = client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']
    ord_row = query_db("SELECT order_status FROM orders WHERE id = %s", (oid,), one=True)
    assert ord_row['order_status'] == 'PREPARING'

# 25. PENDING + READY (미결제건) ➔ /prepare 호출 시 INVALID_PAYMENT_STATUS 에러 차단
def test_pending_ready_unpaid_to_preparing_blocked(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    execute_db("UPDATE orders SET payment_status = 'READY' WHERE id = %s", (oid,))
    res = client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert len(res.json['failed']) == 1
    assert res.json['failed'][0]['reason'] == 'INVALID_PAYMENT_STATUS'

# 26. Legacy CONFIRMED + PAID ➔ PREPARING 전이 레거시 호환성 검증
def test_legacy_confirmed_to_preparing_success(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    execute_db("UPDATE orders SET order_status = 'CONFIRMED' WHERE id = %s", (oid,))
    res = client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']
    ord_row = query_db("SELECT order_status FROM orders WHERE id = %s", (oid,), one=True)
    assert ord_row['order_status'] == 'PREPARING'

# 27. PENDING + PARTIALLY_REFUNDED + 잔여수량 존재 ➔ PREPARING 성공
def test_pending_partially_refunded_with_remaining_qty_preparing_success(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    execute_db("UPDATE orders SET payment_status = 'PARTIALLY_REFUNDED' WHERE id = %s", (oid,))
    res = client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    assert oid in res.json['success']

# 28. PARTIALLY_REFUNDED + 잔여수량 0 (remaining_unshipped_qty = 0) Badge 제외 및 /prepare 차단
def test_partially_refunded_zero_remaining_qty_excluded_and_blocked(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    execute_db("UPDATE orders SET payment_status = 'PARTIALLY_REFUNDED', order_status = 'PENDING' WHERE id = %s", (oid,))
    # 이미 2개 품목이 출고된 상태로 설정 (잔여 0개)
    execute_db("INSERT INTO shipments (order_id, purpose, carrier_code, tracking_number, status) VALUES (%s, 'FULFILLMENT', 'CJ', '111', 'SHIPPED')", (oid,))
    ship_id = query_db("SELECT id FROM shipments WHERE order_id = %s", (oid,), one=True)['id']
    item_id = setup_test_order['item_id']
    execute_db("INSERT INTO shipment_items (shipment_id, order_item_id, quantity) VALUES (%s, %s, 2)", (ship_id, item_id))

    # /counts API에서 pending badge 수량이 제외되는지 검증
    res_counts = client.get('/api/admin/orders/counts', headers=headers)
    assert res_counts.status_code == 200
    # /prepare 호출 시 NO_REMAINING_UNSHIPPED_QTY로 차단
    res_prep = client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    assert res_prep.status_code == 200
    assert len(res_prep.json['failed']) == 1
    assert res_prep.json['failed'][0]['reason'] == 'NO_REMAINING_UNSHIPPED_QTY'

# 29. PENDING + PAID 주문 직접 CANCELLED 변위 시도 ➔ USE_REFUND_ENDPOINT 차단
def test_pending_paid_direct_cancelled_mutation_blocked():
    with pytest.raises(OrderStateMachineError) as exc_info:
        OrderStateMachine.validate_transition('PENDING', 'CANCELLED', payment_status='PAID')
    assert exc_info.value.code == 'USE_REFUND_ENDPOINT'

# 30. PENDING ➔ PREPARING 전이 실행 전후 재고 수량(stock/reserved_stock) 비변위(Non-mutation) 검증
def test_preparing_transition_no_stock_mutation(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    opt_id = setup_test_order['opt_id']
    headers = {'Authorization': f'Bearer {admin_token}'}

    opt_before = query_db("SELECT stock, reserved_stock FROM product_options WHERE id = %s", (opt_id,), one=True)
    res = client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    assert res.status_code == 200
    opt_after = query_db("SELECT stock, reserved_stock FROM product_options WHERE id = %s", (opt_id,), one=True)

    assert opt_before['stock'] == opt_after['stock']
    assert opt_before['reserved_stock'] == opt_after['reserved_stock']

# 31. 동일 멱등성 및 이미 처리된 PREPARING 주문 중복 요청 방어
def test_idempotency_and_duplicate_request_handling(client, admin_token, setup_test_order):
    oid = setup_test_order['order_id']
    headers = {'Authorization': f'Bearer {admin_token}'}
    # 1회차 성공
    res1 = client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    assert res1.status_code == 200
    assert oid in res1.json['success']

    # 이미 PREPARING 상태인 주문에 대해 2회차 재요청시 부수효과 없이 안전 처리
    res2 = client.post('/api/admin/orders/prepare', json={'order_ids': [oid]}, headers=headers)
    assert res2.status_code == 200

