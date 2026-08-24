import datetime
from functools import wraps
from flask import request, jsonify
import jwt
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

def hash_password(password):
    """비밀번호 단방향 암호화 (Werkzeug/pbkdf2:sha256/bcrypt)"""
    return generate_password_hash(password)

def check_password(password, password_hash):
    """비밀번호 검증"""
    return check_password_hash(password_hash, password)

def generate_jwt_token(user_id, email):
    """JWT 토큰 생성"""
    payload = {
        'user_id': user_id,
        'email': email,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=Config.JWT_EXPIRATION_HOURS),
        'iat': datetime.datetime.utcnow()
    }
    token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm='HS256')
    return token

def verify_jwt_token(token):
    """JWT 토큰 검증"""
    try:
        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
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
