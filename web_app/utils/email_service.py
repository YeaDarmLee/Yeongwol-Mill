import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

import json
import datetime
from db.db_connection import query_db, execute_db

def send_email(to_email, subject, body_html):
    """
    이메일 발송 유틸리티.
    SMTP 환경변수가 설정되어 있으면 실제 SMTP로 발송하고,
    설정되어 있지 않으면 개발/테스트용 모드로 콘솔 로그 출력 후 성공 처리합니다.
    """
    smtp_server = os.getenv('SMTP_SERVER', '')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    smtp_user = os.getenv('SMTP_USER', '')
    smtp_password = os.getenv('SMTP_PASSWORD', '')
    smtp_from = os.getenv('SMTP_FROM_EMAIL', Config.CUSTOMER_SERVICE_EMAIL)

    if not smtp_server or not smtp_user:
        # SMTP 미설정 시 개발/디버그 가상 발송 모드
        print(f"[Email Service (Dev Mode)] To: {to_email} | Subject: {subject}")
        return True

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{Config.BUSINESS_NAME} <{smtp_from}>"
        msg['To'] = to_email

        html_part = MIMEText(body_html, 'html', 'utf-8')
        msg.attach(html_part)

        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, [to_email], msg.as_string())
        return True
    except Exception as e:
        print(f"[Email Service Error] Failed to send email to {to_email}: {e}")
        return False

def send_marketing_consent_notice_email(to_email, user_name, consent_type, action, updated_at):
    """
    정보통신망법 제62조의2(14일 이내 처리결과 통지 의무)에 따른 마케팅 수신동의/철회 처리결과 안내 메일 발송
    """
    action_text = "수신 동의" if action == "AGREED" else "수신 거부(철회)"
    type_text = "이메일 광고성 정보" if consent_type == "MARKETING_EMAIL" else "SMS 광고성 정보"
    subject = f"[{Config.BUSINESS_NAME}] {type_text} {action_text} 처리 결과 안내"

    body_html = f"""
    <div style="font-family: 'Noto Sans KR', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eaeaea; border-radius: 8px;">
        <h2 style="color: #915a28; border-bottom: 2px solid #915a28; padding-bottom: 10px;">영월고향방앗간 수신설정 처리 결과</h2>
        <p>안녕하세요, <strong>{user_name or '회원'}</strong>님.</p>
        <p>요청하신 광고성 정보 수신 동의/철회 처리 결과를 다음과 같이 안내해 드립니다.</p>
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0; background: #fafafa;">
            <tr>
                <td style="padding: 10px; border: 1px solid #eee; font-weight: bold; width: 30%;">전송자 명칭</td>
                <td style="padding: 10px; border: 1px solid #eee;">{Config.BUSINESS_NAME}</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #eee; font-weight: bold;">처리 대상 매체</td>
                <td style="padding: 10px; border: 1px solid #eee;">{type_text}</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #eee; font-weight: bold;">처리 일시</td>
                <td style="padding: 10px; border: 1px solid #eee;">{updated_at}</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #eee; font-weight: bold;">처리 결과</td>
                <td style="padding: 10px; border: 1px solid #eee; color: {'green' if action == 'AGREED' else '#d32f2f'}; font-weight: bold;">{action_text} 완료</td>
            </tr>
        </table>
        <p style="font-size: 0.85rem; color: #777;">* 본 메일은 정보통신망 이용촉진 및 정보보호 등에 관한 법률 시행령에 따라 발송되는 수신동의/철회 처리 결과 안내 메일입니다.</p>
    </div>
    """
    return send_email(to_email, subject, body_html)

def process_notification_outbox():
    """
    notification_outbox 테이블의 PENDING 상태 알림 건을 가져와 이메일 전송 (Outbox Pattern)
    """
    pending_records = query_db("SELECT * FROM notification_outbox WHERE status = 'PENDING' LIMIT 20") or []
    for rec in pending_records:
        try:
            payload = json.loads(rec['payload'])
            success = False
            if rec['type'] == 'MARKETING_CONSENT_NOTICE':
                success = send_marketing_consent_notice_email(
                    to_email=rec['email'],
                    user_name=payload.get('user_name'),
                    consent_type=payload.get('consent_type'),
                    action=payload.get('action'),
                    updated_at=payload.get('updated_at')
                )
            
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if success:
                execute_db("UPDATE notification_outbox SET status = 'SENT', sent_at = %s WHERE id = %s", (now_str, rec['id']))
            else:
                execute_db("UPDATE notification_outbox SET retry_count = retry_count + 1 WHERE id = %s", (rec['id'],))
        except Exception as e:
            print(f"[Outbox Processing Exception] {e}")
            execute_db("UPDATE notification_outbox SET retry_count = retry_count + 1 WHERE id = %s", (rec['id'],))
