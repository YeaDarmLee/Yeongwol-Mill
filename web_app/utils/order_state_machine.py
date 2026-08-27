class OrderStateMachineError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)

class OrderStateMachine:
    ALLOWED_TRANSITIONS = {
        'PENDING': ['CONFIRMED', 'PREPARING', 'CANCELLED'],
        'CONFIRMED': ['PREPARING', 'CANCELLED'],
        'PREPARING': ['READY_TO_SHIP', 'SHIPPING', 'CANCELLED'],
        'READY_TO_SHIP': ['SHIPPING', 'PREPARING', 'CANCELLED'],
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

        if target_status == 'CANCELLED' and payment_status in ('PAID', 'PARTIALLY_REFUNDED'):
            raise OrderStateMachineError(
                'USE_REFUND_ENDPOINT',
                '결제 완료(PAID/PARTIALLY_REFUNDED) 상태의 주문은 일반 상태 변경으로 취소할 수 없습니다. 환불/취소 관리 엔진을 이용해 주세요.'
            )

        return True

    @classmethod
    def validate_guards(cls, order, target_status, shipment=None, qty_info=None):
        """100% Sealed Context Guard 2계층 검증 엔진"""
        target_status = (target_status or '').upper()
        payment_status = (order.get('payment_status') or '').upper()

        # Guard 1: Fulfillment Fence 검증
        if order.get('fulfillment_hold'):
            reason = order.get('fulfillment_hold_reason') or 'CS/환불 처리 진행 중'
            raise OrderStateMachineError(
                'FULFILLMENT_HELD',
                f"주문이 보류 상태({reason})입니다. 출고 및 상태 변경이 금지됩니다."
            )

        # Guard 2: 출고 구간(CONFIRMED, PREPARING, READY_TO_SHIP, SHIPPING) 결제 및 잔여 수량 검증
        if target_status in ('CONFIRMED', 'PREPARING', 'READY_TO_SHIP', 'SHIPPING'):
            if payment_status not in ('PAID', 'PARTIALLY_REFUNDED'):
                raise OrderStateMachineError(
                    'INVALID_PAYMENT_STATUS',
                    f"결제 완료(PAID/PARTIALLY_REFUNDED) 상태가 아닌 주문({payment_status})은 출고 처리할 수 없습니다."
                )

            if qty_info and qty_info.get('remaining_unshipped_qty', 1) <= 0:
                raise OrderStateMachineError(
                    'NO_REMAINING_UNSHIPPED_QTY',
                    '출고 가능한 잔여 상품 수량이 없습니다.'
                )

        # Guard 3: SHIPPING 전이 시 송장(Shipment) 유효성 검증
        if target_status == 'SHIPPING':
            if not shipment:
                raise OrderStateMachineError(
                    'MISSING_SHIPMENT',
                    '배송 시작을 위한 운송장 정보(Shipment)가 등록되지 않았습니다.'
                )
            if not shipment.get('carrier_code') or not shipment.get('tracking_number'):
                raise OrderStateMachineError(
                    'MISSING_TRACKING_INFO',
                    '택배사와 운송장 번호가 입력되지 않은 주문은 배송을 시작할 수 없습니다.'
                )

        # Guard 4: 취소 전이 시 출고 완료 항목 존재 여부 검증 (P0 Invariant)
        if target_status == 'CANCELLED':
            if qty_info and qty_info.get('shipped_qty', 0) > 0:
                raise OrderStateMachineError(
                    'SHIPPED_ITEMS_CANNOT_BE_CANCELLED',
                    '이미 출고(SHIPPED/DELIVERED)된 품목은 취소할 수 없습니다. 반품/교환 절차를 이용해 주세요.'
                )

        return True

    @classmethod
    def calculate_payment_status(cls, captured_amount, succeeded_refund_amount):
        """금액 기반 payment_status 정밀 계산"""
        captured_amount = int(captured_amount or 0)
        succeeded_refund_amount = int(succeeded_refund_amount or 0)

        if succeeded_refund_amount <= 0:
            return 'PAID'
        elif succeeded_refund_amount < captured_amount:
            return 'PARTIALLY_REFUNDED'
        else:
            return 'REFUNDED'

    @classmethod
    def validate_refund_guard(cls, captured_amount, current_succeeded_refund, new_refund_amount):
        """원결제액 초과 환불 방지 Refund Guard"""
        captured_amount = int(captured_amount or 0)
        current_succeeded_refund = int(current_succeeded_refund or 0)
        new_refund_amount = int(new_refund_amount or 0)

        if new_refund_amount <= 0:
            raise OrderStateMachineError('INVALID_REFUND_AMOUNT', '환불 요청 금액은 0보다 커야 합니다.')

        if (current_succeeded_refund + new_refund_amount) > captured_amount:
            raise OrderStateMachineError(
                'EXCEEDS_CAPTURED_AMOUNT',
                f"환불 요청 금액({new_refund_amount:,}원)이 남은 환불 가능액({captured_amount - current_succeeded_refund:,}원)을 초과할 수 없습니다."
            )

        return True

    @classmethod
    def compute_order_quantities(cls, conn, order_id):
        """Order, OrderItem, ShipmentItem, CS RequestItems 조인을 통한 수량 집계 계산 엔진"""
        cursor = conn.cursor()
        
        # 1. ordered_qty
        cursor.execute("SELECT COALESCE(SUM(quantity), 0) FROM order_items WHERE order_id = %s", (order_id,))
        row = cursor.fetchone()
        ordered_qty = int(list(row.values())[0] if isinstance(row, dict) else row[0])

        # 2. cancelled_qty (COMPLETED CancellationRequestItem)
        cursor.execute("""
            SELECT COALESCE(SUM(cri.approved_qty), 0)
            FROM cancellation_request_items cri
            JOIN cancellation_requests cr ON cri.cancellation_request_id = cr.id
            WHERE cr.order_id = %s AND cr.status = 'COMPLETED'
        """, (order_id,))
        row = cursor.fetchone()
        cancelled_qty = int(list(row.values())[0] if isinstance(row, dict) else row[0])

        # 3. allocated_qty (FULFILLMENT shipments CREATED/READY/SHIPPED/DELIVERED)
        cursor.execute("""
            SELECT COALESCE(SUM(si.quantity), 0)
            FROM shipment_items si
            JOIN shipments s ON si.shipment_id = s.id
            WHERE s.order_id = %s AND s.purpose = 'FULFILLMENT' AND s.status IN ('CREATED', 'READY', 'SHIPPED', 'DELIVERED')
        """, (order_id,))
        row = cursor.fetchone()
        allocated_qty = int(list(row.values())[0] if isinstance(row, dict) else row[0])

        # 4. shipped_qty (FULFILLMENT shipments SHIPPED/DELIVERED)
        cursor.execute("""
            SELECT COALESCE(SUM(si.quantity), 0)
            FROM shipment_items si
            JOIN shipments s ON si.shipment_id = s.id
            WHERE s.order_id = %s AND s.purpose = 'FULFILLMENT' AND s.status IN ('SHIPPED', 'DELIVERED')
        """, (order_id,))
        row = cursor.fetchone()
        shipped_qty = int(list(row.values())[0] if isinstance(row, dict) else row[0])

        # 5. delivered_qty (FULFILLMENT shipments DELIVERED)
        cursor.execute("""
            SELECT COALESCE(SUM(si.quantity), 0)
            FROM shipment_items si
            JOIN shipments s ON si.shipment_id = s.id
            WHERE s.order_id = %s AND s.purpose = 'FULFILLMENT' AND s.status = 'DELIVERED'
        """, (order_id,))
        row = cursor.fetchone()
        delivered_qty = int(list(row.values())[0] if isinstance(row, dict) else row[0])

        remaining_unallocated_qty = max(0, ordered_qty - cancelled_qty - allocated_qty)
        remaining_unshipped_qty = max(0, ordered_qty - cancelled_qty - shipped_qty)
        remaining_uncancelled_qty = max(0, ordered_qty - cancelled_qty)

        return {
            'ordered_qty': ordered_qty,
            'cancelled_qty': cancelled_qty,
            'allocated_qty': allocated_qty,
            'shipped_qty': shipped_qty,
            'delivered_qty': delivered_qty,
            'remaining_unallocated_qty': remaining_unallocated_qty,
            'remaining_unshipped_qty': remaining_unshipped_qty,
            'remaining_uncancelled_qty': remaining_uncancelled_qty
        }
