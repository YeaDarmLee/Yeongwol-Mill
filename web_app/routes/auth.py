import datetime
import secrets
import hashlib
import uuid
import jwt
from flask import Blueprint, request, jsonify
from config import Config
from db.db_connection import query_db, execute_db
from middlewares.auth import hash_password, check_password, generate_jwt_token, verify_jwt_token, jwt_required

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

RESET_TOKENS = {}

def create_refresh_token(user_id):
    """Refresh Token 생성 및 DB 저장 (7일 유효)"""
    token_str = secrets.token_urlsafe(64)
    token_hash = hashlib.sha256(token_str.encode('utf-8')).hexdigest()
    expires_at = (datetime.datetime.now() + datetime.timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    
    execute_db("""
        INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
        VALUES (%s, %s, %s)
    """, (user_id, token_hash, expires_at))
    return token_str

@auth_bp.route('/register', methods=['POST'])
def register():
    """회원가입 API (약관 동의 검증)"""
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()
    terms_agreed = data.get('terms_agreed', False)
    privacy_agreed = data.get('privacy_agreed', False)

    if not email or not password or not name or not phone:
        return jsonify({'error': '모든 필수 입력항목(이메일, 비밀번호, 이름, 연락처)을 입력해 주세요.'}), 400

    if not terms_agreed or not privacy_agreed:
        return jsonify({'error': '이용약관 및 개인정보 처리방침에 모두 동의해 주세요.'}), 400

    existing_user = query_db("SELECT id FROM users WHERE email = %s", (email,), one=True)
    if existing_user:
        return jsonify({'error': '이미 등록된 이메일 주소입니다.'}), 400

    password_hash = hash_password(password)
    user_id = execute_db(
        "INSERT INTO users (email, password_hash, name, phone) VALUES (%s, %s, %s, %s)",
        (email, password_hash, name, phone)
    )

    token = generate_jwt_token(user_id, email)
    refresh_token = create_refresh_token(user_id)
    return jsonify({
        'message': '영월고향방앗간 회원가입이 성공적으로 완료되었습니다.',
        'token': token,
        'refresh_token': refresh_token,
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
    refresh_token = create_refresh_token(user['id'])
    return jsonify({
        'message': '로그인 성공',
        'token': token,
        'refresh_token': refresh_token,
        'user': {
            'id': user['id'],
            'email': user['email'],
            'name': user['name'],
            'phone': user['phone']
        }
    }), 200

@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    """Refresh Token Rotation 기반 Access Token 재발급 API"""
    data = request.get_json() or {}
    refresh_token = data.get('refresh_token', '').strip()

    if not refresh_token:
        return jsonify({'error': 'Refresh Token이 필요합니다.'}), 400

    token_hash = hashlib.sha256(refresh_token.encode('utf-8')).hexdigest()
    record = query_db("SELECT * FROM refresh_tokens WHERE token_hash = %s AND revoked_at IS NULL", (token_hash,), one=True)

    if not record:
        return jsonify({'error': '유효하지 않거나 취소된 Refresh Token입니다.'}), 401

    # 만료 검증
    exp_dt = datetime.datetime.strptime(str(record['expires_at']).split('.')[0], '%Y-%m-%d %H:%M:%S')
    if exp_dt < datetime.datetime.now():
        return jsonify({'error': '만료된 Refresh Token입니다. 다시 로그인해 주세요.'}), 401

    # 기존 Refresh Token 취소 (Rotation)
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    execute_db("UPDATE refresh_tokens SET revoked_at = %s WHERE id = %s", (now_str, record['id']))

    user = query_db("SELECT * FROM users WHERE id = %s", (record['user_id'],), one=True)
    if not user:
        return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 404

    new_access_token = generate_jwt_token(user['id'], user['email'])
    new_refresh_token = create_refresh_token(user['id'])

    return jsonify({
        'token': new_access_token,
        'refresh_token': new_refresh_token
    }), 200

@auth_bp.route('/logout', methods=['POST'])
@jwt_required
def logout():
    """로그아웃 API (Access Token jti Blacklist 차단 & Refresh Token Revoke)"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split()[1]
        try:
            payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
            jti = payload.get('jti')
            exp = payload.get('exp')
            if jti and exp:
                exp_dt = datetime.datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M:%S')
                execute_db("""
                    INSERT IGNORE INTO revoked_access_tokens (jti, expires_at)
                    VALUES (%s, %s)
                """, (jti, exp_dt))
        except Exception:
            pass

    user_id = request.current_user.get('user_id')
    if user_id:
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        execute_db("UPDATE refresh_tokens SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL", (now_str, user_id))

    return jsonify({'message': '성공적으로 로그아웃되었습니다.'}), 200

@auth_bp.route('/me', methods=['GET'])
@jwt_required
def get_me():
    """내 정보 조회 API"""
    user_id = request.current_user['user_id']
    user = query_db("SELECT id, email, name, phone, created_at FROM users WHERE id = %s", (user_id,), one=True)
    if not user:
        return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 404
    
    return jsonify({'user': user}), 200

@auth_bp.route('/reset-password-request', methods=['POST'])
def reset_password_request():
    """비밀번호 재설정 요청 (토큰 발급) API"""
    data = request.get_json() or {}
    email = data.get('email', '').strip()

    if not email:
        return jsonify({'error': '이메일 주소를 입력해 주세요.'}), 400

    user = query_db("SELECT * FROM users WHERE email = %s", (email,), one=True)
    if not user:
        return jsonify({'message': '비밀번호 재설정 요청이 접수되었습니다. (등록된 이메일인 경우 안내 발송)'}), 200

    token = secrets.token_urlsafe(32)
    RESET_TOKENS[token] = {
        'user_id': user['id'],
        'email': user['email'],
        'expires_at': datetime.datetime.now() + datetime.timedelta(minutes=30)
    }

    return jsonify({
        'message': '비밀번호 재설정 토큰이 성공적으로 발급되었습니다.',
        'reset_token': token
    }), 200

@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """비밀번호 재설정 실행 API"""
    data = request.get_json() or {}
    token = data.get('reset_token', '').strip()
    new_password = data.get('new_password', '').strip()

    if not token or not new_password:
        return jsonify({'error': '재설정 토큰과 새 비밀번호를 모두 입력해 주세요.'}), 400

    info = RESET_TOKENS.get(token)
    if not info or info['expires_at'] < datetime.datetime.now():
        return jsonify({'error': '만료되거나 유효하지 않은 비밀번호 재설정 토큰입니다.'}), 400

    new_hash = hash_password(new_password)
    execute_db("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, info['user_id']))
    RESET_TOKENS.pop(token, None)

    return jsonify({'message': '비밀번호가 성공적으로 재설정되었습니다. 새 비밀번호로 로그인해 주세요.'}), 200
