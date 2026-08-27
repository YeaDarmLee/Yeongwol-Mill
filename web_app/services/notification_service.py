import os
import sys
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config
from db.db_connection import get_db_connection, execute_db_conn
from services.messaging.aligo_provider import AligoProvider
from services.messaging.provider import SendAdmissionStatus, ProviderDeliveryResultStatus, SendAdmissionResponse

logger = logging.getLogger(__name__)

TEMPLATE_FILE_MAP = {
    'ORDER_PAID_SMS': 'order_paid_sms.txt',
    'SHIPPED_SMS': 'shipped_sms.txt',
    'DELIVERED_SMS': 'delivered_sms.txt',
    'ORDER_CANCELLED_SMS': 'order_cancelled_sms.txt',
    'REFUND_COMPLETED_SMS': 'refund_completed_sms.txt'
}

class NotificationService:
    def __init__(self, provider=None):
        self.provider = provider or AligoProvider()
        self.template_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'templates', 'notifications'
        )

    def normalize_phone(self, phone: str) -> str:
        return (phone or "").replace('-', '').strip()

    def compute_payload_fingerprint(
        self,
        recipient: str,
        template_code: str,
        exact_message: str,
        button_json: Optional[str] = None
    ) -> str:
        canonical_payload = (
            self.normalize_phone(recipient) + "\n" +
            (template_code or "") + "\n" +
            (exact_message or "") + "\n" +
            (button_json or "")
        )
        return hashlib.sha256(canonical_payload.encode('utf-8')).hexdigest()

    def render_fallback_template(self, fallback_key: str, data: Dict[str, Any]) -> str:
        filename = TEMPLATE_FILE_MAP.get(fallback_key)
        if not filename:
            return ""
        path = os.path.join(self.template_dir, filename)
        if not os.path.exists(path):
            return ""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            return content.format(**data)
        except Exception as e:
            logger.error(f"[NotificationService] Render fallback template failed for {fallback_key}: {e}")
            return ""

    def enqueue(
        self,
        event_type: str,
        recipient: str,
        template_code: str,
        message: str,
        idempotency_key: str,
        button_json: Optional[str] = None,
        fallback_template_key: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        order_id: Optional[int] = None,
        shipment_id: Optional[int] = None,
        refund_id: Optional[int] = None
    ) -> bool:
        """동일 DB 트랜잭션 상에서 notification_jobs UNIQUE INSERT (Enqueue)"""
        clean_recipient = self.normalize_phone(recipient)
        fingerprint = self.compute_payload_fingerprint(clean_recipient, template_code, message, button_json)

        conn = get_db_connection(autocommit=False)
        try:
            query = """
                INSERT INTO notification_jobs (
                    event_type, order_id, shipment_id, refund_id,
                    recipient, provider, template_code, fallback_template_key,
                    idempotency_key, payload_fingerprint, status
                ) VALUES (%s, %s, %s, %s, %s, 'ALIGO', %s, %s, %s, %s, 'PENDING')
            """
            args = (
                event_type, order_id, shipment_id, refund_id,
                clean_recipient, template_code, fallback_template_key,
                idempotency_key, fingerprint
            )
            execute_db_conn(conn, query, args)
            conn.commit()
            logger.info(f"[NotificationService] Enqueued job: {idempotency_key}")
            return True
        except Exception as e:
            conn.rollback()
            # UNIQUE constraint violation handles idempotency gracefully
            logger.info(f"[NotificationService] Enqueue skipped (duplicate key or error): {idempotency_key} - {e}")
            return False
        finally:
            conn.close()

    def process_pending_jobs(self, batch_size: int = 10, worker_id: str = "worker-1") -> int:
        """PENDING -> DISPATCHING Claim (Short DB Txn) -> Aligo Send -> Status Update"""
        self.cleanup_stale_dispatching()

        # Step 1: Claim Jobs
        claimed_jobs = []
        conn = get_db_connection(autocommit=False)
        try:
            select_query = """
                SELECT id, event_type, recipient, template_code, fallback_template_key,
                       idempotency_key, payload_fingerprint, order_id, shipment_id, refund_id
                FROM notification_jobs
                WHERE status = 'PENDING'
                  AND next_attempt_at <= NOW()
                  AND (locked_until IS NULL OR locked_until < NOW())
                ORDER BY id ASC
                LIMIT %s
            """
            cursor = conn.cursor()
            adapted_select = select_query.replace('%s', '?') if conn._db_type == 'sqlite' else select_query
            cursor.execute(adapted_select, (batch_size,))
            if conn._db_type == 'mysql':
                rows = cursor.fetchall()
            else:
                rows = [dict(r) for r in cursor.fetchall()]

            for row in rows:
                job_id = row['id']
                update_query = """
                    UPDATE notification_jobs
                    SET status = 'DISPATCHING',
                        locked_by = %s,
                        locked_at = NOW(),
                        locked_until = DATE_ADD(NOW(), INTERVAL 5 MINUTE),
                        dispatch_started_at = NOW()
                    WHERE id = %s AND status = 'PENDING'
                """
                if conn._db_type == 'sqlite':
                    update_query = update_query.replace("DATE_ADD(NOW(), INTERVAL 5 MINUTE)", "datetime('now', '+5 minutes')")
                
                rc, _ = execute_db_conn(conn, update_query, (worker_id, job_id))
                if rc > 0:
                    claimed_jobs.append(row)

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"[NotificationService] Claim jobs error: {e}")
            return 0
        finally:
            conn.close()

        if not claimed_jobs:
            return 0

        # Step 2: Dispatch outside DB Txn
        processed_count = 0
        for job in claimed_jobs:
            job_id = job['id']
            recipient = job['recipient']
            fallback_key = job.get('fallback_template_key')

            # Render message (fallback 템플릿 우선, 없으면 기본 메시지)
            fallback_msg = self.render_fallback_template(fallback_key, self._build_context_data(job)) if fallback_key else None
            message = fallback_msg or self._build_message_text(job)

            # Send 1:1 SMS API call
            admission = self.provider.send_sms(
                recipient=recipient,
                message=message,
                subject="영월고향방앗간 알림"
            )

            # Record attempt & Update Job Status
            self._update_job_after_send(job_id, admission)
            processed_count += 1

        return processed_count

    def _update_job_after_send(self, job_id: int, admission: SendAdmissionResponse):
        conn = get_db_connection(autocommit=False)
        try:
            status = admission.status
            if status == SendAdmissionStatus.ACCEPTED:
                query = """
                    UPDATE notification_jobs
                    SET status = 'ACCEPTED',
                        provider_message_id = %s,
                        accepted_at = NOW(),
                        locked_until = NULL
                    WHERE id = %s
                """
                execute_db_conn(conn, query, (admission.provider_message_id, job_id))
            elif status == SendAdmissionStatus.RETRYABLE_REJECTED:
                query = """
                    UPDATE notification_jobs
                    SET status = 'PENDING',
                        attempt_count = attempt_count + 1,
                        next_attempt_at = DATE_ADD(NOW(), INTERVAL 2 MINUTE),
                        locked_until = NULL
                    WHERE id = %s
                """
                if conn._db_type == 'sqlite':
                    query = query.replace("DATE_ADD(NOW(), INTERVAL 2 MINUTE)", "datetime('now', '+2 minutes')")
                execute_db_conn(conn, query, (job_id,))
            elif status == SendAdmissionStatus.BLOCKED:
                query = """
                    UPDATE notification_jobs
                    SET status = 'BLOCKED',
                        attempt_count = attempt_count + 1,
                        locked_until = NULL
                    WHERE id = %s
                """
                execute_db_conn(conn, query, (job_id,))
            elif status == SendAdmissionStatus.PERMANENT_REJECTED:
                query = """
                    UPDATE notification_jobs
                    SET status = 'FAILED',
                        failed_at = NOW(),
                        locked_until = NULL
                    WHERE id = %s
                """
                execute_db_conn(conn, query, (job_id,))
            elif status == SendAdmissionStatus.UNKNOWN_RESULT:
                query = """
                    UPDATE notification_jobs
                    SET status = 'SEND_UNKNOWN',
                        locked_until = NULL
                    WHERE id = %s
                """
                execute_db_conn(conn, query, (job_id,))

            # Record attempt log
            attempt_query = """
                INSERT INTO notification_attempts (
                    job_id, attempt_no, requested_at, responded_at,
                    provider_result_code, provider_message, error_code, error_message
                ) VALUES (
                    %s, (SELECT COALESCE(MAX(a.attempt_no), 0) + 1 FROM notification_attempts a WHERE a.job_id = %s),
                    NOW(), NOW(), %s, %s, %s, %s
                )
            """
            execute_db_conn(conn, attempt_query, (
                job_id, job_id,
                str(admission.raw_code or ''),
                str(admission.raw_message or ''),
                str(admission.error_code or ''),
                str(admission.error_message or '')
            ))

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"[NotificationService] Update job status failed for job {job_id}: {e}")
        finally:
            conn.close()

    def cleanup_stale_dispatching(self):
        """DISPATCHING 및 locked_until < NOW() 상태의 stale job -> SEND_UNKNOWN 전환"""
        conn = get_db_connection(autocommit=True)
        try:
            query = """
                UPDATE notification_jobs
                SET status = 'SEND_UNKNOWN',
                    locked_until = NULL
                WHERE status = 'DISPATCHING'
                  AND locked_until IS NOT NULL
                  AND locked_until < NOW()
            """
            execute_db_conn(conn, query)
        except Exception as e:
            logger.error(f"[NotificationService] Cleanup stale dispatching error: {e}")
        finally:
            conn.close()

    def reconcile_jobs(self, batch_size: int = 20) -> int:
        """ACCEPTED 및 SEND_UNKNOWN 상태에 대한 2-Step Reconciliation"""
        conn = get_db_connection(autocommit=True)
        jobs = []
        try:
            query = """
                SELECT id, status, provider_message_id, recipient, template_code,
                       payload_fingerprint, dispatch_started_at, fallback_template_key
                FROM notification_jobs
                WHERE status IN ('ACCEPTED', 'SEND_UNKNOWN')
                ORDER BY id ASC
                LIMIT %s
            """
            cursor = conn.cursor()
            adapted_query = query.replace('%s', '?') if conn._db_type == 'sqlite' else query
            cursor.execute(adapted_query, (batch_size,))
            if conn._db_type == 'mysql':
                jobs = cursor.fetchall()
            else:
                jobs = [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"[NotificationService] Query reconcile jobs error: {e}")
            return 0
        finally:
            conn.close()

        reconciled_count = 0
        for job in jobs:
            job_id = job['id']
            status = job['status']
            mid = job['provider_message_id']

            if status == 'SEND_UNKNOWN' and not mid:
                # SEND_UNKNOWN: history/list -> candidate mid -> history/detail 교차검증 복구
                dispatch_date = datetime.now().strftime('%Y%m%d')
                if job.get('dispatch_started_at'):
                    try:
                        dispatch_date = datetime.strptime(str(job['dispatch_started_at']), '%Y-%m-%d %H:%M:%S').strftime('%Y%m%d')
                    except Exception:
                        pass
                
                message_text = self._build_message_text(job)
                candidate_mid = self.provider.find_candidate_mid(
                    dispatch_date=dispatch_date,
                    recipient=job['recipient'],
                    template_code=job['template_code'],
                    payload_fingerprint=job['payload_fingerprint'],
                    message_body=message_text
                )

                if candidate_mid:
                    mid = candidate_mid
                    self._update_job_status_and_mid(job_id, 'ACCEPTED', mid)
                else:
                    # 복구 실패 시 SEND_UNKNOWN 유지
                    continue

            if mid:
                result = self.provider.reconcile_sms(mid)
                if result.status == ProviderDeliveryResultStatus.SUCCESS:
                    self._mark_job_success(
                        job_id,
                        final_channel=result.final_channel or 'SMS',
                        fallback_used=result.fallback_used,
                        fallback_mid=result.provider_fallback_message_id
                    )
                    reconciled_count += 1
                elif result.status == ProviderDeliveryResultStatus.FAILED:
                    self._mark_job_failed(job_id)
                    reconciled_count += 1

        return reconciled_count

    def _update_job_status_and_mid(self, job_id: int, status: str, mid: str):
        execute_db("""
            UPDATE notification_jobs
            SET status = %s, provider_message_id = %s, accepted_at = NOW()
            WHERE id = %s
        """, (status, mid, job_id))

    def _mark_job_success(self, job_id: int, final_channel: str, fallback_used: bool, fallback_mid: Optional[str]):
        execute_db("""
            UPDATE notification_jobs
            SET status = 'SUCCESS',
                final_channel = %s,
                fallback_used = %s,
                provider_fallback_message_id = %s,
                sent_at = NOW()
            WHERE id = %s
        """, (final_channel, 1 if fallback_used else 0, fallback_mid, job_id))

    def _mark_job_failed(self, job_id: int):
        execute_db("""
            UPDATE notification_jobs
            SET status = 'FAILED',
                failed_at = NOW()
            WHERE id = %s
        """, (job_id,))

    def _build_message_text(self, job: Dict[str, Any]) -> str:
        # 이벤에 맞는 알림톡 기본 메시지 바디 생성
        event = job.get('event_type', '')
        return f"[영월고향방앗간] {event} 안내 메시지"

    def _build_context_data(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'order_number': job.get('order_id', ''),
            'order_name': '영월 고소한 참기름/들기름',
            'total_amount': '0',
            'tracking_number': '',
            'cancel_reason': '고객 요청',
            'refund_amount': '0'
        }
