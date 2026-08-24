from flask import Blueprint, request, jsonify
from db.db_connection import query_db, execute_db
from middlewares.auth import hash_password, check_password, generate_jwt_token, jwt_required

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@auth_bp.route('/register', methods=['POST'])
def register():
    """회원가입 API"""
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()

    if not email or not password or not name or not phone:
        return jsonify({'error': '모든 필수 입력항목(이메일, 비밀번호, 이름, 연락처)을 입력해 주세요.'}), 400

    # 이메일 중복 확인
    existing_user = query_db("SELECT id FROM users WHERE email = %s", (email,), one=True)
    if existing_user:
        return jsonify({'error': '이미 등록된 이메일 주소입니다.'}), 400

    password_hash = hash_password(password)
    user_id = execute_db(
        "INSERT INTO users (email, password_hash, name, phone) VALUES (%s, %s, %s, %s)",
        (email, password_hash, name, phone)
    )

    token = generate_jwt_token(user_id, email)
    return jsonify({
        'message': '회원가입이 성공적으로 완료되었습니다.',
        'token': token,
        'user': {'id': user_id, 'email': email, 'name': name, 'phone': phone}
    }), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    """JWT 기반 보안 로그인 API"""
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({'error': '이메일과 비밀번호를 입력해 주세요.'}), 400

    user = query_db("SELECT * FROM users WHERE email = %s", (email,), one=True)
    if not user or not check_password(password, user['password_hash']):
        return jsonify({'error': '이메일 또는 비밀번호가 올바르지 않습니다.'}), 401

    token = generate_jwt_token(user['id'], user['email'])
    return jsonify({
        'message': '로그인 성공',
        'token': token,
        'user': {
            'id': user['id'],
            'email': user['email'],
            'name': user['name'],
            'phone': user['phone']
        }
    }), 200

@auth_bp.route('/me', methods=['GET'])
@jwt_required
def get_me():
    """내 정보 조회 API"""
    user_id = request.current_user['user_id']
    user = query_db("SELECT id, email, name, phone, created_at FROM users WHERE id = %s", (user_id,), one=True)
    if not user:
        return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 440
    
    return jsonify({'user': user}), 200
