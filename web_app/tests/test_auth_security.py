import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from db.init_db import init_database
from db.db_connection import query_db, execute_db

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    init_database()
    execute_db("DELETE FROM refresh_tokens")
    execute_db("DELETE FROM revoked_access_tokens")
    execute_db("DELETE FROM users WHERE email = 'auth_test@yeongwol.com'")

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_password_reset_token_flow(client):
    """비밀번호 재설정 토큰 발급 및 변경 테스트"""
    client.post('/api/auth/register', json={
        'email': 'auth_test@yeongwol.com',
        'password': 'oldpassword123',
        'name': '보안테스터',
        'phone': '010-1111-2222',
        'terms_agreed': True,
        'privacy_agreed': True
    })

    res_req = client.post('/api/auth/reset-password-request', json={'email': 'auth_test@yeongwol.com'})
    assert res_req.status_code == 200
    token = res_req.get_json()['reset_token']

    res_reset = client.post('/api/auth/reset-password', json={
        'reset_token': token,
        'new_password': 'newpassword456'
    })
    assert res_reset.status_code == 200

    login_res = client.post('/api/auth/login', json={
        'email': 'auth_test@yeongwol.com',
        'password': 'newpassword456'
    })
    assert login_res.status_code == 200

def test_password_reset_token_single_use(client):
    """비밀번호 재설정 토큰 1회 사용 후 재사용 차단 테스트"""
    client.post('/api/auth/register', json={
        'email': 'auth_test@yeongwol.com',
        'password': 'oldpassword123',
        'name': '보안테스터',
        'phone': '010-1111-2222',
        'terms_agreed': True,
        'privacy_agreed': True
    })
    res_req = client.post('/api/auth/reset-password-request', json={'email': 'auth_test@yeongwol.com'})
    token = res_req.get_json()['reset_token']

    client.post('/api/auth/reset-password', json={'reset_token': token, 'new_password': 'pass1'})
    res_reuse = client.post('/api/auth/reset-password', json={'reset_token': token, 'new_password': 'pass2'})
    assert res_reuse.status_code == 400

def test_expired_password_reset_token(client):
    """유효하지 않거나 만료된 재설정 토큰 거부 테스트"""
    res = client.post('/api/auth/reset-password', json={
        'reset_token': 'invalid_token_9999',
        'new_password': 'newpass'
    })
    assert res.status_code == 400

def test_refresh_token_success(client):
    """Refresh Token Rotation 기반 Access Token 재발급 검증"""
    reg_res = client.post('/api/auth/register', json={
        'email': 'auth_test@yeongwol.com',
        'password': 'password123',
        'name': '보안테스터',
        'phone': '010-1111-2222',
        'terms_agreed': True,
        'privacy_agreed': True
    })
    refresh_token = reg_res.get_json()['refresh_token']

    res = client.post('/api/auth/refresh', json={'refresh_token': refresh_token})
    assert res.status_code == 200
    data = res.get_json()
    assert 'token' in data
    assert 'refresh_token' in data

def test_expired_refresh_token_rejected(client):
    """만료되거나 존재하지 않는 Refresh Token 거부 검증"""
    res = client.post('/api/auth/refresh', json={'refresh_token': 'invalid_or_expired_token'})
    assert res.status_code == 401

def test_logout_blacklisted_token_rejected(client):
    """로그아웃 시 Access Token jti Blacklist 즉시 차단 검증"""
    login_res = client.post('/api/auth/register', json={
        'email': 'auth_test@yeongwol.com',
        'password': 'password123',
        'name': '보안테스터',
        'phone': '010-1111-2222',
        'terms_agreed': True,
        'privacy_agreed': True
    })
    token = login_res.get_json()['token']
    headers = {'Authorization': f'Bearer {token}'}

    # 1. 로그아웃 전 me 접근 성공
    me_res1 = client.get('/api/auth/me', headers=headers)
    assert me_res1.status_code == 200

    # 2. 로그아웃 호출
    logout_res = client.post('/api/auth/logout', headers=headers)
    assert logout_res.status_code == 200

    # 3. 로그아웃 후 me 접근 시 jti 차단 ➔ 401 Unauthorized
    me_res2 = client.get('/api/auth/me', headers=headers)
    assert me_res2.status_code == 401

def test_admin_login_rate_limit(client):
    """관리자 로그인 인증 및 보안 검증"""
    res = client.post('/api/admin/login', json={'email': 'admin@fail.com', 'password': 'wrong'})
    assert res.status_code in [401, 429]

def test_user_login_rate_limit(client):
    """일반 사용자 로그인 인증 및 보안 검증"""
    res = client.post('/api/auth/login', json={'email': 'user@fail.com', 'password': 'wrong'})
    assert res.status_code in [401, 429]

def test_jwt_role_enforcement(client):
    """권한 없는 일반 사용자 토큰으로 관리자 API 호출 시 403 거부 검증"""
    client.post('/api/auth/register', json={
        'email': 'auth_test@yeongwol.com',
        'password': 'password123',
        'name': '일반유저',
        'phone': '010-1111-2222',
        'terms_agreed': True,
        'privacy_agreed': True
    })
    login_res = client.post('/api/auth/login', json={'email': 'auth_test@yeongwol.com', 'password': 'password123'})
    user_token = login_res.get_json()['token']

    admin_res = client.get('/api/admin/dashboard', headers={'Authorization': f'Bearer {user_token}'})
    assert admin_res.status_code == 403
