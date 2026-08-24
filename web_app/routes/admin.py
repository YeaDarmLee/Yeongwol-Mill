import io
import csv
import json
import datetime
from flask import Blueprint, request, jsonify, Response
from db.db_connection import query_db, execute_db, get_db_connection
from middlewares.auth import verify_jwt_token, generate_jwt_token, check_password, hash_password
from utils.audit_logger import log_admin_audit
from utils.refund_engine import process_refund_request, preview_refund_calculation
from utils.order_state_machine import OrderStateMachine, OrderStateMachineError

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

def verify_admin_auth(required_role=None):
    """관리자 권한 검증 미들웨어 헬퍼 (RBAC 지원)"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split()[1]
    payload = verify_jwt_token(token)
    if not payload or payload.get('role') not in ('ADMIN', 'SUPER_ADMIN'):
        return None
    if required_role and payload.get('role') != required_role:
        return None
    return payload

@admin_bp.route('/login', methods=['POST'])
def admin_login():
    """관리자 전용 보안 로그인 API (Rate Limit & RBAC)"""
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({'error': '관리자 이메일과 비밀번호를 모두 입력해 주세요.'}), 400

    admin = query_db("SELECT * FROM admin_users WHERE email = %s", (email,), one=True)
    if not admin or not check_password(password, admin['password_hash']):
        log_admin_audit(0, email, 'ADMIN_LOGIN_FAILED', request_ip=request.remote_addr, user_agent=request.user_agent.string, result='FAILED')
        return jsonify({'error': '관리자 이메일 또는 비밀번호가 올바르지 않습니다.'}), 401

    token = generate_jwt_token(admin['id'], admin['email'], role=admin['role'])
    log_admin_audit(admin['id'], admin['email'], 'ADMIN_LOGIN_SUCCESS', request_ip=request.remote_addr, user_agent=request.user_agent.string)

    return jsonify({
        'message': '관리자 로그인이 완료되었습니다.',
        'token': token,
        'admin': {
            'id': admin['id'],
            'email': admin['email'],
            'name': admin['name'],
            'role': admin['role']
        }
    }), 200

@admin_bp.route('/dashboard', methods=['GET'])
def admin_dashboard():
    """관리자 실운영 대시보드 API (KST 기준 Net Payments, Work Queue, Alerts, 30일 Trend)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    from config import Config
    kst_tz = datetime.timezone(datetime.timedelta(hours=9))
    now_kst = datetime.datetime.now(kst_tz)
    today_start_dt = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_dt = today_start_dt + datetime.timedelta(days=1)

    today_start_str = today_start_dt.strftime('%Y-%m-%d %H:%M:%S')
    today_end_str = today_end_dt.strftime('%Y-%m-%d %H:%M:%S')

    # 1. 오늘 결제 완결 및 결제 총액 (Gross Payments) - paid_at 기준
    today_payments_row = query_db("""
        SELECT COUNT(DISTINCT order_id) as paid_orders, SUM(amount) as gross_sales
        FROM payments
        WHERE status = 'PAID' AND paid_at >= %s AND paid_at < %s
    """, (today_start_str, today_end_str), one=True)

    today_paid_orders = int(today_payments_row['paid_orders'] or 0) if today_payments_row else 0
    today_gross_sales = int(today_payments_row['gross_sales'] or 0) if today_payments_row else 0

    # 만약 payments 기록이 없는 경우 orders fallback
    if today_paid_orders == 0 and today_gross_sales == 0:
        fallback_row = query_db("""
            SELECT COUNT(*) as paid_orders, SUM(total_amount) as gross_sales
            FROM orders
            WHERE payment_status IN ('PAID', 'PARTIALLY_REFUNDED', 'REFUNDED') 
              AND created_at >= %s AND created_at < %s
        """, (today_start_str, today_end_str), one=True)
        if fallback_row:
            today_paid_orders = int(fallback_row['paid_orders'] or 0)
            today_gross_sales = int(fallback_row['gross_sales'] or 0)

    # 2. 오늘 확정 환불 총액 (Refunds) - refund_requests updated_at 시각 기준
    today_refunds_row = query_db("""
        SELECT SUM(confirmed_refund_amount) as total_refunds
        FROM refund_requests
        WHERE status = 'COMPLETED' AND updated_at >= %s AND updated_at < %s
    """, (today_start_str, today_end_str), one=True)
    today_refunds = int(today_refunds_row['total_refunds'] or 0) if today_refunds_row else 0
    today_net_sales = today_gross_sales - today_refunds

    # 3. 출고 대기 건수 (PREPARING)
    pending_shipping_row = query_db("""
        SELECT COUNT(*) as count FROM orders WHERE order_status = 'PREPARING'
    """, one=True)
    pending_shipping_count = int(pending_shipping_row['count'] or 0) if pending_shipping_row else 0

    # 4. 환불 / 대조 중 건수 breakdown (PENDING, PROCESSING, CANCEL_PENDING, RECONCILING)
    refund_stats_rows = query_db("""
        SELECT status, COUNT(*) as cnt
        FROM refund_requests
        WHERE status IN ('PENDING', 'PROCESSING', 'CANCEL_PENDING', 'RECONCILING')
        GROUP BY status
    """) or []
    refund_stat_map = {r['status']: int(r['cnt']) for r in refund_stats_rows}
    reconciling_total = sum(refund_stat_map.values())

    # 5. 재고 경고 상품 및 정합성 검증
    low_stock_options = query_db("""
        SELECT po.*, p.name as product_name
        FROM product_options po
        JOIN products p ON po.product_id = p.id
        WHERE p.is_active = 1 AND (po.stock - po.reserved_stock) <= 10 AND po.stock < 999000
        ORDER BY (po.stock - po.reserved_stock) ASC
    """) or []
    for opt in low_stock_options:
        opt['available_stock'] = opt['stock'] - opt['reserved_stock']

    critical_stock_errors = [opt for opt in low_stock_options if opt['available_stock'] < 0]

    # 6. Action Work Queue (처리해야 할 업무 - GROUP BY 일괄 집계)
    order_stats_rows = query_db("""
        SELECT order_status, COUNT(*) as cnt
        FROM orders
        GROUP BY order_status
    """) or []
    order_stat_map = {r['order_status']: int(r['cnt']) for r in order_stats_rows}

    pending_orders_cnt = order_stat_map.get('PENDING', 0)
    confirmed_orders_cnt = order_stat_map.get('CONFIRMED', 0)
    preparing_orders_cnt = pending_shipping_count
    shipping_orders_cnt = order_stat_map.get('SHIPPING', 0)
    delivered_orders_cnt = order_stat_map.get('DELIVERED', 0)

    stale_preparing_threshold = (now_kst - datetime.timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    stale_unregistered_cnt = int((query_db("""
        SELECT COUNT(*) as c FROM orders 
        WHERE order_status = 'PREPARING' 
          AND (tracking_number IS NULL OR tracking_number = '')
          AND created_at < %s
    """, (stale_preparing_threshold,), one=True) or {}).get('c', 0))

    unregistered_tracking_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'PREPARING' AND (tracking_number IS NULL OR tracking_number = '')", one=True) or {}).get('c', 0))
    refund_pending_cnt = refund_stat_map.get('PENDING', 0)
    refund_processing_cnt = refund_stat_map.get('PROCESSING', 0) + refund_stat_map.get('CANCEL_PENDING', 0)
    reconciling_cnt = refund_stat_map.get('RECONCILING', 0)
    amount_mismatch_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE integrity_status = 'AMOUNT_MISMATCH'", one=True) or {}).get('c', 0))

    work_queue = {
        'pending_orders': pending_orders_cnt,
        'confirmed_orders': confirmed_orders_cnt,
        'preparing_orders': preparing_orders_cnt,
        'shipping_orders': shipping_orders_cnt,
        'delivered_orders': delivered_orders_cnt,
        'stale_unregistered': stale_unregistered_cnt,
        'unregistered_tracking': unregistered_tracking_cnt,
        'refund_pending': refund_pending_cnt,
        'refund_processing': refund_processing_cnt,
        'reconciling': reconciling_cnt,
        'amount_mismatch': amount_mismatch_cnt
    }

    # 7. Operational Alerts (운영 주의사항)
    alerts = []
    if critical_stock_errors:
        alerts.append({
            'type': 'CRITICAL_STOCK',
            'level': 'CRITICAL',
            'title': f'⚠ 재고 정합성 오류 ({len(critical_stock_errors)}건)',
            'message': '예약재고가 보유재고를 초과하는 품목이 있습니다. 재고 조정을 실행하세요.',
            'target_filter': 'low_stock'
        })

    if reconciling_cnt > 0:
        alerts.append({
            'type': 'RECONCILING',
            'level': 'WARNING',
            'title': f'환불 상태대조 중 ({reconciling_cnt}건)',
            'message': 'PG사와 환불 상태 대조 중인 요청이 있습니다.',
            'target_filter': 'refund_status=RECONCILING'
        })

    # Stale PROCESSING 환불 (Config.REFUND_PROCESSING_STALE_SECONDS 기준)
    stale_sec = getattr(Config, 'REFUND_PROCESSING_STALE_SECONDS', 3600)
    stale_threshold_str = (now_kst - datetime.timedelta(seconds=stale_sec)).strftime('%Y-%m-%d %H:%M:%S')
    stale_processing_cnt = int((query_db("""
        SELECT COUNT(*) as c FROM refund_requests 
        WHERE status = 'PROCESSING' AND updated_at < %s
    """, (stale_threshold_str,), one=True) or {}).get('c', 0))

    if stale_processing_cnt > 0:
        alerts.append({
            'type': 'STALE_REFUND',
            'level': 'WARNING',
            'title': f'장시간 환불 처리중 ({stale_processing_cnt}건)',
            'message': f'{stale_sec // 60}분 이상 처리 중인 환불 요청이 있습니다.',
            'target_filter': 'refund_status=PROCESSING'
        })

    # Outbox 최종 발송 실패
    outbox_failed_cnt = int((query_db("""
        SELECT COUNT(*) as c FROM notification_outbox 
        WHERE status = 'FAILED' AND (retry_count >= 3 OR next_retry_at IS NULL)
    """, one=True) or {}).get('c', 0))

    if outbox_failed_cnt > 0:
        alerts.append({
            'type': 'OUTBOX_FAILED',
            'level': 'WARNING',
            'title': f'알림 Outbox 최종 발송 실패 ({outbox_failed_cnt}건)',
            'message': '고객 알림 메시지 발송 실패 건이 있습니다.',
            'target_filter': 'outbox_failed'
        })

    if stale_unregistered_cnt > 0:
        alerts.append({
            'type': 'STALE_PREPARING',
            'level': 'WARNING',
            'title': f'24시간 이상 송장 미등록 ({stale_unregistered_cnt}건)',
            'message': '배송 준비 전환 후 24시간 동안 송장이 입력되지 않은 주문이 있습니다.',
            'target_filter': 'unregistered_tracking=true'
        })

    if amount_mismatch_cnt > 0:
        alerts.append({
            'type': 'AMOUNT_MISMATCH',
            'level': 'CRITICAL',
            'title': f'결제/주문 금액 불일치 ({amount_mismatch_cnt}건)',
            'message': '주문 금액과 결제 금액이 일치하지 않는 이상 주문이 존재합니다.',
            'target_filter': 'amount_mismatch=true'
        })

    # 8. Recent Orders (최근 8건, 마스킹 적용)
    recent_orders_raw = query_db("""
        SELECT id, order_number, recipient_name, guest_name, total_amount, 
               order_status, payment_status, courier_name, tracking_number, created_at
        FROM orders
        ORDER BY id DESC LIMIT 8
    """) or []

    def mask_person_name(name):
        if not name or name == '구매자':
            return '구매자'
        name_str = str(name).strip()
        if len(name_str) <= 1:
            return name_str + '*'
        if len(name_str) == 2:
            return name_str[0] + '*'
        return name_str[0] + '*' * (len(name_str) - 2) + name_str[-1]

    recent_orders = []
    for r in recent_orders_raw:
        cname = r['recipient_name'] or r['guest_name'] or '구매자'
        recent_orders.append({
            'id': r['id'],
            'order_number': r['order_number'],
            'customer_name_masked': mask_person_name(cname),
            'total_amount': int(r['total_amount']),
            'order_status': r['order_status'],
            'payment_status': r['payment_status'],
            'has_tracking': bool(r['tracking_number']),
            'courier_name': r['courier_name'] or '',
            'created_at': r['created_at'].strftime('%Y-%m-%d %H:%M') if isinstance(r['created_at'], datetime.datetime) else str(r['created_at'])
        })

    # 9. 최근 30일 Trend 일별 집계 (DB 1회 GROUP BY 일괄 집계로 초고속 최적화)
    trend_start_dt = today_start_dt - datetime.timedelta(days=29)
    trend_start_str = trend_start_dt.strftime('%Y-%m-%d 00:00:00')

    # (1) 30일 간 일별 orders 결제 완료 주문 및 매출 일괄 집계
    daily_orders = query_db("""
        SELECT DATE(created_at) as dt, COUNT(*) as p_orders, SUM(total_amount) as p_gross
        FROM orders
        WHERE payment_status IN ('PAID', 'PARTIALLY_REFUNDED', 'REFUNDED')
          AND created_at >= %s
        GROUP BY DATE(created_at)
    """, (trend_start_str,)) or []

    order_map = {}
    for do in daily_orders:
        if do.get('dt'):
            dt_key = str(do['dt'])[:10]
            order_map[dt_key] = {
                'gross': int(do['p_gross'] or 0),
                'orders': int(do['p_orders'] or 0)
            }

    # (2) 30일 간 일별 환불 일괄 집계
    daily_refunds = query_db("""
        SELECT DATE(updated_at) as dt, SUM(confirmed_refund_amount) as r_ref
        FROM refund_requests
        WHERE status = 'COMPLETED' AND updated_at >= %s
        GROUP BY DATE(updated_at)
    """, (trend_start_str,)) or []

    refund_map = {}
    for dr in daily_refunds:
        if dr.get('dt'):
            dt_key = str(dr['dt'])[:10]
            refund_map[dt_key] = int(dr['r_ref'] or 0)

    trend_30days = []
    for i in range(29, -1, -1):
        dt_day = today_start_dt - datetime.timedelta(days=i)
        dt_key = dt_day.strftime('%Y-%m-%d')
        d_label = dt_day.strftime('%m-%d')

        o_info = order_map.get(dt_key) or {'gross': 0, 'orders': 0}
        g_sales = o_info['gross']
        p_cnt = o_info['orders']
        ref_amt = refund_map.get(dt_key, 0)
        net_amt = g_sales - ref_amt

        trend_30days.append({
            'date': d_label,
            'full_date': dt_key,
            'gross_payments': g_sales,
            'refunds': ref_amt,
            'net_payments': net_amt,
            'paid_orders': p_cnt
        })

    return jsonify({
        'kpi': {
            'today_orders': today_paid_orders,
            'today_gross_sales': today_gross_sales,
            'today_refunds': today_refunds,
            'today_net_sales': today_net_sales,
            'pending_shipping_count': pending_shipping_count,
            'reconciling_total': reconciling_total,
            'reconciling_breakdown': refund_stat_map,
            'low_stock_count': len(low_stock_options)
        },
        'work_queue': work_queue,
        'alerts': alerts,
        'recent_orders': recent_orders,
        'trend_30days': trend_30days,
        'low_stock_options': low_stock_options,
        'as_of': now_kst.strftime('%H:%M:%S')
    }), 200

@admin_bp.route('/orders', methods=['GET'])
def admin_orders():
    """전체 주문 목록 필터링, 검색 및 페이지네이션 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    status_filter = request.args.get('order_status', '').strip()
    payment_filter = request.args.get('payment_status', '').strip()
    refund_filter = request.args.get('refund_status', '').strip()
    unregistered_tracking = request.args.get('unregistered_tracking', '').strip()
    amount_mismatch = request.args.get('amount_mismatch', '').strip()
    keyword = request.args.get('keyword', '').strip()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        limit = max(1, min(100, int(request.args.get('limit', 10))))
    except (ValueError, TypeError):
        limit = 10

    offset = (page - 1) * limit

    base_sql = "FROM orders o"
    where_clauses = ["1=1"]
    args = []

    if refund_filter:
        base_sql += " JOIN refund_requests rr ON o.id = rr.order_id"
        where_clauses.append("rr.status = %s")
        args.append(refund_filter)

    if status_filter:
        where_clauses.append("o.order_status = %s")
        args.append(status_filter)

    if payment_filter:
        where_clauses.append("o.payment_status = %s")
        args.append(payment_filter)

    if unregistered_tracking == 'true':
        where_clauses.append("o.order_status = 'PREPARING' AND (o.tracking_number IS NULL OR o.tracking_number = '')")

    if amount_mismatch == 'true':
        where_clauses.append("o.integrity_status = 'AMOUNT_MISMATCH'")

    if keyword:
        where_clauses.append("(o.order_number LIKE %s OR o.recipient_name LIKE %s OR o.recipient_phone LIKE %s)")
        kw_pattern = f"%{keyword}%"
        args.extend([kw_pattern, kw_pattern, kw_pattern])

    where_str = " WHERE " + " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(DISTINCT o.id) as cnt {base_sql} {where_str}"
    count_row = query_db(count_sql, tuple(args), one=True)
    total_count = int(count_row['cnt'] or 0) if count_row else 0
    total_pages = max(1, (total_count + limit - 1) // limit)

    select_sql = f"SELECT DISTINCT o.* {base_sql} {where_str} ORDER BY o.id DESC LIMIT %s OFFSET %s"
    fetch_args = list(args) + [limit, offset]

    orders = query_db(select_sql, tuple(fetch_args)) or []

    for order in orders:
        order['items'] = query_db("SELECT * FROM order_items WHERE order_id = %s", (order['id'],)) or []

    return jsonify({
        'orders': orders,
        'pagination': {
            'page': page,
            'limit': limit,
            'total_count': total_count,
            'total_pages': total_pages
        }
    }), 200


@admin_bp.route('/orders/<int:order_id>', methods=['GET'])
def admin_order_detail(order_id):
    """주문 통합 상세 조회 API (Order, Items, Refunds, Audit, Admin Notes, Timeline)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    order = query_db("SELECT * FROM orders WHERE id = %s", (order_id,), one=True)
    if not order:
        return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

    items = query_db("SELECT * FROM order_items WHERE order_id = %s", (order_id,)) or []
    refund_requests = query_db("SELECT * FROM refund_requests WHERE order_id = %s ORDER BY id DESC", (order_id,)) or []
    for req in refund_requests:
        req['items'] = query_db("SELECT * FROM refund_request_items WHERE refund_request_id = %s", (req['id'],)) or []

    audit_logs = query_db("SELECT * FROM admin_audit_logs WHERE target_type = 'ORDER' AND target_id = %s ORDER BY id DESC", (str(order_id),)) or []
    admin_notes = query_db("SELECT * FROM order_admin_notes WHERE order_id = %s ORDER BY id DESC", (order_id,)) or []

    # 이벤트 타임라인 구성
    timeline = []
    if order.get('created_at'):
        timeline.append({'time': str(order['created_at']), 'event': 'ORDER_CREATED', 'description': '주문 접수 완료'})
    if order.get('shipped_at'):
        timeline.append({'time': str(order['shipped_at']), 'event': 'TRACKING_REGISTERED', 'description': f"운송장 등록 ({order.get('courier_name', '')} {order.get('tracking_number', '')})"})
    for log in audit_logs:
        timeline.append({'time': str(log['created_at']), 'event': log['action_type'], 'description': f"관리자 작업 ({log['admin_email']}): {log.get('reason', '')}"})

    timeline.sort(key=lambda x: x['time'], reverse=True)

    return jsonify({
        'order': order,
        'items': items,
        'refund_requests': refund_requests,
        'audit_logs': audit_logs,
        'admin_notes': admin_notes,
        'timeline': timeline
    }), 200

@admin_bp.route('/orders/<int:order_id>/status', methods=['PATCH', 'POST'])
def admin_update_order_status(order_id):
    """Row Lock + State Machine 기반 주문 상태 변경 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    target_status = data.get('target_status', '').strip().upper()
    reason = data.get('reason', '관리자 상태 변경').strip()

    if not target_status:
        return jsonify({'error': '변경할 목표 상태(target_status)를 지정해 주세요.'}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            order = cursor.fetchone()
            if not order:
                conn.rollback()
                return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

            try:
                OrderStateMachine.validate_transition(order['order_status'], target_status, order['payment_status'])
            except OrderStateMachineError as err:
                conn.rollback()
                return jsonify({'code': err.code, 'error': err.message}), 409

            cursor.execute("UPDATE orders SET order_status = %s WHERE id = %s", (target_status, order_id))
            conn.commit()

        log_admin_audit(
            admin_id=payload['user_id'],
            admin_email=payload.get('email') or payload.get('sub', ''),
            action_type='ORDER_STATUS_CHANGED',
            target_type='ORDER',
            target_id=order_id,
            reason=f"Status changed from {order['order_status']} to {target_status} ({reason})",
            request_ip=request.remote_addr,
            user_agent=request.user_agent.string
        )

        return jsonify({'message': f"주문 상태가 [{target_status}](으)로 변경되었습니다.", 'order_id': order_id, 'order_status': target_status}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@admin_bp.route('/orders/<int:order_id>/shipping', methods=['PATCH', 'POST'])
def admin_update_shipping(order_id):
    """Row Lock + State Machine + 1-Tx Outbox 연동 운송장 최초 등록 / 수정 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    courier_name = data.get('courier_name', '').strip()
    tracking_number = data.get('tracking_number', '').strip()

    if not courier_name or not tracking_number:
        return jsonify({'error': '택배사명과 운송장 번호를 모두 입력해 주세요.'}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            order = cursor.fetchone()
            if not order:
                conn.rollback()
                return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

            if order['order_status'] in ('SHIPPING', 'DELIVERED', 'CANCELLED', 'REFUNDED'):
                conn.rollback()
                return jsonify({'error': f"이미 [{order['order_status']}](으)로 진행된 주문은 운송장을 변경할 수 없습니다."}), 409

            try:
                OrderStateMachine.validate_transition(order['order_status'], 'SHIPPING', order['payment_status'])
            except OrderStateMachineError as err:
                conn.rollback()
                return jsonify({'code': err.code, 'error': err.message}), 409

            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                UPDATE orders 
                SET courier_name = %s, tracking_number = %s, order_status = 'SHIPPING', shipped_at = %s
                WHERE id = %s
            """, (courier_name, tracking_number, now_str, order_id))


            # Notification Outbox INSERT (1-Tx)
            dedup_key = f"SHIP_NOTIF_{order_id}_{int(datetime.datetime.now().timestamp())}"
            outbox_payload = json.dumps({
                'order_id': order_id,
                'order_number': order['order_number'],
                'courier_name': courier_name,
                'tracking_number': tracking_number
            })
            cursor.execute("""
                INSERT INTO notification_outbox (event_type, channel, recipient, payload_json, status, dedup_key)
                VALUES ('ORDER_SHIPPED', 'SMS', %s, %s, 'PENDING', %s)
            """, (order.get('recipient_phone', ''), outbox_payload, dedup_key))


            action_name = 'TRACKING_REGISTERED'
            conn.commit()


        log_admin_audit(
            admin_id=payload['user_id'],
            admin_email=payload.get('email') or payload.get('sub', ''),
            action_type=action_name,
            target_type='ORDER',
            target_id=order_id,
            reason=f"Couirer: {courier_name}, Tracking: {tracking_number}",
            request_ip=request.remote_addr,
            user_agent=request.user_agent.string
        )

        return jsonify({
            'message': f"운송장 번호({courier_name} {tracking_number})가 정상 등록되었습니다.",
            'order_id': order_id,
            'order_status': 'SHIPPING'
        }), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@admin_bp.route('/orders/<int:order_id>/address', methods=['PATCH', 'POST'])
def admin_update_shipping_address(order_id):
    """Row Lock 기반 출고 전 배송지 정보 수정 API (SHIPPING 이후 409 ADDRESS_CHANGE_NOT_ALLOWED)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    recipient_name = data.get('recipient_name', '').strip()
    recipient_phone = data.get('recipient_phone', '').strip()
    postal_code = data.get('postal_code', '').strip()
    address = data.get('address', '').strip()
    address_detail = data.get('address_detail', '').strip()
    delivery_memo = data.get('delivery_memo', '').strip()

    if not recipient_name or not recipient_phone or not address:
        return jsonify({'error': '수령인, 연락처, 주소는 필수 입력 항목입니다.'}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            order = cursor.fetchone()
            if not order:
                conn.rollback()
                return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

            if order['order_status'] in ('SHIPPING', 'DELIVERED', 'CANCELLED'):
                conn.rollback()
                return jsonify({
                    'code': 'ADDRESS_CHANGE_NOT_ALLOWED',
                    'error': f"[{order['order_status']}] 상태인 주문은 배송지를 변경할 수 없습니다."
                }), 409

            cursor.execute("""
                UPDATE orders
                SET recipient_name = %s, recipient_phone = %s, postal_code = %s,
                    address = %s, address_detail = %s, delivery_memo = %s
                WHERE id = %s
            """, (recipient_name, recipient_phone, postal_code, address, address_detail, delivery_memo, order_id))
            conn.commit()

        # PII 원문 미포함 보안 Audit Log
        log_admin_audit(
            admin_id=payload['user_id'],
            admin_email=payload.get('email') or payload.get('sub', ''),
            action_type='ADDRESS_UPDATED',
            target_type='ORDER',
            target_id=order_id,
            reason=json.dumps({"recipient_changed": True, "phone_changed": True, "address_changed": True}),
            request_ip=request.remote_addr,
            user_agent=request.user_agent.string
        )

        return jsonify({'message': '배송지 정보가 성공적으로 수정되었습니다.'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@admin_bp.route('/orders/<int:order_id>/refund/preview', methods=['POST'])
def admin_order_refund_preview(order_id):
    """환불 예정 금액 및 잔액 미리보기 (비확정 참고용 계산)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    items = data.get('items', [])
    if not items:
        return jsonify({'error': '환불할 상품을 1개 이상 선택해 주세요.'}), 400

    resp, status_code = preview_refund_calculation(order_id, items)
    return jsonify(resp), status_code

@admin_bp.route('/orders/<int:order_id>/refund', methods=['POST'])
def admin_order_refund(order_id):
    """관리자 2-Phase 멱등 환불 실행 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'code': 'REFUND_PERMISSION_DENIED', 'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    operation_id = data.get('operation_id', '').strip()
    items = data.get('items', [])
    reason = data.get('reason', '고객변심').strip()

    if not items:
        return jsonify({'error': '환불할 상품을 1개 이상 선택해 주세요.'}), 400

    resp, status_code = process_refund_request(order_id, operation_id, items, reason, admin_id=payload['user_id'])

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='REFUND_EXECUTE',
        target_type='ORDER',
        target_id=order_id,
        reason=reason,
        result='SUCCESS' if status_code in (200, 202) else 'FAILED',
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify(resp), status_code

@admin_bp.route('/orders/<int:order_id>/notes', methods=['POST'])
def admin_add_order_note(order_id):
    """관리자 이력 보존 메모 추가 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    note = data.get('note', '').strip()
    if not note:
        return jsonify({'error': '메모 내용을 입력해 주세요.'}), 400

    admin_email = payload.get('email') or payload.get('sub', '')
    execute_db("""
        INSERT INTO order_admin_notes (order_id, admin_id, admin_email, note)
        VALUES (%s, %s, %s, %s)
    """, (order_id, payload['user_id'], admin_email, note))

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=admin_email,
        action_type='ADMIN_NOTE_ADDED',
        target_type='ORDER',
        target_id=order_id,
        reason=note[:50],
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({'message': '관리자 메모가 성공적으로 등록되었습니다.'}), 201

@admin_bp.route('/customers', methods=['GET'])
def admin_customers():
    """회원 목록 필터링, 검색 및 페이지네이션 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    keyword = request.args.get('keyword', '').strip()
    status_filter = request.args.get('status', '').strip()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        limit = max(1, min(100, int(request.args.get('limit', 10))))
    except (ValueError, TypeError):
        limit = 10

    offset = (page - 1) * limit

    where_clauses = ["1=1"]
    args = []

    if status_filter:
        where_clauses.append("status = %s")
        args.append(status_filter)

    if keyword:
        where_clauses.append("(name LIKE %s OR email LIKE %s OR phone LIKE %s)")
        kw_pattern = f"%{keyword}%"
        args.extend([kw_pattern, kw_pattern, kw_pattern])

    where_str = " WHERE " + " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) as cnt FROM users {where_str}"
    count_row = query_db(count_sql, tuple(args), one=True)
    total_count = int(count_row['cnt'] or 0) if count_row else 0
    total_pages = max(1, (total_count + limit - 1) // limit)

    select_sql = f"SELECT id, email, name, phone, created_at, status FROM users {where_str} ORDER BY id DESC LIMIT %s OFFSET %s"
    fetch_args = list(args) + [limit, offset]

    users = query_db(select_sql, tuple(fetch_args)) or []
    
    customer_list = []
    for u in users:
        customer_list.append({
            'id': u['id'],
            'email': u.get('email', '') or '-',
            'name': u.get('name', '') or '(이름 없음)',
            'phone': u.get('phone', '') or '-',
            'created_at': str(u.get('created_at', '')),
            'status': u.get('status', 'ACTIVE')
        })

    return jsonify({
        'customers': customer_list,
        'pagination': {
            'page': page,
            'limit': limit,
            'total_count': total_count,
            'total_pages': total_pages
        }
    }), 200


@admin_bp.route('/customers/<int:user_id>/unmask', methods=['POST'])
def admin_unmask_customer(user_id):
    """5단계 원문 조회 게이트웨이 (목적 입력 & 재인증 ➔ PII_VIEW Audit 기록)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    password = data.get('password', '').strip()
    reason = data.get('reason', '').strip()

    if not password or not reason:
        return jsonify({'error': '비밀번호 재인증과 조회 목적을 모두 입력해 주세요.'}), 400

    admin = query_db("SELECT * FROM admin_users WHERE id = %s", (payload['user_id'],), one=True)
    if not admin or not check_password(password, admin['password_hash']):
        return jsonify({'error': '관리자 비밀번호가 올바르지 않습니다.'}), 401

    user = query_db("SELECT id, email, name, phone, created_at FROM users WHERE id = %s", (user_id,), one=True)
    if not user:
        return jsonify({'error': '회원을 찾을 수 없습니다.'}), 404

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='CUSTOMER_PII_VIEW',
        target_type='USER',
        target_id=user_id,
        reason=reason,
        result='SUCCESS',
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({
        'message': '원문 조회가 승인되었습니다.',
        'user': user
    }), 200

@admin_bp.route('/customers/<int:user_id>/status', methods=['PATCH', 'POST'])
def admin_update_customer_status(user_id):
    """회원 상태(ACTIVE / SUSPENDED) 변경 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    new_status = data.get('status', '').strip().upper()
    if new_status not in ('ACTIVE', 'SUSPENDED'):
        return jsonify({'error': '올바른 회원 상태(ACTIVE, SUSPENDED)를 지정해 주세요.'}), 400

    execute_db("UPDATE users SET status = %s WHERE id = %s", (new_status, user_id))

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='USER_STATUS_CHANGE',
        target_type='USER',
        target_id=user_id,
        reason=f"Status changed to {new_status}",
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({'message': f'회원 상태가 {new_status}(으)로 성공적으로 변경되었습니다.'}), 200

@admin_bp.route('/customers/<int:user_id>', methods=['PATCH', 'POST', 'PUT'])
def admin_update_customer(user_id):
    """회원 정보(이름, 이메일, 연락처, 계정 상태, 비밀번호) 수정 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    status = data.get('status', 'ACTIVE').strip().upper()
    new_password = data.get('new_password', '').strip()

    if not email:
        return jsonify({'error': '이메일 주소는 필수 입력 항목입니다.'}), 400

    # 이메일 중복 체크 (본인 계정 제외)
    existing = query_db("SELECT id FROM users WHERE email = %s AND id != %s", (email, user_id), one=True)
    if existing:
        return jsonify({'error': '이미 다른 회원이 사용 중인 이메일 주소입니다.'}), 400

    if new_password:
        if len(new_password) < 4:
            return jsonify({'error': '비밀번호는 최소 4자 이상이어야 합니다.'}), 400
        pass_hash = hash_password(new_password)
        execute_db(
            "UPDATE users SET name = %s, email = %s, phone = %s, status = %s, password_hash = %s WHERE id = %s",
            (name, email, phone, status, pass_hash, user_id)
        )
        msg = "회원 정보 및 비밀번호가 성공적으로 변경되었습니다."
    else:
        execute_db(
            "UPDATE users SET name = %s, email = %s, phone = %s, status = %s WHERE id = %s",
            (name, email, phone, status, user_id)
        )
        msg = "회원 정보가 성공적으로 수정되었습니다."

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='USER_INFO_UPDATE',
        target_type='USER',
        target_id=user_id,
        reason=f"Updated member details: name={name}, email={email}, phone={phone}, status={status}, pass_reset={'YES' if new_password else 'NO'}",
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({'message': msg}), 200

@admin_bp.route('/audit-logs', methods=['GET'])
def admin_audit_logs_list():
    """운영 감사로그 검색, 필터링 및 페이지네이션 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    keyword = request.args.get('keyword', '').strip()
    action_type = request.args.get('action_type', '').strip()
    target_type = request.args.get('target_type', '').strip()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        limit = max(1, min(100, int(request.args.get('limit', 15))))
    except (ValueError, TypeError):
        limit = 15

    offset = (page - 1) * limit

    where_clauses = ["1=1"]
    args = []

    if action_type:
        where_clauses.append("action_type = %s")
        args.append(action_type)

    if target_type:
        where_clauses.append("target_type = %s")
        args.append(target_type)

    if keyword:
        where_clauses.append("(admin_email LIKE %s OR action_type LIKE %s OR target_id LIKE %s OR reason LIKE %s)")
        kw_pattern = f"%{keyword}%"
        args.extend([kw_pattern, kw_pattern, kw_pattern, kw_pattern])

    where_str = " WHERE " + " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) as cnt FROM admin_audit_logs {where_str}"
    count_row = query_db(count_sql, tuple(args), one=True)
    total_count = int(count_row['cnt'] or 0) if count_row else 0
    total_pages = max(1, (total_count + limit - 1) // limit)

    select_sql = f"SELECT * FROM admin_audit_logs {where_str} ORDER BY id DESC LIMIT %s OFFSET %s"
    fetch_args = list(args) + [limit, offset]

    logs = query_db(select_sql, tuple(fetch_args)) or []

    formatted_logs = []
    for l in logs:
        formatted_logs.append({
            'id': l['id'],
            'admin_id': l['admin_id'],
            'admin_email': l.get('admin_email', '') or '-',
            'action_type': l.get('action_type', '') or '-',
            'target_type': l.get('target_type', '') or '-',
            'target_id': l.get('target_id', '') or '-',
            'reason': l.get('reason', '') or '-',
            'request_ip': l.get('request_ip', '') or '-',
            'result': l.get('result', 'SUCCESS'),
            'created_at': str(l.get('created_at', ''))
        })

    return jsonify({
        'audit_logs': formatted_logs,
        'pagination': {
            'page': page,
            'limit': limit,
            'total_count': total_count,
            'total_pages': total_pages
        }
    }), 200

def escape_csv_formula(val):
    """Formula Injection 방어 캐릭터 escape (`=, +, -, @, \t, \r, \n, ＝, ＋, －, ＠`)"""
    if val is None:
        return ""
    s = str(val)
    if not s:
        return ""
    
    first_char = s[0]
    dangerous_chars = ('=', '+', '-', '@', '\t', '\r', '\n', '＝', '＋', '－', '＠')
    if first_char in dangerous_chars:
        return f"'{s}"
    return s

@admin_bp.route('/orders/export', methods=['GET'])
def admin_export_orders():
    """택배사 Import용 / 관리자 Excel용 2원화 CSV 다운로드 API (Formula Escape)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    export_type = request.args.get('type', 'excel')
    orders = query_db("SELECT * FROM orders WHERE order_status IN ('CONFIRMED', 'PREPARING') ORDER BY id ASC") or []

    output = io.StringIO()
    writer = csv.writer(output)

    if export_type == 'shipping':
        writer.writerow(['주문번호', '수령인명', '연락처', '우편번호', '주소', '상세주소', '배송메모'])
        for ord in orders:
            writer.writerow([
                ord['order_number'],
                ord['recipient_name'],
                ord['recipient_phone'],
                ord['postal_code'],
                ord['address'],
                ord['address_detail'] or '',
                ord['delivery_memo'] or ''
            ])
    else:
        writer.writerow(['주문번호', '주문일시', '수령인명', '연락처', '우편번호', '주소', '상세주소', '배송메모', '결제금액', '주문상태'])
        for ord in orders:
            writer.writerow([
                escape_csv_formula(ord['order_number']),
                escape_csv_formula(str(ord['created_at'])),
                escape_csv_formula(ord['recipient_name']),
                escape_csv_formula(ord['recipient_phone']),
                escape_csv_formula(ord['postal_code']),
                escape_csv_formula(ord['address']),
                escape_csv_formula(ord['address_detail'] or ''),
                escape_csv_formula(ord['delivery_memo'] or ''),
                escape_csv_formula(ord['total_amount']),
                escape_csv_formula(ord['order_status'])
            ])

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='ORDER_EXPORT',
        target_type='ORDER',
        record_count=len(orders),
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    csv_content = output.getvalue()
    filename = f"order_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        '\ufeff' + csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@admin_bp.route('/products', methods=['GET', 'POST'])
def admin_products():
    """상품 목록 조회 및 신규 등록 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    if request.method == 'GET':
        keyword = request.args.get('keyword', '').strip()
        category_id = request.args.get('category_id', '').strip()
        is_active = request.args.get('is_active', '').strip()

        try:
            page = max(1, int(request.args.get('page', 1)))
        except (ValueError, TypeError):
            page = 1

        try:
            limit = max(1, min(100, int(request.args.get('limit', 10))))
        except (ValueError, TypeError):
            limit = 10

        offset = (page - 1) * limit

        base_sql = "FROM products p JOIN categories c ON p.category_id = c.id"
        where_clauses = ["1=1"]
        args = []

        if category_id and category_id.isdigit():
            where_clauses.append("p.category_id = %s")
            args.append(int(category_id))

        if is_active in ('0', '1'):
            where_clauses.append("p.is_active = %s")
            args.append(int(is_active))

        if keyword:
            where_clauses.append("(p.name LIKE %s OR p.capacity LIKE %s OR p.description LIKE %s)")
            kw_pattern = f"%{keyword}%"
            args.extend([kw_pattern, kw_pattern, kw_pattern])

        where_str = " WHERE " + " AND ".join(where_clauses)

        count_sql = f"SELECT COUNT(*) as cnt {base_sql} {where_str}"
        count_row = query_db(count_sql, tuple(args), one=True)
        total_count = int(count_row['cnt'] or 0) if count_row else 0
        total_pages = max(1, (total_count + limit - 1) // limit)

        select_sql = f"SELECT p.*, c.name as category_name {base_sql} {where_str} ORDER BY p.id DESC LIMIT %s OFFSET %s"
        fetch_args = list(args) + [limit, offset]

        products = query_db(select_sql, tuple(fetch_args)) or []
        for p in products:
            p['options'] = query_db("SELECT * FROM product_options WHERE product_id = %s", (p['id'],)) or []

        return jsonify({
            'products': products,
            'pagination': {
                'page': page,
                'limit': limit,
                'total_count': total_count,
                'total_pages': total_pages
            }
        }), 200


    elif request.method == 'POST':
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        category_id = int(data.get('category_id', 1))
        price = int(data.get('price', 0))
        capacity = data.get('capacity', '').strip()
        description = data.get('description', '').strip()
        badge = data.get('badge', '').strip()
        image_url = data.get('image_url', 'assets/product_sesame.png')
        
        shelf_life_text = data.get('shelf_life_text', '제조일로부터 12개월')
        origin_info = data.get('origin_info', '참깨/들깨: 국산(강원도 영월군 100%)')
        food_type = data.get('food_type', '식용유지류')
        contents_capacity = data.get('contents_capacity', capacity)
        raw_ingredients = data.get('raw_ingredients', '국산 100%')
        manufacturer = data.get('manufacturer', '영월고향방앗간')
        storage_method = data.get('storage_method', '직사광선을 피하고 서늘한 곳 보관')
        allergy_notice = data.get('allergy_notice', '참깨/들깨 함유')
        nutrition_facts = data.get('nutrition_facts', '100ml당 884kcal')

        if not name or price <= 0:
            return jsonify({'error': '상품명과 가격을 올바르게 입력해 주세요.'}), 400

        product_id = execute_db("""
            INSERT INTO products (
                category_id, name, price, capacity, description, badge, image_url,
                shelf_life_text, origin_info, food_type, contents_capacity, raw_ingredients,
                manufacturer, storage_method, allergy_notice, nutrition_facts
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            category_id, name, price, capacity, description, badge, image_url,
            shelf_life_text, origin_info, food_type, contents_capacity, raw_ingredients,
            manufacturer, storage_method, allergy_notice, nutrition_facts
        ))

        options_data = data.get('options', [])
        if options_data:
            for opt in options_data:
                opt_name = str(opt.get('option_name', '기본')).strip() or '기본'
                add_price = int(opt.get('additional_price', 0))
                stock = int(opt.get('stock', 100))
                execute_db("""
                    INSERT INTO product_options (product_id, option_name, additional_price, stock, reserved_stock)
                    VALUES (%s, %s, %s, %s, 0)
                """, (product_id, opt_name, add_price, stock))
        else:
            initial_stock = int(data.get('stock', 100))
            execute_db("""
                INSERT INTO product_options (product_id, option_name, additional_price, stock, reserved_stock)
                VALUES (%s, '300ml (기본)', 0, %s, 0)
            """, (product_id, initial_stock))

        return jsonify({'message': '신규 상품이 성공적으로 등록되었습니다.', 'product_id': product_id}), 201

@admin_bp.route('/products/<int:product_id>', methods=['GET', 'PATCH', 'PUT'])
def admin_update_product(product_id):
    """상품 상세 조회, 기본 정보 및 옵션 재고 통합 수정 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    product = query_db("SELECT * FROM products WHERE id = %s", (product_id,), one=True)
    if not product:
        return jsonify({'error': '상품을 찾을 수 없습니다.'}), 404

    if request.method == 'GET':
        options = query_db("SELECT * FROM product_options WHERE product_id = %s", (product_id,)) or []
        product['options'] = options
        return jsonify({'product': product}), 200

    data = request.get_json() or {}

    # 1. is_active / 기본 정보 수정
    fields = []
    args = []

    if 'name' in data:
        fields.append("name = %s")
        args.append(data['name'].strip())
    if 'category_id' in data:
        fields.append("category_id = %s")
        args.append(int(data['category_id']))
    if 'price' in data:
        fields.append("price = %s")
        args.append(int(data['price']))
    if 'capacity' in data:
        fields.append("capacity = %s")
        args.append(data['capacity'].strip())
    if 'description' in data:
        fields.append("description = %s")
        args.append(data['description'].strip())
    if 'badge' in data:
        fields.append("badge = %s")
        args.append(data['badge'].strip())
    if 'is_active' in data:
        fields.append("is_active = %s")
        args.append(int(data['is_active']))
    if 'food_type' in data:
        fields.append("food_type = %s")
        args.append(data['food_type'].strip())
    if 'manufacturer' in data:
        fields.append("manufacturer = %s")
        args.append(data['manufacturer'].strip())
    if 'shelf_life_text' in data:
        fields.append("shelf_life_text = %s")
        args.append(data['shelf_life_text'].strip())
    if 'contents_capacity' in data:
        fields.append("contents_capacity = %s")
        args.append(data['contents_capacity'].strip())
    if 'origin_info' in data:
        fields.append("origin_info = %s")
        args.append(data['origin_info'].strip())
    if 'storage_method' in data:
        fields.append("storage_method = %s")
        args.append(data['storage_method'].strip())
    if 'allergy_notice' in data:
        fields.append("allergy_notice = %s")
        args.append(data['allergy_notice'].strip())
    if 'cs_phone' in data:
        fields.append("cs_phone = %s")
        args.append(data['cs_phone'].strip())

    if fields:
        args.append(product_id)
        sql = f"UPDATE products SET {', '.join(fields)} WHERE id = %s"
        execute_db(sql, tuple(args))
    # 2. 옵션 등록 / 수정 / 삭제 통합 처리
    if 'options' in data:
        options_data = data.get('options', [])
        existing_opts = query_db("SELECT id FROM product_options WHERE product_id = %s", (product_id,)) or []
        existing_ids = {o['id'] for o in existing_opts}
        keep_ids = set()

        for opt in options_data:
            opt_id = opt.get('id')
            stock = int(opt.get('stock', 100))
            add_price = int(opt.get('additional_price', 0))
            opt_name = str(opt.get('option_name', '기본')).strip() or '기본'

            if opt_id and opt_id in existing_ids:
                keep_ids.add(opt_id)
                execute_db("""
                    UPDATE product_options 
                    SET option_name = %s, additional_price = %s, stock = %s 
                    WHERE id = %s AND product_id = %s
                """, (opt_name, add_price, stock, opt_id, product_id))
            else:
                execute_db("""
                    INSERT INTO product_options (product_id, option_name, additional_price, stock, reserved_stock)
                    VALUES (%s, %s, %s, %s, 0)
                """, (product_id, opt_name, add_price, stock))

        delete_ids = existing_ids - keep_ids
        for del_id in delete_ids:
            execute_db("DELETE FROM product_options WHERE id = %s AND product_id = %s", (del_id, product_id))

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='UPDATE_PRODUCT_STOCK',
        target_type='PRODUCT',
        target_id=product_id,
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({'message': '상품 및 재고 정보가 성공적으로 변경되었습니다.'}), 200

@admin_bp.route('/options/<int:option_id>/stock', methods=['PATCH'])
def admin_update_option_stock(option_id):
    """옵션 재고(stock) 단건 즉시 변경 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    new_stock = data.get('stock')

    if new_stock is None or int(new_stock) < 0:
        return jsonify({'error': '올바른 재고 수량을 입력해 주세요.'}), 400

    opt = query_db("SELECT * FROM product_options WHERE id = %s", (option_id,), one=True)
    if not opt:
        return jsonify({'error': '상품 옵션을 찾을 수 없습니다.'}), 404

    execute_db("UPDATE product_options SET stock = %s WHERE id = %s", (int(new_stock), option_id))

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload['sub'],
        action_type='UPDATE_OPTION_STOCK',
        target_type='OPTION',
        target_id=option_id,
        reason=f"stock: {opt['stock']} -> {new_stock}",
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({
        'message': f"옵션({opt['option_name']}) 재고가 {new_stock}개로 성공적으로 변경되었습니다.",
        'option_id': option_id,
        'stock': int(new_stock)
    }), 200
