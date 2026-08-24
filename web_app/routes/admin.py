import io
import csv
import datetime
from flask import Blueprint, request, jsonify, Response
from db.db_connection import query_db, execute_db
from middlewares.auth import verify_jwt_token, generate_jwt_token, check_password

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

def verify_admin_auth():
    """관리자 권한 검증 미들웨어 헬퍼"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split()[1]
    payload = verify_jwt_token(token)
    if not payload or payload.get('role') != 'ADMIN':
        return None
    return payload

@admin_bp.route('/login', methods=['POST'])
def admin_login():
    """관리자 전용 보안 로그인 API"""
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({'error': '관리자 이메일과 비밀번호를 모두 입력해 주세요.'}), 400

    admin = query_db("SELECT * FROM admin_users WHERE email = %s", (email,), one=True)
    if not admin or not check_password(password, admin['password_hash']):
        return jsonify({'error': '관리자 이메일 또는 비밀번호가 올바르지 않습니다.'}), 401

    token = generate_jwt_token(admin['id'], admin['email'], role='ADMIN')
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
    """관리자 매출 및 대시보드 요약 통계 API"""
    if not verify_admin_auth():
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    month_str = datetime.datetime.now().strftime('%Y-%m')

    today_sales_row = query_db("""
        SELECT SUM(total_amount) as today_sales, COUNT(*) as today_count 
        FROM orders 
        WHERE payment_status = 'PAID' AND DATE(created_at) = %s
    """, (today_str,), one=True)

    month_sales_row = query_db("""
        SELECT SUM(total_amount) as month_sales, COUNT(*) as month_count 
        FROM orders 
        WHERE payment_status = 'PAID' AND DATE_FORMAT(created_at, '%%Y-%%m') = %s
    """, (month_str,), one=True)

    pending_shipping_row = query_db("""
        SELECT COUNT(*) as count FROM orders WHERE order_status IN ('CONFIRMED', 'PREPARING')
    """, one=True)

    low_stock_options = query_db("""
        SELECT po.*, p.name as product_name 
        FROM product_options po 
        JOIN products p ON po.product_id = p.id 
        WHERE (po.stock - po.reserved_stock) <= 10
    """) or []

    return jsonify({
        'today_sales': int(today_sales_row['today_sales'] or 0) if today_sales_row else 0,
        'today_orders': int(today_sales_row['today_count'] or 0) if today_sales_row else 0,
        'month_sales': int(month_sales_row['month_sales'] or 0) if month_sales_row else 0,
        'month_orders': int(month_sales_row['month_count'] or 0) if month_sales_row else 0,
        'pending_shipping_count': int(pending_shipping_row['count'] or 0) if pending_shipping_row else 0,
        'low_stock_options': low_stock_options
    }), 200

@admin_bp.route('/products', methods=['GET', 'POST'])
def admin_products():
    """상품 목록 조회 및 신규 등록 API"""
    if not verify_admin_auth():
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    if request.method == 'GET':
        products = query_db("SELECT p.*, c.name as category_name FROM products p JOIN categories c ON p.category_id = c.id ORDER BY p.id DESC") or []
        for p in products:
            p['options'] = query_db("SELECT * FROM product_options WHERE product_id = %s", (p['id'],)) or []
        return jsonify({'products': products}), 200

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

        # 기본 옵션 자동 생성
        initial_stock = int(data.get('stock', 100))
        execute_db("""
            INSERT INTO product_options (product_id, option_name, additional_price, stock, reserved_stock)
            VALUES (%s, '기본 (DEFAULT)', 0, %s, 0)
        """, (product_id, initial_stock))

        return jsonify({'message': '신규 상품이 성공적으로 등록되었습니다.', 'product_id': product_id}), 201

@admin_bp.route('/orders', methods=['GET'])
def admin_orders():
    """전체 주문 목록 필터링 및 검색 API"""
    if not verify_admin_auth():
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    status_filter = request.args.get('order_status', '')
    payment_filter = request.args.get('payment_status', '')
    keyword = request.args.get('keyword', '').strip()

    sql = "SELECT * FROM orders WHERE 1=1"
    args = []

    if status_filter:
        sql += " AND order_status = %s"
        args.append(status_filter)
    if payment_filter:
        sql += " AND payment_status = %s"
        args.append(payment_filter)
    if keyword:
        sql += " AND (order_number LIKE %s OR recipient_name LIKE %s OR recipient_phone LIKE %s)"
        kw_pattern = f"%{keyword}%"
        args.extend([kw_pattern, kw_pattern, kw_pattern])

    sql += " ORDER BY id DESC LIMIT 100"
    orders = query_db(sql, tuple(args)) or []

    for order in orders:
        order['items'] = query_db("SELECT * FROM order_items WHERE order_id = %s", (order['id'],)) or []

    return jsonify({'orders': orders}), 200

@admin_bp.route('/orders/<int:order_id>/shipping', methods=['POST'])
def admin_update_shipping(order_id):
    """택배 운송장 번호 및 택배사 등록 (배송중 상태 변경) API"""
    if not verify_admin_auth():
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    courier_name = data.get('courier_name', '').strip()
    tracking_number = data.get('tracking_number', '').strip()

    if not courier_name or not tracking_number:
        return jsonify({'error': '택배사명과 운송장 번호를 모두 입력해 주세요.'}), 400

    order = query_db("SELECT * FROM orders WHERE id = %s", (order_id,), one=True)
    if not order:
        return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    execute_db("""
        UPDATE orders 
        SET courier_name = %s, tracking_number = %s, order_status = 'SHIPPING', shipped_at = %s
        WHERE id = %s
    """, (courier_name, tracking_number, now_str, order_id))

    return jsonify({
        'message': f"운송장 번호({courier_name} {tracking_number})가 성공적으로 등록되었으며 배송중 상태로 전환되었습니다.",
        'order_id': order_id,
        'order_status': 'SHIPPING'
    }), 200

@admin_bp.route('/orders/export', methods=['GET'])
def admin_export_orders():
    """택배사 발송용 주문 내역 CSV 다운로드 API"""
    if not verify_admin_auth():
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    orders = query_db("SELECT * FROM orders WHERE order_status IN ('CONFIRMED', 'PREPARING') ORDER BY id ASC") or []

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['주문번호', '주문일시', '수령인명', '연락처', '우편번호', '주소', '상세주소', '배송메모', '결제금액', '주문상태'])

    for ord in orders:
        writer.writerow([
            ord['order_number'],
            ord['created_at'],
            ord['recipient_name'],
            ord['recipient_phone'],
            ord['postal_code'],
            ord['address'],
            ord['address_detail'],
            ord['delivery_memo'],
            ord['total_amount'],
            ord['order_status']
        ])

    csv_data = "\ufeff" + output.getvalue() # UTF-8 BOM 추가 (엑셀 한글 깨짐 방지)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=yeongwol_orders_{datetime.datetime.now().strftime('%Y%m%d')}.csv"}
    )
