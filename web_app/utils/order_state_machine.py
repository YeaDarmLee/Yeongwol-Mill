class OrderStateMachineError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)

class OrderStateMachine:
    ALLOWED_TRANSITIONS = {
        'PENDING': ['CONFIRMED', 'CANCELLED'],
        'CONFIRMED': ['PREPARING', 'CANCELLED'],
        'PREPARING': ['SHIPPING', 'CANCELLED'],
        'SHIPPING': ['DELIVERED'],
        'DELIVERED': [],
        'CANCELLED': [],
        'REFUNDED': []
    }

    @classmethod
    def validate_transition(cls, current_status, target_status, payment_status=None):
        current_status = (current_status or 'PENDING').upper()
        target_status = (target_status or '').upper()
        payment_status = (payment_status or '').upper()

        if current_status == target_status:
            return True

        allowed = cls.ALLOWED_TRANSITIONS.get(current_status, [])
        if target_status not in allowed:
            raise OrderStateMachineError(
                'INVALID_STATE_TRANSITION',
                f"[{current_status}] 상태에서 [{target_status}](으)로 직접 상태를 변경할 수 없습니다."
            )

        # 결제 완료(PAID) 상태인 경우 /status API를 통한 CANCELLED 직접 전이 금지
        if target_status == 'CANCELLED' and payment_status in ('PAID', 'PARTIALLY_REFUNDED'):
            raise OrderStateMachineError(
                'USE_REFUND_ENDPOINT',
                '결제 완료(PAID) 상태의 주문은 일반 상태 변경으로 취소할 수 없습니다. 환불 관리 기능을 이용해 주세요.'
            )

        return True
