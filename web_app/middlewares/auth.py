import datetime
import uuid
from functools import wraps
from flask import request, jsonify
import jwt
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from db.db_connection import query_db

def hash_password(password):
    """비밀번호 단방향 암호화 (Werkzeug/pbkdf2:sha256)"""
    return generate_password_hash(password)

def check_password(password, password_hash):
    """비밀번호 검증"""
    return check_password_hash(password_hash, password)

def validate_password_policy(password):
    """
    공통 비밀번호 검증 함수 (OWASP/NIST 권고 참고 서비스 정책):
    - 최소 10자 이상, 최대 128자 이하
    - 공백 및 특수문자 전면 허용
    """
    if not password or not isinstance(password, str):
        return False, "비밀번호를 입력해 주세요."
    if len(password) < 10:
        return False, "비밀번호는 최소 10자 이상이어야 합니다."
    if len(password) > 128:
        return False, "비밀번호는 최대 128자 이하이어야 합니다."
    return True, ""

def generate_jwt_token(user_id, email, role='USER', token_version=0):
    """JWT 토큰 생성 (jti, role 및 token_version 포함)"""
    jti = str(uuid.uuid4())
    payload = {
        'user_id': user_id,
        'email': email,
        'role': role,
        'jti': jti,
        'token_version': token_version,
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=Config.JWT_EXPIRATION_HOURS),
        'iat': datetime.datetime.now(datetime.timezone.utc)
    }
    token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm='HS256')
    return token

def verify_jwt_token(token):
    """JWT 토큰 검증 (jti Blacklist, DB status == 'ACTIVE', token_version 실시간 비교)"""
    try:
        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
        jti = payload.get('jti')
        if jti:
            revoked = query_db("SELECT * FROM revoked_access_tokens WHERE jti = %s", (jti,), one=True)
            if revoked:
                return None
        
        # 일반 회원 유저인 경우 status='ACTIVE' 및 token_version 실시간 이중 검증
        user_id = payload.get('user_id')
        if user_id and payload.get('role') not in ('ADMIN', 'SUPER_ADMIN'):
            db_user = query_db("SELECT status, token_version FROM users WHERE id = %s", (user_id,), one=True)
            if not db_user:
                return None
            if db_user.get('status') != 'ACTIVE':
                return None
            if db_user.get('token_version', 0) != payload.get('token_version', 0):
                return None
                
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

def jwt_required(f):
    """보안 JWT 검증 데코레이터"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': '인증 헤더가 필요합니다.'}), 401
        
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return jsonify({'error': '유효하지 않은 인증 형식입니다.'}), 401
        
        token = parts[1]
        payload = verify_jwt_token(token)
        if not payload:
            return jsonify({'error': '만료되거나 유효하지 않은 JWT 토큰입니다.'}), 401
        
        request.current_user = payload
        return f(*args, **kwargs)
    return decorated_function
