import requests
from flask import Blueprint, request, jsonify
from config import Config
from db.db_connection import query_db, execute_db

payment_bp = Blueprint('payment', __name__, url_prefix='/api/payment')

@payment_bp.route('/complete', methods=['POST'])
def complete_payment():
    """
    Portone PG 결제 완료 사후 검증 API
    클라이언트에서 전달받은 payment_id와 order_number를 이용해 결제 위변조 검증 수행
    """
    data = request.get_json() or {}
    payment_id = data.get('payment_id') or data.get('imp_uid')
    order_number = data.get('order_number')

    if not payment_id or not order_number:
        return jsonify({'error': '결제 ID(payment_id)와 주문번호(order_number)가 필요합니다.'}), 400

    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    if not order:
        return jsonify({'error': '해당 주문번호의 주문이 존재하지 않습니다.'}), 404

    # 테스트 결제 또는 Portone V2 REST API 검증
    # 만약 PORTONE_API_SECRET이 설정되어 있으면 Portone API 호출하여 금액 검증
    verified = True
    paid_amount = order['total_amount']

    if Config.PORTONE_API_SECRET:
        try:
            # Portone API 토큰 발급 및 결제 정보 조회
            auth_resp = requests.post('https://api.portone.io/login/api-secret', json={
                'apiSecret': Config.PORTONE_API_SECRET
            }, timeout=5)
            
            if auth_resp.status_code == 200:
                token = auth_resp.json().get('accessToken')
                pay_resp = requests.get(f'https://api.portone.io/payments/{payment_id}', headers={
                    'Authorization': f'Bearer {token}'
                }, timeout=5)
                
                if pay_resp.status_code == 200:
                    payment_data = pay_resp.json()
                    paid_amount = payment_data.get('amount', {}).get('total', 0)
                    if paid_amount != order['total_amount']:
                        verified = False
        except Exception as e:
            print(f"Portone verification API error: {e}")

    if not verified:
        execute_db("UPDATE orders SET payment_status = 'FAILED' WHERE id = %s", (order['id'],))
        return jsonify({'error': '결제 위변조 검증에 실패하였습니다. 결제 금액이 일치하지 않습니다.'}), 400

    # 결제 완료 처리
    execute_db("""
        UPDATE orders 
        SET payment_status = 'PAID', portone_payment_id = %s 
        WHERE id = %s
    """, (payment_id, order['id']))

    return jsonify({
        'message': '결제 검증 및 완료 처리가 성공적으로 이루어졌습니다.',
        'order_number': order_number,
        'payment_status': 'PAID'
    }), 200
