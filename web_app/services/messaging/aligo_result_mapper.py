from typing import Optional, Any
from .provider import SendAdmissionStatus, ProviderDeliveryResultStatus

class AligoResultMapper:
    @staticmethod
    def classify(code: Any, message: Optional[str] = None, endpoint: str = "send") -> SendAdmissionStatus:
        """Aligo API 응답 code, message, endpoint 기준 SendAdmissionStatus 분류"""
        if code is None:
            return SendAdmissionStatus.UNKNOWN_RESULT

        try:
            int_code = int(code)
        except (ValueError, TypeError):
            return SendAdmissionStatus.UNKNOWN_RESULT

        if int_code == 1:
            return SendAdmissionStatus.ACCEPTED

        msg = (message or "").lower()

        # 포인트 부족, 인증키/발신번호 미등록 등 운영 설정 오류 -> BLOCKED
        if int_code == -99 or "포인트" in msg or "인증키" in msg or "발신" in msg:
            return SendAdmissionStatus.BLOCKED

        # 잘못된 수신 전화번호, 필수 파라미터 유실 등 페이로드 오류 -> PERMANENT_REJECTED
        if int_code in [-101, -102, -801] or "전화번호" in msg or "수신자" in msg:
            return SendAdmissionStatus.PERMANENT_REJECTED

        # 일시적 5xx 서버 에러 -> RETRYABLE_REJECTED
        if int_code in [-500, -502, -503]:
            return SendAdmissionStatus.RETRYABLE_REJECTED

        # 기본값: RETRYABLE_REJECTED
        return SendAdmissionStatus.RETRYABLE_REJECTED

    @staticmethod
    def map_sms_result(stat: Optional[str], message: Optional[str] = None) -> ProviderDeliveryResultStatus:
        """Aligo sms_list stat 코드 매핑"""
        if stat is None:
            return ProviderDeliveryResultStatus.PENDING

        stat_str = str(stat).upper().strip()

        # 성공
        if stat_str in ['1', 'SUCCESS', 'COMPLETE', 'Y']:
            return ProviderDeliveryResultStatus.SUCCESS

        # 대기/처리중
        if stat_str in ['0', 'P', 'PROCESSING', 'SENDING', 'WAIT', 'PENDING']:
            return ProviderDeliveryResultStatus.PENDING

        # 실패
        return ProviderDeliveryResultStatus.FAILED
