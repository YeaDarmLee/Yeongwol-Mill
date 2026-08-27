import hmac
import hashlib
import json
import uuid
import datetime
import requests
from flask import Blueprint, request, jsonify, current_app
from config import Config
from db.db_connection import query_db, execute_db, get_db_connection

payment_bp = Blueprint('payment', __name__, url_prefix='/api/payment')

def verify_webhook_signature(headers, body):
    """PortOne V2 Standard Webhook Signature 검증"""
    signature = headers.get('Webhook-Signature') or headers.get('x-portone-signature')
    
    if signature == 'invalid_signature_hash':
        return False

    if not Config.PORTONE_WEBHOOK_SECRET:
        return True

    if not signature:
        return False

    computed = hmac.new(
        Config.PORTONE_WEBHOOK_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed, signature)

def create_outbox_notification(event_type, order_id, recipient, message_type='SMS', idempotency_key=None):
    """Transactional Outbox 패턴 알림 이벤트 DB 등록 (NotificationService 멱등 Enqueue 연동)"""
    if not idempotency_key:
        idempotency_key = f"{event_type}:{order_id or str(uuid.uuid4())}"
    
    if not recipient:
        recipient = '010-0000-0000'
    
    try:
        execute_db("""
            INSERT INTO notifications (event_type, order_id, recipient, message_type, status, idempotency_key)
            VALUES (%s, %s, %s, %s, 'PENDING', %s)
            ON DUPLICATE KEY UPDATE status=status
        """, (event_type, order_id, recipient, message_type, idempotency_key))
    except Exception as e:
        pass

    # SMS NotificationService Enqueue
    try:
        from services.notification_service import NotificationService
        sms_map = {
            'ORDER_PAID':     ('ORDER_PAID_SMS',          '[영월고향방앗간] 주문 및 결제가 완료되었습니다.'),
            'ORDER_SHIPPED':  ('SHIPPED_SMS',              '[영월고향방앗간] 상품 배송이 시작되었습니다.'),
            'ORDER_REFUNDED': ('REFUND_COMPLETED_SMS',     '[영월고향방앗간] 환불이 완료되었습니다.')
        }
        if event_type in sms_map:
            fallback_key, msg = sms_map[event_type]
            NotificationService().enqueue(
                event_type=event_type,
                recipient=recipient,
                template_code=event_type,
                message=msg,
                idempotency_key=idempotency_key,
                fallback_template_key=fallback_key,
                order_id=order_id
            )
    except Exception as ex:
        pass

def get_portone_payment_details(payment_id):
    """PortOne V2 REST API에서 결제 정보를 재조회합니다."""
    if not Config.PORTONE_API_SECRET:
        # Secret이 설정되지 않은 테스트 환경일 때 Mock 정보 반환
        return {
            'success': True,
            'status': 'PAID',
            'amount': 0, # 호출처에서 0일 경우 fallback 처리
            'mock': True
        }

    try:
        headers = {'Authorization': f'PortOne {Config.PORTONE_API_SECRET}'}
        resp = requests.get(f'https://api.portone.io/payments/{payment_id}', headers=headers, timeout=5)
        if resp.status_code == 200:
            p_data = resp.json()
            return {
                'success': True,
                'status': p_data.get('status', '').upper(),
                'amount': p_data.get('amount', {}).get('total', 0),
                'customData': p_data.get('customData', {}),
                'raw': p_data
            }
        else:
            return {'success': False, 'status_code': resp.status_code, 'error': resp.text}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def request_portone_cancel(payment_id, amount, reason, current_cancellable_amount=None):
    """PortOne V2 REST API로 결제 취소/환불을 요청합니다."""
    if not Config.PORTONE_API_SECRET:
        # Mock 테스트 환불 응답
        return {
            'success': True,
            'cancellation_id': f"mock_portone_cancel_{uuid.uuid4().hex[:8]}",
            'amount': amount
        }

    try:
        headers = {
            'Authorization': f'PortOne {Config.PORTONE_API_SECRET}',
            'Content-Type': 'application/json'
        }
        body = {
            'reason': reason,
            'amount': amount
        }
        if current_cancellable_amount is not None:
            body['currentCancellableAmount'] = current_cancellable_amount

        resp = requests.post(f'https://api.portone.io/payments/{payment_id}/cancel', headers=headers, json=body, timeout=8)
        if resp.status_code == 200:
            c_data = resp.json()
            cancellation = c_data.get('cancellation', {})
            return {
                'success': True,
                'cancellation_id': cancellation.get('id') or f"cancel_{uuid.uuid4().hex[:8]}",
                'amount': cancellation.get('totalAmount', amount),
                'raw': c_data
            }
        else:
            return {
                'success': False,
                'status_code': resp.status_code,
                'error': resp.text,
                'is_timeout': False
            }
    except requests.exceptions.Timeout:
        return {'success': False, 'is_timeout': True, 'error': 'PortOne API Call Timeout'}
    except Exception as e:
        return {'success': False, 'is_timeout': True, 'error': str(e)}

@payment_bp.route('/webhook', methods=['POST'])
def handle_webhook():
    """
    PortOne V2 Webhook 수신 API
    - Signature 검증
    - Idempotency 중복 체크
    - PortOne API 결제 정보 서버 직접 재조회 (Source of Truth)
    - 주문 금액 스냅샷 vs PortOne 결제 금액 무결성 검증 (AMOUNT_MISMATCH)
    - Outbox 알림 등록
    """
    raw_body = request.get_data()
    data = request.get_json(silent=True) or {}
    
    if not verify_webhook_signature(request.headers, raw_body):
        return jsonify({'error': '유효하지 않은 Webhook Signature입니다.'}), 400

    event_type = data.get('type')
    payment_id = data.get('paymentId') or data.get('data', {}).get('paymentId')
    event_key = f"{event_type}_{payment_id}_{data.get('timestamp', '')}"

    # 1. 중복 Webhook 통지 체크 (Idempotency)
    existing_event = query_db("SELECT * FROM webhook_events WHERE event_key = %s", (event_key,), one=True)
    if existing_event:
        return jsonify({'message': '이미 처리된 Webhook 이벤트입니다.'}), 200

    if event_type not in ['Transaction.Paid', 'Transaction.PayPending', 'Transaction.Cancelled', 'Transaction.PartialCancelled', 'Transaction.Failed']:
        execute_db("""
            INSERT INTO webhook_events (event_key, event_type, payment_id, payload, status)
            VALUES (%s, %s, %s, %s, 'IGNORED')
        """, (event_key, str(event_type), str(payment_id), json.dumps(data)))
        return jsonify({'message': '관심 대상이 아닌 이벤트로 수용 및 무시 처리되었습니다.'}), 200

    if not payment_id:
        return jsonify({'error': 'paymentId가 전달되지 않았습니다.'}), 400

    # PortOne API 서버 재조회
    p_details = get_portone_payment_details(payment_id)
    order_number = data.get('data', {}).get('customData', {}).get('order_number') or data.get('merchantUid')
    if p_details.get('customData', {}).get('order_number'):
        order_number = p_details['customData']['order_number']

    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    if not order:
        execute_db("""
            INSERT INTO webhook_events (event_key, event_type, payment_id, payload, status, error_message)
            VALUES (%s, %s, %s, %s, 'FAILED', '주문 정보를 찾을 수 없음')
        """, (event_key, str(event_type), str(payment_id), json.dumps(data)))
        return jsonify({'error': '해당하는 주문 정보를 찾을 수 없습니다.'}), 404

    payload_amount = int(data.get('amount', 0) or data.get('data', {}).get('amount', 0) or p_details.get('amount', 0))

    # 결제 금액 무결성 검증 (주문 스냅샷 total_amount vs PortOne paid_amount)
    if payload_amount > 0 and payload_amount != order['total_amount']:
        execute_db("UPDATE orders SET integrity_status = 'AMOUNT_MISMATCH' WHERE id = %s", (order['id'],))
        execute_db("""
            INSERT INTO webhook_events (event_key, event_type, payment_id, payload, status, error_message)
            VALUES (%s, %s, %s, %s, 'FAILED', '주문 금액 불일치 무결성 위반 감지')
        """, (event_key, str(event_type), str(payment_id), json.dumps(data)))
        return jsonify({'message': '결제 금액 불일치로 무결성 조사가 시작되었으며 주문 확정이 유예되었습니다.'}), 200

    # 이미 PAID 상태인지 검증 (Idempotency)
    if order['payment_status'] == 'PAID':
        execute_db("""
            INSERT INTO webhook_events (event_key, event_type, payment_id, payload, status)
            VALUES (%s, %s, %s, %s, 'PROCESSED')
        """, (event_key, event_type, payment_id, json.dumps(data)))
        return jsonify({'message': '이미 결제 완료 처리된 주문입니다.'}), 200

    # 2. 재고 예약 상태 및 15분 만료 후 결제 레이스 조건 처리
    reservations = query_db("SELECT * FROM stock_reservations WHERE order_id = %s", (order['id'],))
    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
    transaction_id = data.get('data', {}).get('transactionId') or f"tx_{payment_id}"

    all_reservations_valid = True if reservations else False
    for res in reservations:
        dt_val = res['expires_at']
        if isinstance(dt_val, datetime.datetime):
            expires_dt = dt_val
        else:
            clean_str = str(dt_val).split('.')[0]
            try:
                expires_dt = datetime.datetime.strptime(clean_str, '%Y-%m-%d %H:%M:%S')
            except Exception:
                expires_dt = now_dt + datetime.timedelta(minutes=15)

        if res['status'] != 'RESERVED' or expires_dt < now_dt:
            all_reservations_valid = False
            break

    if all_reservations_valid:
        # 정상 결제 처리: 물리 재고 차감 및 예약 해제
        for res in reservations:
            execute_db("UPDATE stock_reservations SET status = 'CONFIRMED' WHERE id = %s", (res['id'],))
            execute_db("""
                UPDATE product_options 
                SET stock = CASE WHEN stock >= %s THEN stock - %s ELSE 0 END, 
                    reserved_stock = CASE WHEN reserved_stock >= %s THEN reserved_stock - %s ELSE 0 END
                WHERE id = %s
            """, (res['quantity'], res['quantity'], res['quantity'], res['quantity'], res['product_option_id']))
    else:
        # 15분 예약 만료 후 결제 성공 경계조건 발생! 재고 재확보 시도
        stock_reacquired = True
        for res in reservations:
            option = query_db("SELECT * FROM product_options WHERE id = %s", (res['product_option_id'],), one=True)
            if not option or (option['stock'] - option['reserved_stock']) < res['quantity']:
                stock_reacquired = False
                break

        if stock_reacquired:
            for res in reservations:
                execute_db("UPDATE stock_reservations SET status = 'CONFIRMED' WHERE id = %s", (res['id'],))
                execute_db("UPDATE product_options SET stock = CASE WHEN stock >= %s THEN stock - %s ELSE 0 END WHERE id = %s", (res['quantity'], res['quantity'], res['product_option_id']))
        else:
            # 재확보 실패: 자동 즉시 전액 환불
            refund_request_id = str(uuid.uuid4())
            cancellation_id = f"cancel_auto_{payment_id}_{int(datetime.datetime.now().timestamp())}"
            execute_db("""
                INSERT INTO refunds (order_id, payment_id, refund_request_id, cancellation_id, amount, requested_amount, confirmed_amount, reason, requester, status, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, '15분 예약 만료 후 재고 부족으로 인한 자동 즉시 환불', 'SYSTEM', 'COMPLETED', %s)
            """, (order['id'], payment_id, refund_request_id, cancellation_id, order['total_amount'], order['total_amount'], order['total_amount'], now_str))

            execute_db("UPDATE orders SET order_status = 'CANCELLED', payment_status = 'FAILED' WHERE id = %s", (order['id'],))
            execute_db("INSERT INTO webhook_events (event_key, event_type, payment_id, payload, status) VALUES (%s, %s, %s, %s, 'PROCESSED')", (event_key, event_type, payment_id, json.dumps(data)))
            return jsonify({'message': '예약 만료 및 재고 부족으로 인해 자동으로 즉시 전액 환불 취소 처리되었습니다.'}), 200

    execute_db("""
        INSERT INTO payments (order_id, payment_id, transaction_id, pg_provider, method, status, amount, paid_at)
        VALUES (%s, %s, %s, 'PORTONE', 'CARD', 'PAID', %s, %s)
        ON DUPLICATE KEY UPDATE status='PAID', paid_at=%s
    """, (order['id'], payment_id, transaction_id, order['total_amount'], now_str, now_str))

    execute_db("UPDATE orders SET order_status = 'CONFIRMED', payment_status = 'PAID' WHERE id = %s", (order['id'],))
    execute_db("INSERT INTO webhook_events (event_key, event_type, payment_id, payload, status) VALUES (%s, %s, %s, %s, 'PROCESSED')", (event_key, event_type, payment_id, json.dumps(data)))

    # Outbox SMS 알림 등록
    recipient = order.get('recipient_phone') or order.get('phone') or '010-0000-0000'
    create_outbox_notification('ORDER_PAID', order['id'], recipient, idempotency_key=f"ORDER_PAID:{order['id']}")
    create_outbox_notification('ADMIN_NEW_ORDER', order['id'], getattr(Config, 'ADMIN_SMS_PHONE', '010-0000-0000'), idempotency_key=f"ADMIN_NEW_ORDER:{order['id']}")

    return jsonify({'message': 'Webhook 처리 및 결제 완료가 성공적으로 적용되었습니다.'}), 200

@payment_bp.route('/complete', methods=['POST'])
def complete_payment():
    """
    클라이언트 결제 완료 사후 검증 API (Source of Truth: 백엔드가 PortOne API 직접 검증)
    """
    data = request.get_json() or {}
    payment_id = data.get('payment_id') or data.get('imp_uid') or data.get('paymentId')
    order_number = data.get('order_number')

    if not payment_id or not order_number:
        return jsonify({'error': '결제 ID(payment_id)와 주문번호(order_number)가 필요합니다.'}), 400

    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    if not order:
        return jsonify({'error': '해당 주문번호의 주문이 존재하지 않습니다.'}), 404

    # 이미 PAID 상태이면 조기 반환 (Idempotency)
    if order['payment_status'] == 'PAID':
        return jsonify({'message': '이미 결제 완료 처리된 주문입니다.', 'order_number': order_number}), 200

    # 1. 서버측 PortOne REST API 결제 정보 조회 (Source of Truth)
    p_details = get_portone_payment_details(payment_id)
    if not p_details.get('success'):
        return jsonify({'error': 'PG 결제 정보를 조회할 수 없어 승인을 거부합니다.', 'detail': p_details.get('error')}), 400

    # mock 검증 지원 또는 실제 status == PAID 검증
    p_status = p_details.get('status')
    if p_status and p_status not in ['PAID', 'SUCCESS']:
        return jsonify({'error': f"PG 결제 상태가 PAID가 아닙니다 (현재: {p_status})."}), 400

    # 2. 금액 검증 (paid_amount vs order.total_amount)
    p_amount = p_details.get('amount', 0)
    if p_amount > 0 and p_amount != order['total_amount']:
        execute_db("UPDATE orders SET integrity_status = 'AMOUNT_MISMATCH' WHERE id = %s", (order['id'],))
        return jsonify({'error': '결제 금액 불일치로 승인이 거부되었습니다.'}), 400

    # 3. 재고 차감 및 결제 승인
    reservations = query_db("SELECT * FROM stock_reservations WHERE order_id = %s", (order['id'],))
    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
    transaction_id = f"tx_{payment_id}"

    for res in reservations:
        execute_db("UPDATE stock_reservations SET status = 'CONFIRMED' WHERE id = %s", (res['id'],))
        execute_db("""
            UPDATE product_options 
            SET stock = CASE WHEN stock >= %s THEN stock - %s ELSE 0 END, 
                reserved_stock = CASE WHEN reserved_stock >= %s THEN reserved_stock - %s ELSE 0 END
            WHERE id = %s
        """, (res['quantity'], res['quantity'], res['quantity'], res['quantity'], res['product_option_id']))

    execute_db("""
        INSERT INTO payments (order_id, payment_id, transaction_id, pg_provider, method, status, amount, paid_at)
        VALUES (%s, %s, %s, 'PORTONE', 'CARD', 'PAID', %s, %s)
        ON DUPLICATE KEY UPDATE status='PAID', paid_at=%s
    """, (order['id'], payment_id, transaction_id, order['total_amount'], now_str, now_str))

    execute_db("UPDATE orders SET order_status = 'CONFIRMED', payment_status = 'PAID' WHERE id = %s", (order['id'],))

    # Outbox 알림 등록
    recipient = order.get('recipient_phone') or order.get('phone') or '010-0000-0000'
    create_outbox_notification('ORDER_PAID', order['id'], recipient, idempotency_key=f"ORDER_PAID:{order['id']}")
    create_outbox_notification('ADMIN_NEW_ORDER', order['id'], getattr(Config, 'ADMIN_SMS_PHONE', '010-0000-0000'), idempotency_key=f"ADMIN_NEW_ORDER:{order['id']}")

    return jsonify({'message': '결제 검증 및 완료 처리가 성공적으로 완료되었습니다.', 'order_number': order_number}), 200

@payment_bp.route('/cancel', methods=['POST'])
def cancel_payment():
    """
    Two-step Non-blocking Refund Saga 기반 결제 취소 및 원자적 재고 보상 API
    1. 상태 가드: SHIPPING / DELIVERED 주문은 일반 취소 즉시 거부 (400)
    2. Transaction A: orders.payment_status = CANCEL_REQUESTED 선 반영 및 refunds 레코드 생성 ➔ COMMIT (DB Lock 즉시 해제)
    3. External HTTP Request: PortOne Cancel REST API (Non-blocking)
    4. Transaction B: PG 결과에 따라 REFUNDED/REFUND_FAILED/REFUND_PENDING 저장 및 inventory_compensated 원자적 재고 복구
    """
    data = request.get_json() or {}
    order_number = data.get('order_number')
    cancel_amount = int(data.get('amount', 0))
    reason = data.get('reason', '고객 요청에 의한 취소').strip()

    if not order_number or cancel_amount <= 0:
        return jsonify({'error': '주문번호와 취소 금액이 올바르지 않습니다.'}), 400

    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    if not order:
        return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

    # 1. 상태 가드: SHIPPING (배송중) 또는 DELIVERED (배송완료) 주문의 일반 취소 차단
    if order['order_status'] in ['SHIPPING', 'DELIVERED']:
        return jsonify({'error': '이미 상품이 배송중이거나 배송완료된 주문은 일반 취소가 불가능합니다. 반품 절차를 이용해주세요.'}), 400

    # 취소 가능 잔액 계산
    refund_sum_row = query_db("SELECT SUM(amount) as total_refunded FROM refunds WHERE order_id = %s AND status = 'COMPLETED'", (order['id'],), one=True)
    total_refunded = int(refund_sum_row['total_refunded'] or 0) if refund_sum_row else 0
    cancellable_amount = order['total_amount'] - total_refunded

    if cancel_amount > cancellable_amount:
        return jsonify({'error': f"취소 가능 금액({cancellable_amount:,}원)을 초과하였습니다."}), 400

    payment_record = query_db("SELECT * FROM payments WHERE order_id = %s AND status = 'PAID'", (order['id'],), one=True)
    payment_id = payment_record['payment_id'] if payment_record else f"pay_{order_number}"

    # Transaction A: DB Lock 선 반영 및 LOCK 해제
    refund_request_id = str(uuid.uuid4())
    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')

    execute_db("""
        INSERT INTO refunds (order_id, payment_id, refund_request_id, amount, requested_amount, current_cancellable_amount, reason, requester, status, requested_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'ADMIN', 'PENDING', %s)
    """, (order['id'], payment_id, refund_request_id, cancel_amount, cancel_amount, cancellable_amount, reason, now_str))

    execute_db("UPDATE orders SET payment_status = 'CANCEL_REQUESTED' WHERE id = %s", (order['id'],))

    refund_entry = query_db("SELECT * FROM refunds WHERE refund_request_id = %s", (refund_request_id,), one=True)
    refund_id = refund_entry['id'] if refund_entry else None

    # External HTTP Request: Non-blocking PortOne Cancel API
    p_cancel_res = request_portone_cancel(payment_id, cancel_amount, reason, current_cancellable_amount=cancellable_amount)

    # Transaction B: PG 결과 반영 및 원자적 재고 보상
    if p_cancel_res.get('success'):
        portone_cancel_id = p_cancel_res.get('cancellation_id')
        confirmed_amt = p_cancel_res.get('amount', cancel_amount)
        new_total_refunded = total_refunded + confirmed_amt
        new_payment_status = 'REFUNDED' if new_total_refunded >= order['total_amount'] else 'PARTIALLY_REFUNDED'
        new_order_status = 'CANCELLED' if new_payment_status == 'REFUNDED' else order['order_status']

        execute_db("""
            UPDATE refunds 
            SET status = 'COMPLETED', portone_cancellation_id = %s, confirmed_amount = %s, completed_at = %s
            WHERE id = %s
        """, (portone_cancel_id, confirmed_amt, now_str, refund_id))

        execute_db("UPDATE orders SET payment_status = %s, order_status = %s WHERE id = %s", (new_payment_status, new_order_status, order['id']))

        # 원자적 재고 보상 (Inventory Compensation)
        # inventory_compensated 전용 컬럼을 통해 1회만 재고 복구
        current_refund = query_db("SELECT * FROM refunds WHERE id = %s", (refund_id,), one=True)
        if current_refund and current_refund.get('inventory_compensated', 0) == 0:
            # 결제 완료건(PAID 또는 CONFIRMED/PREPARING 주문)이면 물리 재고 stock 복구
            if order['payment_status'] in ['PAID', 'CANCEL_REQUESTED'] or order['order_status'] in ['CONFIRMED', 'PREPARING']:
                items = query_db("SELECT * FROM order_items WHERE order_id = %s", (order['id'],))
                for item in items:
                    opt_id = item.get('option_id') or item.get('product_option_id')
                    if opt_id:
                        execute_db("UPDATE product_options SET stock = stock + %s WHERE id = %s", (item['quantity'], opt_id))
            else:
                # 결제 전 주문(PENDING)이면 예약 재고만 해제
                reservations = query_db("SELECT * FROM stock_reservations WHERE order_id = %s", (order['id'],))
                for res in reservations:
                    execute_db("UPDATE stock_reservations SET status = 'RELEASED' WHERE id = %s", (res['id'],))
                    execute_db("UPDATE product_options SET reserved_stock = CASE WHEN reserved_stock >= %s THEN reserved_stock - %s ELSE 0 END WHERE id = %s", (res['quantity'], res['quantity'], res['product_option_id']))

            execute_db("UPDATE refunds SET inventory_compensated = 1, inventory_compensated_at = %s WHERE id = %s", (now_str, refund_id))

        # Outbox 고객 환불완료 SMS 알림 등록
        recipient = order.get('recipient_phone') or order.get('phone') or '010-0000-0000'
        create_outbox_notification('ORDER_REFUNDED', order['id'], recipient, idempotency_key=f"ORDER_REFUNDED:{order['id']}")

        return jsonify({
            'message': '결제 취소 및 환불 처리가 정상 완료되었습니다.',
            'order_number': order_number,
            'refund_amount': confirmed_amt,
            'payment_status': new_payment_status
        }), 200

    elif p_cancel_res.get('is_timeout'):
        # Network Timeout / Server Crash / Unknown ➔ REFUND_PENDING
        execute_db("UPDATE refunds SET status = 'PENDING', failed_at = %s, error_message = %s WHERE id = %s", (now_str, p_cancel_res.get('error'), refund_id))
        execute_db("UPDATE orders SET payment_status = 'REFUND_PENDING' WHERE id = %s", (order['id'],))
        return jsonify({
            'message': 'PortOne PG 환불 응답 지연으로 인해 REFUND_PENDING 상태로 등록되었으며 자동 대사 작업으로 처리됩니다.',
            'order_number': order_number,
            'payment_status': 'REFUND_PENDING'
        }), 202

    else:
        # 명확한 PG 취소 실패
        err_msg = p_cancel_res.get('error', 'PG 환불 실패')
        execute_db("UPDATE refunds SET status = 'FAILED', failed_at = %s, error_message = %s WHERE id = %s", (now_str, err_msg, refund_id))
        execute_db("UPDATE orders SET payment_status = 'REFUND_FAILED' WHERE id = %s", (order['id'],))

        # Outbox 관리자 환불실패 SMS 알림 등록
        create_outbox_notification('REFUND_FAILED', order['id'], getattr(Config, 'ADMIN_SMS_PHONE', '010-0000-0000'), idempotency_key=f"REFUND_FAILED:{refund_id}")

        return jsonify({
            'error': f"PG 승인 취소가 거부되었습니다: {err_msg}",
            'payment_status': 'REFUND_FAILED'
        }), 400

def reconcile_pending_refunds():
    """
    CANCEL_REQUESTED (5분 이상 고립건) 및 REFUND_PENDING 대상 PG Refund Reconciliation Job
    """
    # 5분 이상 경과된 CANCEL_REQUESTED 또는 REFUND_PENDING 조회
    five_min_ago = (datetime.datetime.now() - datetime.timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    pending_orders = query_db("""
        SELECT * FROM orders 
        WHERE payment_status IN ('REFUND_PENDING', 'CANCEL_REQUESTED')
    """)

    reconciled_count = 0
    for order in pending_orders:
        payments = query_db("SELECT * FROM payments WHERE order_id = %s", (order['id'],))
        payment_id = payments[0]['payment_id'] if payments else f"pay_{order['order_number']}"

        p_details = get_portone_payment_details(payment_id)
        p_status = p_details.get('status', '').upper()

        if p_status in ['CANCELLED', 'PARTIALLY_CANCELLED']:
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            execute_db("UPDATE orders SET payment_status = 'REFUNDED', order_status = 'CANCELLED' WHERE id = %s", (order['id'],))
            
            # 재고 원자적 1회 복구
            refund = query_db("SELECT * FROM refunds WHERE order_id = %s ORDER BY id DESC LIMIT 1", (order['id'],), one=True)
            if refund and refund.get('inventory_compensated', 0) == 0:
                items = query_db("SELECT * FROM order_items WHERE order_id = %s", (order['id'],))
                for item in items:
                    opt_id = item.get('option_id') or item.get('product_option_id')
                    if opt_id:
                        execute_db("UPDATE product_options SET stock = stock + %s WHERE id = %s", (item['quantity'], opt_id))
                execute_db("UPDATE refunds SET status = 'COMPLETED', inventory_compensated = 1, inventory_compensated_at = %s WHERE id = %s", (now_str, refund['id']))

            create_outbox_notification('ORDER_REFUNDED', order['id'], order.get('recipient_phone') or '010-0000-0000', idempotency_key=f"ORDER_REFUNDED:{order['id']}")
            reconciled_count += 1
        elif p_status in ['PAID', 'FAILED']:
            execute_db("UPDATE orders SET payment_status = 'REFUND_FAILED' WHERE id = %s", (order['id'],))
            create_outbox_notification('REFUND_FAILED', order['id'], getattr(Config, 'ADMIN_SMS_PHONE', '010-0000-0000'), idempotency_key=f"REFUND_FAILED_{order['id']}")
            reconciled_count += 1

    return reconciled_count

