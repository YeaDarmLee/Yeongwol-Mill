import logging
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime

from config import Config
from .provider import (
    BaseMessagingProvider,
    SendAdmissionResponse,
    SendAdmissionStatus,
    ProviderReconcileResult,
    ProviderDeliveryResultStatus
)
from .aligo_result_mapper import AligoResultMapper

logger = logging.getLogger(__name__)

class AligoProvider(BaseMessagingProvider):
    BASE_URL = "https://apis.aligo.in"

    def __init__(self):
        self.api_key = getattr(Config, 'ALIGO_API_KEY', '')
        self.user_id = getattr(Config, 'ALIGO_USER_ID', '')
        self.sender = getattr(Config, 'ALIGO_SENDER', '')

    def _get_base_payload(self) -> Dict[str, str]:
        return {
            'apikey': self.api_key,
            'userid': self.user_id,
        }

    def send_sms(
        self,
        recipient: str,
        message: str,
        subject: Optional[str] = None
    ) -> SendAdmissionResponse:
        """SMS/LMS 문자 발송"""
        url = f"{self.BASE_URL}/send/"

        # 90바이트 초과 시 LMS로 자동 구분
        msg_type = 'LMS' if len(message.encode('euc-kr', errors='replace')) > 90 else 'SMS'

        payload = {
            'apikey': self.api_key,
            'userid': self.user_id,
            'sendernum': self.sender,
            'receiver_1': recipient.replace('-', '').strip(),
            'msg_1': message,
            'msg_type': msg_type,
        }

        if subject and msg_type == 'LMS':
            payload['title'] = subject

        try:
            res = requests.post(url, data=payload, timeout=10)
            if res.status_code != 200:
                return SendAdmissionResponse(
                    status=SendAdmissionStatus.RETRYABLE_REJECTED,
                    raw_code=res.status_code,
                    raw_message=res.text,
                    error_code=f"HTTP_{res.status_code}",
                    error_message=res.text
                )

            data = res.json()
            raw_code = data.get('result_code')
            raw_message = data.get('message', '')
            mid = data.get('msg_id')

            status = AligoResultMapper.classify(raw_code, raw_message, endpoint="sms/send")

            if status == SendAdmissionStatus.ACCEPTED and mid:
                return SendAdmissionResponse(
                    status=SendAdmissionStatus.ACCEPTED,
                    provider_message_id=str(mid),
                    raw_code=raw_code,
                    raw_message=raw_message
                )
            else:
                return SendAdmissionResponse(
                    status=status,
                    raw_code=raw_code,
                    raw_message=raw_message,
                    error_code=str(raw_code),
                    error_message=raw_message
                )

        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"[AligoProvider] Network timeout/connection error: {e}")
            return SendAdmissionResponse(
                status=SendAdmissionStatus.UNKNOWN_RESULT,
                error_code="NETWORK_TIMEOUT",
                error_message=str(e)
            )
        except Exception as e:
            logger.error(f"[AligoProvider] Unexpected exception in send_sms: {e}")
            return SendAdmissionResponse(
                status=SendAdmissionStatus.RETRYABLE_REJECTED,
                error_code="EXCEPTION",
                error_message=str(e)
            )

    def reconcile_sms(self, provider_message_id: str) -> ProviderReconcileResult:
        """mid 기준 SMS 전송 결과 조회"""
        url = f"{self.BASE_URL}/sms_list/"
        payload = {
            'apikey': self.api_key,
            'userid': self.user_id,
            'mid': provider_message_id
        }

        try:
            res = requests.post(url, data=payload, timeout=10)
            if res.status_code != 200:
                return ProviderReconcileResult(
                    status=ProviderDeliveryResultStatus.PENDING,
                    raw_code=res.status_code,
                    raw_message=res.text
                )

            data = res.json()
            list_data = data.get('list', [])
            if not list_data:
                return ProviderReconcileResult(
                    status=ProviderDeliveryResultStatus.PENDING,
                    provider_message_id=provider_message_id
                )

            item = list_data[0]
            sms_type = item.get('type', 'SMS').upper()
            sms_status_code = str(item.get('sms_state', item.get('stat', '')))

            if sms_status_code in ['1', 'SUCCESS', '0', 'COMPLETE']:
                return ProviderReconcileResult(
                    status=ProviderDeliveryResultStatus.SUCCESS,
                    final_channel=sms_type,
                    fallback_used=False,
                    provider_message_id=provider_message_id,
                    raw_code=sms_status_code,
                    raw_message=item.get('msg', 'SMS Sent')
                )
            elif sms_status_code in ['PENDING', 'PROCESSING']:
                return ProviderReconcileResult(
                    status=ProviderDeliveryResultStatus.PENDING,
                    provider_message_id=provider_message_id
                )
            else:
                return ProviderReconcileResult(
                    status=ProviderDeliveryResultStatus.FAILED,
                    final_channel=sms_type,
                    provider_message_id=provider_message_id,
                    raw_code=sms_status_code,
                    raw_message=item.get('msg', 'SMS Failed')
                )

        except Exception as e:
            logger.error(f"[AligoProvider] Exception in reconcile_sms: {e}")
            return ProviderReconcileResult(
                status=ProviderDeliveryResultStatus.PENDING,
                provider_message_id=provider_message_id
            )

    def find_candidate_mid(
        self,
        dispatch_date: str,  # YYYYMMDD
        recipient: str,
        template_code: str,
        payload_fingerprint: str,
        message_body: str
    ) -> Optional[str]:
        """SEND_UNKNOWN 상태 복구를 위한 sms_list -> 2단계 mid 찾기"""
        url = f"{self.BASE_URL}/sms_list/"
        clean_recipient = recipient.replace('-', '').strip()

        matched_mids: List[str] = []

        page = 1
        total_page = 1

        while page <= total_page and page <= 5:  # 안전을 위해 최대 5페이지 순회
            payload = {
                'apikey': self.api_key,
                'userid': self.user_id,
                'startdate': dispatch_date,
                'enddate': dispatch_date,
                'page': page,
                'limit': 50
            }

            try:
                res = requests.post(url, data=payload, timeout=10)
                if res.status_code != 200:
                    break

                data = res.json()
                total_page = int(data.get('totalPage', 1))
                list_data = data.get('list', [])

                for item in list_data:
                    item_mid = str(item.get('mid', ''))
                    item_mbody = str(item.get('msg', ''))

                    if item_mid:
                        # 1차 로컬 필터: 메시지 본문 비교
                        if message_body.strip() in item_mbody or item_mbody in message_body.strip():
                            matched_mids.append(item_mid)

                page += 1
            except Exception as e:
                logger.error(f"[AligoProvider] Exception in find_candidate_mid page {page}: {e}")
                break

        # 후보 mid들에 대해 sms_list 상세 교차 검증
        final_candidate_mid: Optional[str] = None
        valid_count = 0

        for candidate_mid in set(matched_mids):
            try:
                d_res = requests.post(url, data={**self._get_base_payload(), 'mid': candidate_mid}, timeout=10)
                if d_res.status_code == 200:
                    d_data = d_res.json()
                    d_list = d_data.get('list', [])
                    d_item = d_list[0] if isinstance(d_list, list) and d_list else {}

                    target_phone = str(d_item.get('phone', '')).replace('-', '').strip()

                    if target_phone == clean_recipient:
                        valid_count += 1
                        final_candidate_mid = candidate_mid
            except Exception:
                continue

        # 정확히 1개 일치할 때만 복구 mid 인정
        if valid_count == 1:
            return final_candidate_mid
        return None
