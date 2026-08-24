import json
import logging
from db.db_connection import execute_db

logger = logging.getLogger(__name__)

# PII 및 민감 데이터 필터링 키
BLOCKED_KEYS = {
    'password', 'password_hash', 'guest_password_hash', 'token', 'jwt',
    'refresh_token', 'secret', 'api_secret', 'mfa_secret',
    'recipient_name', 'recipient_phone', 'address', 'address_detail',
    'guest_name', 'guest_phone', 'name', 'phone', 'email'
}

def sanitize_data_for_audit(data):
    """감사로그에 PII 원문 및 Secret 저장을 엄격히 금지하는 필터링 유틸리티"""
    if not isinstance(data, dict):
        return data
    
    clean_dict = {}
    for k, v in data.items():
        k_lower = str(k).lower()
        if k_lower in BLOCKED_KEYS:
            clean_dict[k] = "[REDACTED_PII]"
        elif isinstance(v, dict):
            clean_dict[k] = sanitize_data_for_audit(v)
        elif isinstance(v, list):
            clean_dict[k] = [sanitize_data_for_audit(item) if isinstance(item, dict) else item for item in v]
        else:
            clean_dict[k] = v
    return clean_dict

def log_admin_audit(admin_id, admin_email, action_type, target_type=None, target_id=None,
                    request_id=None, before_data=None, after_data=None, reason=None,
                    result="SUCCESS", record_count=0, request_ip="127.0.0.1", user_agent=None):
    """관리자 운영 감사로그 기록 (admin_audit_logs)"""
    try:
        clean_before = sanitize_data_for_audit(before_data) if before_data else None
        clean_after = sanitize_data_for_audit(after_data) if after_data else None
        
        before_json = json.dumps(clean_before, ensure_ascii=False) if clean_before else None
        after_json = json.dumps(clean_after, ensure_ascii=False) if clean_after else None

        execute_db("""
            INSERT INTO admin_audit_logs (
                admin_id, admin_email, action_type, target_type, target_id,
                request_id, before_data, after_data, reason, result,
                record_count, request_ip, user_agent
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            admin_id, admin_email, action_type, target_type, str(target_id) if target_id else None,
            request_id, before_json, after_json, reason, result,
            record_count, request_ip, user_agent
        ))
    except Exception as e:
        logger.error(f"Audit log insertion failed: {e}")
