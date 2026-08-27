import os
import sys
import logging
import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import Config
from db.db_connection import get_db_connection, execute_db, execute_db_conn

logger = logging.getLogger(__name__)

class DeliveryStatus(Enum):
    UNKNOWN = "UNKNOWN"           # 정상 응답이나 매핑되지 않는 신규 배송상태
    IN_TRANSIT = "IN_TRANSIT"     # 접수, 발송, 이동중
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY" # 배달준비, 배달출발
    DELIVERED = "DELIVERED"       # 배달완료
    EXCEPTION = "EXCEPTION"       # 반송, 미배달

@dataclass
class TrackingFetchResult:
    success: bool
    status: Optional[DeliveryStatus] = None
    raw_status: Optional[str] = None
    delivered_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

class EPostProvider:
    """과학기술정보통신부 우정사업본부_국내우편물 종적 조회 서비스 (Data ID: 15000390)"""
    ENDPOINT_URL = "http://openapi.epost.go.kr/trace/retrieveLongitudinalService/retrieveLongitudinalService/getLongitudinalList"

    def __init__(self):
        self.service_key = getattr(Config, 'EPOST_API_SERVICE_KEY', '')
        self.timeout = getattr(Config, 'EPOST_TRACKING_TIMEOUT_SECONDS', 10)

    def fetch_tracking_info(self, tracking_number: str) -> TrackingFetchResult:
        clean_number = (tracking_number or "").replace('-', '').strip()
        if len(clean_number) != 13 or not clean_number.isdigit():
            return TrackingFetchResult(
                success=False,
                error_code="INVALID_TRACKING_NUMBER",
                error_message="13자리 등기번호 양식이 아닙니다."
            )

        params = {
            'serviceKey': self.service_key,
            'rgno': clean_number
        }

        try:
            res = requests.get(self.ENDPOINT_URL, params=params, timeout=self.timeout)
            if res.status_code != 200:
                return TrackingFetchResult(
                    success=False,
                    error_code=f"HTTP_{res.status_code}",
                    error_message=res.text
                )

            # XML 파싱
            root = ET.fromstring(res.content)

            # 에러 응답 체크
            header = root.find('.//header') or root.find('.//cmmMsgHeader')
            if header is not None:
                result_code = header.findtext('resultCode') or header.findtext('errMsg')
                if result_code and result_code not in ['00', 'NORMAL_SERVICE']:
                    result_msg = header.findtext('resultMsg') or ''
                    return TrackingFetchResult(
                        success=False,
                        error_code=result_code,
                        error_message=result_msg
                    )

            # 배달상태 및 종적목록 파싱
            raw_status = root.findtext('.//dlvyStts') or root.findtext('.//nowStts') or ''
            delivery_date_str = root.findtext('.//dlvyDe') or ''

            mapped_status = self.normalize_status(raw_status)
            delivered_at = None

            if mapped_status == DeliveryStatus.DELIVERED and delivery_date_str:
                try:
                    delivered_at = datetime.strptime(delivery_date_str.strip(), '%Y%m%d')
                except Exception:
                    delivered_at = datetime.now()

            return TrackingFetchResult(
                success=True,
                status=mapped_status,
                raw_status=raw_status,
                delivered_at=delivered_at
            )

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"[EPostProvider] Timeout/Connection error for {clean_number}: {e}")
            return TrackingFetchResult(
                success=False,
                error_code="EPOST_TIMEOUT",
                error_message=str(e)
            )
        except ET.ParseError as e:
            logger.error(f"[EPostProvider] XML parse error for {clean_number}: {e}")
            return TrackingFetchResult(
                success=False,
                error_code="XML_PARSE_ERROR",
                error_message=str(e)
            )
        except Exception as e:
            logger.error(f"[EPostProvider] Unexpected exception for {clean_number}: {e}")
            return TrackingFetchResult(
                success=False,
                error_code="EXCEPTION",
                error_message=str(e)
            )

    @staticmethod
    def normalize_status(raw_status: str) -> DeliveryStatus:
        if not raw_status:
            return DeliveryStatus.UNKNOWN

        clean = raw_status.strip()
        if "배달완료" in clean or "완료" in clean:
            return DeliveryStatus.DELIVERED
        elif "배달준비" in clean or "배달출발" in clean:
            return DeliveryStatus.OUT_FOR_DELIVERY
        elif "접수" in clean or "발송" in clean or "이동" in clean or "도착" in clean or "구분" in clean:
            return DeliveryStatus.IN_TRANSIT
        elif "반송" in clean or "미배달" in clean or "보관" in clean:
            return DeliveryStatus.EXCEPTION
        else:
            return DeliveryStatus.UNKNOWN

class EPostDeliveryTracker:
    def __init__(self, provider=None):
        self.provider = provider or EPostProvider()

    def process_polling_shipments(self, batch_size: int = 50) -> int:
        """status='SHIPPED' 인 운송장에 대한 주기적 Polling"""
        conn = get_db_connection(autocommit=True)
        shipments = []
        try:
            query = """
                SELECT id, order_id, tracking_number
                FROM shipments
                WHERE status = 'SHIPPED'
                  AND courier = 'EPOST'
                  AND tracking_number IS NOT NULL
                  AND (tracking_next_check_at IS NULL OR tracking_next_check_at <= NOW())
                ORDER BY id ASC
                LIMIT %s
            """
            cursor = conn.cursor()
            adapted_query = query.replace('%s', '?') if conn._db_type == 'sqlite' else query
            cursor.execute(adapted_query, (batch_size,))
            if conn._db_type == 'mysql':
                shipments = cursor.fetchall()
            else:
                shipments = [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"[EPostDeliveryTracker] Query shipments error: {e}")
            return 0
        finally:
            conn.close()

        updated_count = 0
        for item in shipments:
            shipment_id = item['id']
            order_id = item['order_id']
            tracking_number = item['tracking_number']

            result = self.provider.fetch_tracking_info(tracking_number)

            if not result.success:
                # API 실패 시 기존 배송상태 덮어쓰지 않음 (Fail-Closed)
                q = "UPDATE shipments SET tracking_last_checked_at = NOW(), tracking_next_check_at = DATE_ADD(NOW(), INTERVAL 1 HOUR), tracking_error_count = tracking_error_count + 1, tracking_last_error = %s WHERE id = %s"
                if conn._db_type == 'sqlite':
                    q = q.replace("DATE_ADD(NOW(), INTERVAL 1 HOUR)", "datetime('now', '+1 hour')")
                execute_db(q, (f"{result.error_code}: {result.error_message}", shipment_id))
                continue

            if result.status == DeliveryStatus.DELIVERED:
                delivered_at = result.delivered_at or datetime.now()
                # 1. shipment 상태 DELIVERED 업데이트
                execute_db("""
                    UPDATE shipments
                    SET status = 'DELIVERED',
                        delivered_at = %s,
                        tracking_last_checked_at = NOW(),
                        tracking_next_check_at = NULL,
                        tracking_last_status = 'DELIVERED'
                    WHERE id = %s
                """, (delivered_at, shipment_id))

                # 2. orders 테이블 상태 업데이트
                execute_db("""
                    UPDATE orders
                    SET order_status = 'DELIVERED',
                        delivered_at = %s
                    WHERE id = %s
                """, (delivered_at, order_id))

                # 3. 배송완료 알림톡 Enqueue (DELIVERED:{shipment_id} 멱등키 사용)
                from services.notification_service import NotificationService
                order_info = execute_db("""SELECT guest_phone, recipient_phone FROM orders WHERE id = %s""", (order_id,))
                recipient = ''
                if isinstance(order_info, dict):
                    recipient = order_info.get('recipient_phone') or order_info.get('guest_phone') or ''

                if recipient:
                    NotificationService().enqueue(
                        event_type="DELIVERED",
                        recipient=recipient,
                        template_code="DELIVERED",
                        message="[영월고향방앗간] 고객님의 상품 배송이 완료되었습니다.",
                        idempotency_key=f"DELIVERED:{shipment_id}",
                        fallback_template_key="DELIVERED_SMS",
                        order_id=order_id,
                        shipment_id=shipment_id
                    )

                updated_count += 1
            else:
                # 배송중 유지 -> 1시간 후 재조회
                q = "UPDATE shipments SET tracking_last_checked_at = NOW(), tracking_next_check_at = DATE_ADD(NOW(), INTERVAL 1 HOUR), tracking_last_status = %s WHERE id = %s"
                if conn._db_type == 'sqlite':
                    q = q.replace("DATE_ADD(NOW(), INTERVAL 1 HOUR)", "datetime('now', '+1 hour')")
                execute_db(q, (result.status.value if result.status else 'IN_TRANSIT', shipment_id))

        return updated_count
