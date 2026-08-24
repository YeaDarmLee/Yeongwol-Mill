import json
import hashlib
import uuid
import datetime
import requests
import logging
from config import Config
from db.db_connection import query_db, execute_db, get_db_connection

logger = logging.getLogger(__name__)

def generate_request_fingerprint(order_id, items, reason_code):
    """Canonical JSON 기반 SHA-256 request_fingerprint 생성"""
    sorted_items = sorted(
        [{"order_item_id": int(i["order_item_id"]), "quantity": int(i["quantity"])} for i in items],
        key=lambda x: x["order_item_id"]
    )
    canonical_payload = {
        "order_id": int(order_id),
        "items": sorted_items,
        "reason_code": str(reason_code).strip()
    }
    canonical_json_str = json.dumps(canonical_payload, sort_keys=True)
    return hashlib.sha256(canonical_json_str.encode('utf-8')).hexdigest()

def finalize_refund(refund_request_id, confirmed_refund_amount=None):
    """FinalizeRefund() 멱등 Guard 함수 (SELECT FOR UPDATE & COMPLETED early return)"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. refund_request FOR UPDATE
            cursor.execute("SELECT * FROM refund_requests WHERE id = %s FOR UPDATE", (refund_request_id,))
            req = cursor.fetchone()
            if not req:
                conn.rollback()
                return False, "Refund request not found"
            
            if req['status'] == 'COMPLETED':
                conn.rollback()
                return True, "ALREADY_COMPLETED"  # 멱등 Guard Early Return

            order_id = req['order_id']
            refund_amount = confirmed_refund_amount if confirmed_refund_amount is not None else req['requested_amount']

            # 2. refund_request_items 조회
            cursor.execute("SELECT * FROM refund_request_items WHERE refund_request_id = %s", (refund_request_id,))
            req_items = cursor.fetchall() or []

            # 3. order_items 수량 갱신 & 재고 보상
            for r_item in req_items:
                item_id = r_item['order_item_id']
                r_qty = r_item['requested_qty']

                cursor.execute("""
                    UPDATE order_items 
                    SET cancelled_qty = cancelled_qty + %s
                    WHERE id = %s
                """, (r_qty, item_id))

                # 재고 1회 보상 (source_line_id UNIQUE)
                cursor.execute("SELECT product_id, option_id FROM order_items WHERE id = %s", (item_id,))
                oi = cursor.fetchone()
                if oi and oi['option_id']:
                    opt_id = oi['option_id']
                    cursor.execute("SELECT stock, reserved_stock FROM product_options WHERE id = %s FOR UPDATE", (opt_id,))
                    opt = cursor.fetchone()
                    if opt:
                        prev_stock = opt['stock']
                        curr_stock = prev_stock + r_qty
                        cursor.execute("UPDATE product_options SET stock = stock + %s WHERE id = %s", (r_qty, opt_id))
                        
                        # inventory_transactions INSERT (uk_inventory_source_line)
                        source_line_id = str(r_item['id'])
                        try:
                            cursor.execute("""
                                INSERT INTO inventory_transactions (
                                    product_option_id, change_qty, previous_stock, current_stock,
                                    reason_code, source_type, source_id, source_line_id, movement_type
                                ) VALUES (%s, %s, %s, %s, %s, 'REFUND_REQUEST', %s, %s, 'CANCEL_RESTOCK')
                            """, (opt_id, r_qty, prev_stock, curr_stock, 'ORDER_CANCEL', str(refund_request_id), source_line_id))
                        except Exception as inv_err:
                            logger.warning(f"Inventory transaction duplicate ignored: {inv_err}")

            # 4. payment_status 재계산
            cursor.execute("SELECT SUM(item_paid_amount) as total_paid, SUM(cancelled_qty * (item_paid_amount / quantity)) as total_cancelled FROM order_items WHERE order_id = %s", (order_id,))
            stat = cursor.fetchone()
            
            cursor.execute("SELECT total_amount FROM orders WHERE id = %s", (order_id,))
            ord_row = cursor.fetchone()

            cursor.execute("SELECT SUM(confirmed_refund_amount) as total_refunded FROM refund_requests WHERE order_id = %s AND status = 'COMPLETED'", (order_id,))
            rf_row = cursor.fetchone()
            existing_rf = int(rf_row['total_refunded'] or 0) if rf_row else 0
            new_total_rf = existing_rf + refund_amount

            cursor.execute("SELECT order_status, total_amount FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            ord_row = cursor.fetchone()

            if ord_row and new_total_rf >= ord_row['total_amount'] and ord_row['order_status'] in ('PENDING', 'CONFIRMED', 'PREPARING'):
                new_payment_status = 'REFUNDED'
                new_order_status = 'CANCELLED'
            else:
                new_payment_status = 'REFUNDED' if (ord_row and new_total_rf >= ord_row['total_amount']) else 'PARTIALLY_REFUNDED'
                new_order_status = None

            if new_order_status:
                cursor.execute("UPDATE orders SET payment_status = %s, order_status = %s WHERE id = %s", (new_payment_status, new_order_status, order_id))
            else:
                cursor.execute("UPDATE orders SET payment_status = %s WHERE id = %s", (new_payment_status, order_id))

            # 5. notification_outbox 등록 (dedup_key UNIQUE)
            dedup_key = f"REFUND_NOTIF_{refund_request_id}"
            try:
                cursor.execute("""
                    INSERT INTO notification_outbox (
                        event_type, channel, recipient, payload_json, status, dedup_key
                    ) VALUES ('REFUND_COMPLETED', 'EMAIL', 'user@yeongwol.com', %s, 'PENDING', %s)
                """, (json.dumps({"refund_request_id": refund_request_id, "amount": refund_amount}), dedup_key))
            except Exception as notif_err:
                logger.warning(f"Notification outbox duplicate ignored: {notif_err}")

            # 6. refund_request COMPLETED 전환
            cursor.execute("""
                UPDATE refund_requests 
                SET status = 'COMPLETED', confirmed_refund_amount = %s, updated_at = NOW() 
                WHERE id = %s
            """, (refund_amount, refund_request_id))

            conn.commit()
            return True, "SUCCESS"
    except Exception as e:
        conn.rollback()
        logger.error(f"FinalizeRefund failed for req_id {refund_request_id}: {e}")
        return False, str(e)
    finally:
        conn.close()

def process_refund_request(order_id, operation_id, items, reason, admin_id=1):
    """
    2-Phase 멱등 환불 Engine
    TX #1: 사전 검증 & PROCESSING 저장 ➔ DB Lock 즉시 해제
    PortOne Cancel API 호출
    TX #2: FinalizeRefund() 멱등 확정
    """
    if not operation_id:
        operation_id = str(uuid.uuid4())

    request_fingerprint = generate_request_fingerprint(order_id, items, reason)

    # 1. [TX #1] 사전 검증 & 멱등 조회
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            ord_row = cursor.fetchone()
            if not ord_row:
                conn.rollback()
                return {'error': '주문을 찾을 수 없습니다.'}, 404
            
            if ord_row.get('refund_calculation_mode') == 'MANUAL_REVIEW':
                conn.rollback()
                return {'error': '스냅샷 백필 불일치 주문입니다. 관리자 수동 검토가 필요합니다.'}, 400

            if ord_row.get('order_status') in ('SHIPPING', 'DELIVERED'):
                conn.rollback()
                return {
                    'code': 'USE_RETURN_CLAIM',
                    'error': '출고 완료된(배송중/배송완료) 주문은 직접 환불할 수 없습니다. 반품 Claim 절차를 이용해 주세요.'
                }, 409

            # 멱등 조회
            cursor.execute("SELECT * FROM refund_requests WHERE operation_id = %s FOR UPDATE", (operation_id,))
            existing_req = cursor.fetchone()
            if existing_req:
                if existing_req['request_fingerprint'] != request_fingerprint:
                    conn.rollback()
                    return {'error': '동일한 operation_id에 서로 다른 환불 요청입니다 (409 Conflict).'}, 409
                
                # 기존 멱등 결과 반환
                conn.rollback()
                if existing_req['status'] == 'COMPLETED':
                    return {'message': '이미 성공적으로 처리된 환불 요청입니다.', 'status': 'COMPLETED', 'refund_request_id': existing_req['id']}, 200
                elif existing_req['status'] in ('RECONCILING', 'CANCEL_PENDING'):
                    return {'message': '결제 대조 중(RECONCILING)입니다. 비동기 확정 진행 중입니다.', 'status': existing_req['status']}, 202
                elif existing_req['status'] == 'FAILED':
                    return {'error': f"이전 환불 처리 실패: {existing_req.get('last_error_message')}"}, 400

            # 환불 수량 및 금액 계산
            total_req_amount = 0
            req_items_data = []

            for it in items:
                item_id = int(it['order_item_id'])
                qty = int(it['quantity'])

                cursor.execute("SELECT * FROM order_items WHERE id = %s AND order_id = %s FOR UPDATE", (item_id, order_id))
                oi = cursor.fetchone()
                if not oi:
                    conn.rollback()
                    return {'error': f'주문 상품(ID: {item_id})을 찾을 수 없습니다.'}, 404

                rem_qty = oi['quantity'] - oi['cancelled_qty']
                if qty <= 0 or qty > rem_qty:
                    conn.rollback()
                    return {'error': f"상품 '{oi['product_name_snapshot']}'의 환불 가능 수량({rem_qty}개)을 초과했습니다."}, 400

                unit_paid = oi['item_paid_amount'] // oi['quantity'] if (oi.get('item_paid_amount') and oi['quantity']) else oi['final_unit_price']
                item_refund_amt = unit_paid * qty
                total_req_amount += item_refund_amt

                req_items_data.append({
                    'order_item_id': item_id,
                    'requested_qty': qty,
                    'refund_amount': item_refund_amt,
                    'inventory_compensation_qty': qty
                })

            # PortOne 취소 가능 잔액 조회 및 멱등키 생성
            idempotency_key = f"IDEM_{operation_id}"
            portone_payment_id = f"PAY_{ord_row['order_number']}"
            cancellable_before = ord_row['total_amount']

            # PROCESSING 저장
            cursor.execute("""
                INSERT INTO refund_requests (
                    order_id, operation_id, request_fingerprint, idempotency_key,
                    portone_payment_id, requested_amount, cancellable_amount_before,
                    status, reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'PROCESSING', %s)
            """, (order_id, operation_id, request_fingerprint, idempotency_key, portone_payment_id, total_req_amount, cancellable_before, reason))
            
            refund_req_id = cursor.lastrowid

            for r_item in req_items_data:
                cursor.execute("""
                    INSERT INTO refund_request_items (
                        refund_request_id, order_item_id, requested_qty, refund_amount, inventory_compensation_qty
                    ) VALUES (%s, %s, %s, %s, %s)
                """, (refund_req_id, r_item['order_item_id'], r_item['requested_qty'], r_item['refund_amount'], r_item['inventory_compensation_qty']))

            conn.commit()  # TX #1 COMMIT ➔ DB Lock 해제!
    except Exception as err:
        conn.rollback()
        logger.error(f"TX #1 Refund Pre-check error: {err}")
        return {'error': '환불 사전 검증 중 오류가 발생했습니다.'}, 500
    finally:
        conn.close()

    # 2. PortOne Cancel API 호출 (Mock / Real API)
    # 개발/테스트 환경에서는 항상 정상 승인(SUCCEEDED) 시뮬레이션
    cancellation_status = "SUCCEEDED"
    portone_cancellation_id = f"CANCEL_{uuid.uuid4().hex[:12]}"

    if cancellation_status == "SUCCEEDED":
        # 3. [TX #2] FinalizeRefund 멱등 확정
        success, msg = finalize_refund(refund_req_id, total_req_amount)
        if success:
            execute_db("UPDATE refund_requests SET portone_cancellation_id = %s WHERE id = %s", (portone_cancellation_id, refund_req_id))
            return {
                'message': '환불 처리가 성공적으로 완료되었습니다.',
                'refund_request_id': refund_req_id,
                'confirmed_amount': total_req_amount,
                'status': 'COMPLETED'
            }, 200
        else:
            # Local DB Commit 실패 시 RECONCILING 대조 전환
            execute_db("UPDATE refund_requests SET status = 'RECONCILING' WHERE id = %s", (refund_req_id,))
            return {
                'message': '환불은 PG 승인되었으나 결제 대조 중(RECONCILING)입니다. 자동 복구됩니다.',
                'status': 'RECONCILING'
            }, 202

    elif cancellation_status == "REQUESTED":
        execute_db("UPDATE refund_requests SET status = 'CANCEL_PENDING' WHERE id = %s", (refund_req_id,))
        return {'message': 'PG 취소 요청 완료(CANCEL_PENDING). 비동기 확정 대기 중입니다.', 'status': 'CANCEL_PENDING'}, 202

    elif cancellation_status == "FAILED":
        execute_db("UPDATE refund_requests SET status = 'FAILED', last_error_message = %s WHERE id = %s", ("PortOne cancellation failed", refund_req_id))
        return {'error': 'PG 결제 취소가 거부되었습니다.'}, 400

    else:
        execute_db("UPDATE refund_requests SET status = 'RECONCILING' WHERE id = %s", (refund_req_id,))
        return {'message': '결제 대조 중(RECONCILING)입니다. Webhook/조회 후 자동 확정됩니다.', 'status': 'RECONCILING'}, 202

def preview_refund_calculation(order_id, items):
    """환불 예정 금액 및 잔액 미리보기 (비확정 참고용 계산)"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            ord_row = cursor.fetchone()
            if not ord_row:
                return {'error': '주문을 찾을 수 없습니다.'}, 404

            total_req_amount = 0
            preview_items = []

            for it in items:
                item_id = int(it['order_item_id'])
                qty = int(it['quantity'])

                cursor.execute("SELECT * FROM order_items WHERE id = %s AND order_id = %s", (item_id, order_id))
                oi = cursor.fetchone()
                if not oi:
                    return {'error': f'주문 상품(ID: {item_id})을 찾을 수 없습니다.'}, 404

                rem_qty = oi['quantity'] - oi['cancelled_qty']
                if qty <= 0 or qty > rem_qty:
                    return {'error': f"상품 '{oi['product_name_snapshot']}'의 환불 가능 수량({rem_qty}개)을 초과했습니다."}, 400

                unit_paid = oi['item_paid_amount'] // oi['quantity'] if (oi.get('item_paid_amount') and oi['quantity']) else oi['final_unit_price']
                item_refund_amt = unit_paid * qty
                total_req_amount += item_refund_amt

                preview_items.append({
                    'order_item_id': item_id,
                    'product_name': oi['product_name_snapshot'],
                    'requested_qty': qty,
                    'item_refund_amount': item_refund_amt
                })

            cursor.execute("SELECT SUM(confirmed_refund_amount) as total_refunded FROM refund_requests WHERE order_id = %s AND status = 'COMPLETED'", (order_id,))
            rf_row = cursor.fetchone()
            existing_rf = int(rf_row['total_refunded'] or 0) if (rf_row and rf_row['total_refunded']) else 0
            remaining_paid = ord_row['total_amount'] - existing_rf - total_req_amount

            return {
                'preview_refund_amount': total_req_amount,
                'existing_refunded_amount': existing_rf,
                'remaining_paid_amount': max(0, remaining_paid),
                'total_order_amount': ord_row['total_amount'],
                'items': preview_items,
                'disclaimer': '예상 환불액이며, 최종 실행 시 현재 결제/환불 상태를 다시 검증합니다.'
            }, 200
    finally:
        conn.close()
