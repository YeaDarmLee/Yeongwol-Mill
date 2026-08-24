import pytest
import json
from app import app
from db.init_db import init_database
from db.db_connection import query_db, execute_db
from middlewares.auth import generate_jwt_token, hash_password

@pytest.fixture(autouse=True)
def setup_test_db():
    from app import REQUEST_LOGS
    REQUEST_LOGS.clear()
    init_database()
    execute_db("DELETE FROM user_consents")
    execute_db("DELETE FROM notification_outbox")
    execute_db("DELETE FROM users WHERE email LIKE %s OR email LIKE %s", ('%@example.com', '%@deleted.invalid'))
    yield

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def create_sample_user(email="testuser@example.com", password="Password1234!", name="홍길동", phone="01012345678", token_version=0):
    pwd_hash = hash_password(password)
    execute_db("""
        INSERT INTO users (email, password_hash, name, phone, token_version, marketing_email_agreed, marketing_sms_agreed, status)
        VALUES (%s, %s, %s, %s, %s, 1, 0, 'ACTIVE')
    """, (email, pwd_hash, name, phone, token_version))
    user = query_db("SELECT * FROM users WHERE email = %s", (email,), one=True)
    return user

def test_get_profile_success_and_unauthorized(client):
    user = create_sample_user()
    token = generate_jwt_token(user['id'], user['email'], token_version=0)

    # 1. 정상 조회
    resp = client.get('/api/users/me', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['user']['email'] == "testuser@example.com"
    assert data['user']['name'] == "홍길동"

    # 2. 토큰 없음 -> 401
    resp_no_token = client.get('/api/users/me')
    assert resp_no_token.status_code == 401

def test_update_profile_success(client):
    user = create_sample_user()
    token = generate_jwt_token(user['id'], user['email'], token_version=0)

    patch_data = {
        'name': '홍길동',
        'phone': '010-9876-5432'
    }
    resp = client.patch('/api/users/me/profile', 
                        headers={'Authorization': f'Bearer {token}'},
                        data=json.dumps(patch_data),
                        content_type='application/json')
    assert resp.status_code == 200
    
    # DB 정규화 확인 (숫자만 저장)
    db_user = query_db("SELECT name, phone FROM users WHERE id = %s", (user['id'],), one=True)
    assert db_user['name'] == '홍길동'
    assert db_user['phone'] == '01098765432'

def test_change_password_and_token_version_invalidation(client):
    user = create_sample_user(password="OldPassword123!")
    old_token = generate_jwt_token(user['id'], user['email'], token_version=0)

    # 1. 비밀번호 10자 미만 변경 실패
    resp_short = client.put('/api/users/me/password',
                            headers={'Authorization': f'Bearer {old_token}'},
                            data=json.dumps({
                                'current_password': 'OldPassword123!',
                                'new_password': 'short',
                                'new_password_confirm': 'short'
                            }),
                            content_type='application/json')
    assert resp_short.status_code == 400

    # 2. 정상 비밀번호 변경 (10자 이상)
    resp_ok = client.put('/api/users/me/password',
                         headers={'Authorization': f'Bearer {old_token}'},
                         data=json.dumps({
                             'current_password': 'OldPassword123!',
                             'new_password': 'NewPassword12345!',
                             'new_password_confirm': 'NewPassword12345!'
                         }),
                         content_type='application/json')
    assert resp_ok.status_code == 200

    # 3. 비밀번호 변경 후 기존 old_token 사용 시 token_version 불일치로 401 차단!
    resp_invalid = client.get('/api/users/me', headers={'Authorization': f'Bearer {old_token}'})
    assert resp_invalid.status_code == 401

def test_marketing_consents_outbox_and_history(client):
    user = create_sample_user()
    token = generate_jwt_token(user['id'], user['email'], token_version=0)

    # 이메일 수신 거부(false), SMS 수신 동의(true) 변경
    resp = client.patch('/api/users/me/marketing-consents',
                        headers={'Authorization': f'Bearer {token}'},
                        data=json.dumps({
                            'marketing_email': False,
                            'marketing_sms': True
                        }),
                        content_type='application/json')
    assert resp.status_code == 200

    # 1. users 스냅샷 확인
    db_user = query_db("SELECT marketing_email_agreed, marketing_sms_agreed FROM users WHERE id = %s", (user['id'],), one=True)
    assert db_user['marketing_email_agreed'] == 0
    assert db_user['marketing_sms_agreed'] == 1

    # 2. user_consents 이력 레코드 생성 확인
    consents = query_db("SELECT * FROM user_consents WHERE user_id = %s", (user['id'],))
    assert len(consents) >= 2

    # 3. notification_outbox 레코드 생성 확인
    outbox = query_db("SELECT * FROM notification_outbox WHERE user_id = %s", (user['id'],))
    assert len(outbox) >= 2

def test_withdraw_account_and_deidentification(client):
    user = create_sample_user(password="Password1234!")
    token = generate_jwt_token(user['id'], user['email'], token_version=0)

    # 회원 탈퇴 실행
    resp = client.post('/api/users/me/withdraw',
                       headers={'Authorization': f'Bearer {token}'},
                       data=json.dumps({'current_password': 'Password1234!'}),
                       content_type='application/json')
    assert resp.status_code == 200

    # 1. DB 비식별 시스템 대체값 확인 및 개인정보 파기 확인
    db_user = query_db("SELECT status, email, name, phone, password_hash FROM users WHERE id = %s", (user['id'],), one=True)
    assert db_user['status'] == 'WITHDRAWN'
    assert '@deleted.invalid' in db_user['email']
    assert db_user['name'] is None
    assert db_user['phone'] is None
    assert db_user['password_hash'] is None

    # 2. 탈퇴 후 기존 토큰 요청 시 401 차단!
    resp_blocked = client.get('/api/users/me', headers={'Authorization': f'Bearer {token}'})
    assert resp_blocked.status_code == 401
