from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

class SendAdmissionStatus(Enum):
    ACCEPTED = "ACCEPTED"
    RETRYABLE_REJECTED = "RETRYABLE_REJECTED"
    BLOCKED = "BLOCKED"
    PERMANENT_REJECTED = "PERMANENT_REJECTED"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"

class ProviderDeliveryResultStatus(Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"

@dataclass
class SendAdmissionResponse:
    status: SendAdmissionStatus
    provider_message_id: Optional[str] = None
    raw_code: Optional[Any] = None
    raw_message: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

@dataclass
class ProviderReconcileResult:
    status: ProviderDeliveryResultStatus
    final_channel: Optional[str] = None  # SMS, LMS
    fallback_used: bool = False
    provider_message_id: Optional[str] = None
    provider_fallback_message_id: Optional[str] = None
    raw_code: Optional[Any] = None
    raw_message: Optional[str] = None

class BaseMessagingProvider(ABC):
    @abstractmethod
    def send_sms(
        self,
        recipient: str,
        message: str,
        subject: Optional[str] = None
    ) -> SendAdmissionResponse:
        """SMS/LMS 문자 발송"""
        pass

    @abstractmethod
    def reconcile_sms(
        self,
        provider_message_id: str
    ) -> ProviderReconcileResult:
        """mid 기준 SMS 전송 결과 조회"""
        pass

    @abstractmethod
    def find_candidate_mid(
        self,
        dispatch_date: str,  # YYYYMMDD
        recipient: str,
        template_code: str,
        payload_fingerprint: str,
        message_body: str
    ) -> Optional[str]:
        """SEND_UNKNOWN 상태 복구를 위한 sms_list -> 2단계 mid 찾기"""
        pass
