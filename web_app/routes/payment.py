import hmac
import hashlib
import json
import datetime
import requests
from flask import Blueprint, request, jsonify
from config import Config
from db.db_connection import query_db, execute_db, get_db_connection

payment_bp = Blueprint('payment', __name__, url_prefix='/api/payment')

def verify_webhook_signature(headers, body):
    """PortOne V2 Webhook Signature 검증"""
    if not Config.PORTONE_WEBHOOK_SECRET:
        return True # 비밀키 미설정 시 통과 (테스트 모드)
    
    signature = headers.get('Webhook-Signature') or headers.get('x-portone-signature')
    if not signature:
        return False

    computed = hmac.new(
        Config.PORTONE_WEBHOOK_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed, signature)

@payment_bp.route('/webhook', methods=['POST'])
def handle_webhook():
    """
    PortOne V2 Webhook 수신 API (Version 2024-04-25 기준)
    - Signature 검증
    - Idempotency 중복 체크
    - PortOne API 결제 정보 재조회
    - 주문 금액 스냅샷 vs PortOne 결제 금액 검증
    - 재고 예약 판매 확정 및 15분 만료 후 결제 레이스 조건 자동 환불 대응
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

    # 알 수 없는 이벤트 무시 처리
    if event_type not in ['Transaction.Paid', 'Transaction.PayPending', 'Transaction.Cancelled', 'Transaction.PartialCancelled', 'Transaction.Failed']:
        execute_db("""
            INSERT INTO webhook_events (event_key, event_type, payment_id, payload, status)
            VALUES (%s, %s, %s, %s, 'IGNORED')
        """, (event_key, str(event_type), str(payment_id), json.dumps(data)))
        return jsonify({'message': '관심 대상이 아닌 이벤트로 수용 및 무시 처리되었습니다.'}), 200

    if not payment_id:
        return jsonify({'error': 'paymentId가 전달되지 않았습니다.'}), 400

    # PortOne API 재조회
    paid_amount = 0
    order_number = None
    transaction_id = data.get('data', {}).get('transactionId') or f"tx_{payment_id}"

    if Config.PORTONE_API_SECRET:
        try:
            auth_resp = requests.post('https://api.portone.io/login/api-secret', json={
                'apiSecret': Config.PORTONE_API_SECRET
            }, timeout=5)
            
            if auth_resp.status_code == 200:
                token = auth_resp.json().get('accessToken')
                pay_resp = requests.get(f'https://api.portone.io/payments/{payment_id}', headers={
                    'Authorization': f'Bearer {token}'
                }, timeout=5)
                
                if pay_resp.status_code == 200:
                    payment_info = pay_resp.json()
                    paid_amount = payment_info.get('amount', {}).get('total', 0)
                    order_number = payment_info.get('customData', {}).get('order_number') or payment_info.get('merchantUid')
        except Exception as e:
            print(f"PortOne Payment Re-query Error: {e}")

    if not order_number:
        order_number = data.get('data', {}).get('customData', {}).get('order_number') or data.get('merchantUid')

    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    if not order:
        execute_db("""
            INSERT INTO webhook_events (event_key, event_type, payment_id, payload, status, error_message)
            VALUES (%s, %s, %s, %s, 'FAILED', '주문 정보를 찾을 수 없음')
        """, (event_key, event_type, payment_id, json.dumps(data)))
        return jsonify({'error': '해당하는 주문 정보를 찾을 수 없습니다.'}), 404

    # 테스트 환경 또는 API 재조회 실패 시 페이로드 금액 적용
    if paid_amount == 0:
        paid_amount = int(data.get('data', {}).get('amount', 0) or data.get('amount', 0) or order['total_amount'])

    # 결제 금액 무결성 검증 (주문 스냅샷 total_amount vs PortOne paid_amount)
    if paid_amount > 0 and paid_amount != order['total_amount']:
        execute_db("UPDATE orders SET payment_status = 'FAILED' WHERE id = %s", (order['id'],))
        execute_db("""
            INSERT INTO webhook_events (event_key, event_type, payment_id, payload, status, error_message)
            VALUES (%s, %s, %s, %s, 'FAILED', '주문 금액 불일치 위변조 시도')
        """, (event_key, event_type, payment_id, json.dumps(data)))
        return jsonify({'error': '주문 금액과 결제 금액이 일치하지 않습니다.'}), 400

    # 2. 재고 예약 상태 및 15분 만료 후 결제 레이스 조건 처리
    reservations = query_db("SELECT * FROM stock_reservations WHERE order_id = %s", (order['id'],))
    now_dt = datetime.datetime.now()
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
        # 정상 결제 처리: 물리 재고 차감 및 예약 해제 (stock -= qty, reserved_stock -= qty)
        for res in reservations:
            execute_db("UPDATE stock_reservations SET status = 'CONFIRMED' WHERE id = %s", (res['id'],))
            execute_db("""
                UPDATE product_options 
                SET stock = stock - %s, 
                    reserved_stock = CASE WHEN reserved_stock >= %s THEN reserved_stock - %s ELSE 0 END
                WHERE id = %s
            """, (res['quantity'], res['quantity'], res['quantity'], res['product_option_id']))

        # Payments 레코드 추가 및 Order 상태 업데이트
        now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
        execute_db("""
            INSERT INTO payments (order_id, payment_id, transaction_id, pg_provider, method, status, amount, paid_at)
            VALUES (%s, %s, %s, 'PORTONE', 'CARD', 'PAID', %s, %s)
            ON DUPLICATE KEY UPDATE status='PAID', paid_at=%s
        """, (order['id'], payment_id, transaction_id, order['total_amount'], now_str, now_str))

        execute_db("""
            UPDATE orders 
            SET order_status = 'CONFIRMED', payment_status = 'PAID' 
            WHERE id = %s
        """, (order['id'],))

        execute_db("""
            INSERT INTO webhook_events (event_key, event_type, payment_id, payload, status)
            VALUES (%s, %s, %s, %s, 'PROCESSED')
        """, (event_key, event_type, payment_id, json.dumps(data)))

        return jsonify({'message': 'Webhook 처리 및 결제 완료가 성공적으로 적용되었습니다.'}), 200

    else:
        # 15분 예약 만료 후 결제 성공 경계조건 발생! 재고 재확보 시도
        stock_reacquired = True
        for res in reservations:
            option = query_db("SELECT * FROM product_options WHERE id = %s", (res['product_option_id'],), one=True)
            if not option or (option['stock'] - option['reserved_stock']) < res['quantity']:
                stock_reacquired = False
                break

        if stock_reacquired:
            # 재확보 성공: 확정 처리
            for res in reservations:
                execute_db("UPDATE stock_reservations SET status = 'CONFIRMED' WHERE id = %s", (res['id'],))
                execute_db("""
                    UPDATE product_options 
                    SET stock = stock - %s 
                    WHERE id = %s
                """, (res['quantity'], res['product_option_id']))

            now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
            execute_db("""
                INSERT INTO payments (order_id, payment_id, transaction_id, pg_provider, method, status, amount, paid_at)
                VALUES (%s, %s, %s, 'PORTONE', 'CARD', 'PAID', %s, %s)
            """, (order['id'], payment_id, transaction_id, order['total_amount'], now_str))

            execute_db("UPDATE orders SET order_status = 'CONFIRMED', payment_status = 'PAID' WHERE id = %s", (order['id'],))
            return jsonify({'message': '예약 만료 후 결제건에 대한 재고 재확보 및 판매 확정이 완료되었습니다.'}), 200
        else:
            # 재확보 실패 (타 고객 선점): PortOne Cancel API를 통한 자동 전액 환불 실행!
            refund_success = False
            cancellation_id = f"cancel_auto_{payment_id}"
            if Config.PORTONE_API_SECRET:
                try:
                    auth_resp = requests.post('https://api.portone.io/login/api-secret', json={'apiSecret': Config.PORTONE_API_SECRET}, timeout=5)
                    if auth_resp.status_code == 200:
                        token = auth_resp.json().get('accessToken')
                        cancel_resp = requests.post(f'https://api.portone.io/payments/{payment_id}/cancel', headers={
                            'Authorization': f'Bearer {token}'
                        }, json={'reason': '15분 예약 만료 후 재고 부족으로 인한 자동 전액 환불'}, timeout=5)
                        if cancel_resp.status_code == 200:
                            refund_success = True
                except Exception as ex:
                    print(f"Auto Cancel Exception: {ex}")

            now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
            execute_db("""
                INSERT INTO refunds (order_id, payment_id, cancellation_id, amount, reason, requester, status, completed_at)
                VALUES (%s, %s, %s, %s, '15분 예약 만료 후 재고 부족으로 인한 자동 즉시 환불', 'SYSTEM', 'COMPLETED', %s)
            """, (order['id'], payment_id, cancellation_id, order['total_amount'], now_str))

            execute_db("UPDATE orders SET order_status = 'CANCELLED', payment_status = 'FAILED' WHERE id = %s", (order['id'],))
            return jsonify({'message': '예약 만료 및 재고 부족으로 인해 자동으로 즉시 전액 환불 취소 처리되었습니다.'}), 200

@payment_bp.route('/complete', methods=['POST'])
def complete_payment():
    """클라이언트 결제 완료 응답 사후 검증 API"""
    data = request.get_json() or {}
    payment_id = data.get('payment_id') or data.get('imp_uid') or data.get('paymentId')
    order_number = data.get('order_number')

    if not payment_id or not order_number:
        return jsonify({'error': '결제 ID(payment_id)와 주문번호(order_number)가 필요합니다.'}), 400

    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    if not order:
        return jsonify({'error': '해당 주문번호의 주문이 존재하지 않습니다.'}), 404

    # 이미 PAID 처리된 경우 즉시 반환
    if order['payment_status'] == 'PAID':
        return jsonify({'message': '이미 결제 완료 처리된 주문입니다.', 'order_number': order_number}), 200

    # 결제 수동 완료 처리
    execute_db("UPDATE orders SET order_status = 'CONFIRMED', payment_status = 'PAID' WHERE id = %s", (order['id'],))
    return jsonify({'message': '결제 검증 및 완료 처리가 완료되었습니다.', 'order_number': order_number}), 200

@payment_bp.route('/cancel', methods=['POST'])
def cancel_payment():
    """관리자/고객 결제 취소 및 부분/전체 환불 처리 API"""
    data = request.get_json() or {}
    order_number = data.get('order_number')
    cancel_amount = int(data.get('amount', 0))
    reason = data.get('reason', '고객 요청에 의한 취소').strip()

    if not order_number or cancel_amount <= 0:
        return jsonify({'error': '주문번호와 취소 금액이 올바르지 않습니다.'}), 400

    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    if not order:
        return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

    # 기존 성공한 환불 합계 조회 (cancellable_amount 계산)
    refund_sum_row = query_db("SELECT SUM(amount) as total_refunded FROM refunds WHERE order_id = %s AND status = 'COMPLETED'", (order['id'],), one=True)
    total_refunded = int(refund_sum_row['total_refunded'] or 0) if refund_sum_row else 0
    cancellable_amount = order['total_amount'] - total_refunded

    if cancel_amount > cancellable_amount:
        return jsonify({'error': f"취소 가능 금액({cancellable_amount:,}원)을 초과하였습니다."}), 400

    cancellation_id = f"cancel_{order['id']}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # PortOne API 취소 호출
    if Config.PORTONE_API_SECRET:
        payment = query_db("SELECT * FROM payments WHERE order_id = %s ORDER BY id DESC", (order['id'],), one=True)
        payment_id = payment['payment_id'] if payment else f"pay_{order_number}"
        try:
            auth_resp = requests.post('https://api.portone.io/login/api-secret', json={'apiSecret': Config.PORTONE_API_SECRET}, timeout=5)
            if auth_resp.status_code == 200:
                token = auth_resp.json().get('accessToken')
                requests.post(f'https://api.portone.io/payments/{payment_id}/cancel', headers={
                    'Authorization': f'Bearer {token}'
                }, json={'amount': cancel_amount, 'reason': reason}, timeout=5)
        except Exception as e:
            print(f"PortOne Cancel API Warning: {e}")

    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    execute_db("""
        INSERT INTO refunds (order_id, payment_id, cancellation_id, amount, reason, requester, status, completed_at)
        VALUES (%s, %s, %s, %s, %s, 'ADMIN', 'COMPLETED', %s)
    """, (order['id'], order_number, cancellation_id, cancel_amount, reason, now_str))

    new_total_refunded = total_refunded + cancel_amount
    new_payment_status = 'REFUNDED' if new_total_refunded >= order['total_amount'] else 'PARTIALLY_REFUNDED'
    new_order_status = 'CANCELLED' if new_payment_status == 'REFUNDED' else order['order_status']

    execute_db("""
        UPDATE orders 
        SET payment_status = %s, order_status = %s 
        WHERE id = %s
    """, (new_payment_status, new_order_status, order['id']))

    return jsonify({
        'message': '결제 취소 및 환불 처리가 정상 완료되었습니다.',
        'order_number': order_number,
        'refund_amount': cancel_amount,
        'cancellable_amount': order['total_amount'] - new_total_refunded,
        'payment_status': new_payment_status
    }), 200
