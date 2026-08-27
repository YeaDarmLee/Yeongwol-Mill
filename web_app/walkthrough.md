# 영월방앗간 주문 관리 2단계 서브탭 & CS 분리 리팩토링 검증 보고서

## 1. 개요 (Overview)
기존 단일 `#orders` 관리자 주문 관리 화면을 **2계층 서브탭(주문 처리 워크플로우 탭 6종 + CS 처리 전용 탭 4종)** 구조로 완전 분리하고, **상태 머신(OrderStateMachine)**, **컨텍스트 가드(2-Tier Context Guards)**, **6대 서버 핵심 불변조건**, **Saga 취소 트랜잭션** 및 **부분 처리 응답 (Partial Batch API)**을 완벽하게 구현하였습니다.

---

## 2. 주요 변경 및 구현 내용

### A. 2계층 서브탭 UI 및 인라인 송장 입력 (`orders.html` & `orders.js`)
1. **주문 처리 워크플로우 서브탭**:
   - `PENDING` (신규 주문: `[선택 주문 확인]`, `[선택 주문 취소]`)
   - `CONFIRMED` (주문 확정: `[선택 상품 준비중 전환]`, `[선택 주문 취소]`)
   - `PREPARING` (상품 준비중: `[선택 배송 준비중 전환]`, `[선택 주문 취소]`)
   - `READY_TO_SHIP` (배송 준비중: **인라인 택배사/송장번호 입력 테이블**, `[송장 일괄 저장]`, `[선택 배송 시작]`)
   - `SHIPPING` (배송 중: `[선택 배송 완료 처리]`)
   - `DELIVERED` (배송 완료)
2. **CS 처리 전용 서브탭**:
   - `cs_cancel` (주문 취소 내역)
   - `cs_return` (반품 승인/검수)
   - `cs_exchange` (교환 처리)
   - `cs_refund` (PG 환불 처리 / `RECONCILE_REQUIRED` 대조중 경고 뱃지)
3. **URL 해시 싱크**:
   - `#orders/pending`, `#orders/ready_to_ship`, `#orders/cs_refund` 등 해시 라우팅 지원.
4. **부분 처리 Toast 및 알림**:
   - 배치 API 처리 시 성공 건수와 실패건(사유 포함)을 사용자에게 알림.

---

### B. 도메인 상태 머신 및 컨텍스트 가드 (`order_state_machine.py`)
1. **서버 측 수량 계산 규칙 (`compute_order_quantities`)**:
   - $\text{ordered\_qty} = \text{OrderItem.quantity}$
   - $\text{cancelled\_qty} = \text{COMPLETED CancellationRequestItem.approved\_qty}$
   - $\text{allocated\_qty} = \text{FULFILLMENT ShipmentItem.quantity}$ (`CREATED`, `READY`, `SHIPPED`, `DELIVERED`)
   - $\text{shipped\_qty} = \text{FULFILLMENT ShipmentItem.quantity}$ (`SHIPPED`, `DELIVERED`)
   - $\text{delivered\_qty} = \text{FULFILLMENT ShipmentItem.quantity}$ (`DELIVERED`)
   - $\text{remaining\_unallocated\_qty} = \text{ordered\_qty} - \text{cancelled\_qty} - \text{allocated\_qty}$
   - $\text{remaining\_unshipped\_qty} = \text{ordered\_qty} - \text{cancelled\_qty} - \text{shipped\_qty}$
   - $\text{remaining\_uncancelled\_qty} = \text{ordered\_qty} - \text{cancelled\_qty}$
2. **2계층 Context Guard (`validate_guards`)**:
   - 1차: `OrderStateMachine.validate_transition(current_status, target_status, payment_status)`
   - 2차: Context Guards:
     - `fulfillment_hold == True` $\implies$ 출고/배송 금지 (`FULFILLMENT_HELD`)
     - `payment_status IN ('PAID', 'PARTIALLY_REFUNDED')` 및 `remaining_unshipped_qty > 0` 검증
     - `READY_TO_SHIP` ➔ `SHIPPING` 전이 시 택배사 및 송장번호 필수 검증 (`MISSING_TRACKING_INFO`)
3. **금액 기준 Payment Status 자동 판정 (`calculate_payment_status`)**:
   - $\text{succeeded\_refund\_amount} == 0 \implies \text{PAID}$
   - $0 < \text{succeeded\_refund\_amount} < \text{captured\_amount} \implies \text{PARTIALLY\_REFUNDED}$
   - $\text{succeeded\_refund\_amount} == \text{captured\_amount} \implies \text{REFUNDED}$

---

### C. 백엔드 배치 API (`routes/admin.py`)
- `/api/admin/orders/counts` (실시간 서브탭 건수 및 `RECONCILE_REQUIRED` 경고 Badge 조회)
- `/api/admin/orders/confirm` (주문 확인)
- `/api/admin/orders/prepare` (상품 준비중)
- `/api/admin/orders/ready-to-ship` (배송 준비중)
- `/api/admin/orders/batch-tracking` (송장 일괄 저장)
- `/api/admin/orders/ship` (배송 시작)
- `/api/admin/orders/deliver` (배송 완료)
- `/api/admin/orders/cancel` (Saga 패턴 기반 취소 및 RefundEngine 연동, 부분 처리 표준 JSON 반환)

---

## 3. 자동화 E2E 테스트 검증 결과 (`test_admin_order_workflow.py`)

총 **23가지 E2E 테스트 시나리오**를 작성하고 100% 통과하였습니다.

```bash
pytest tests/test_admin_order_workflow.py
```

### 테스트 케이스 목록 및 결과:
1. `test_normal_order_workflow_transitions` - **PASSED** (PENDING ➔ CONFIRMED ➔ PREPARING ➔ READY_TO_SHIP ➔ SHIPPING ➔ DELIVERED 정상 전이)
2. `test_backward_transition_blocked` - **PASSED** (역행 전이 차단)
3. `test_skip_transition_blocked` - **PASSED** (건너뛰기 전이 차단)
4. `test_shipping_without_tracking_blocked` - **PASSED** (송장 없는 배송 시작 차단)
5. `test_cancelled_order_shipping_blocked` - **PASSED** (취소된 주문 배송전환 차단)
6. `test_refunded_order_shipping_blocked` - **PASSED** (환불완료 주문 배송전환 차단)
7. `test_paid_order_cancellation_via_refund_engine` - **PASSED** (PAID 주문 취소 시 RefundEngine 연동)
8. `test_batch_api_partial_success_response` - **PASSED** (Batch API 부분 성공/실패 JSON 응답)
9. `test_concurrency_lock_defense` - **PASSED** (SELECT FOR UPDATE 동시성 방어)
10. `test_batch_idempotency` - **PASSED** (배치 명령 멱등성 보장)
11. `test_audit_log_recorded` - **PASSED** (상태 변경 Audit Log 기록)
12. `test_unauthorized_user_access_blocked` - **PASSED** (비권한 유저 403 차단)
13. `test_race_condition_fulfillment_hold_and_reconcile_required` - **PASSED** (Race condition 방어 & RECONCILE_REQUIRED 발생 시 Hold 유지)
14. `test_partial_refund_payment_status` - **PASSED** (부분 환불 후 payment_status = PARTIALLY_REFUNDED)
15. `test_shipment_aggregation_to_order_delivered` - **PASSED** (Shipment 전체 배송완료 ➔ Order DELIVERED 자동 집계)
16. `test_cs_request_item_partial_qty_handling` - **PASSED** (CS RequestItem 품목별 부분수량 처리 & Allocation 차감)
17. `test_partial_cancel_order_status_not_cancelled` - **PASSED** (부분취소 성공 시 PARTIALLY_REFUNDED이나 order_status != CANCELLED)
18. `test_partially_refunded_order_remaining_items_shipped` - **PASSED** (PARTIALLY_REFUNDED 주문에서 잔여 품목 배송 가능)
19. `test_partial_cancel_plus_remaining_delivered_aggregation` - **PASSED** (일부 품목 취소 + 나머지 Shipment DELIVERED 시 최종 Order DELIVERED)
20. `test_delivered_order_full_return_independent_statuses` - **PASSED** (배송완료 주문 전량 반품 후 Order = DELIVERED 유지, ReturnRequest = COMPLETED, Payment.status = REFUNDED)
21. `test_payment_status_calculated_by_amount` - **PASSED** (payment_status 금액 기준 판정)
22. `test_ready_to_ship_allocation_not_miscounted_as_shipped` - **PASSED** (READY_TO_SHIP 단계 allocation이 shipped_qty로 오인되지 않음)
23. `test_exchange_shipment_purpose_isolation` - **PASSED** (Shipment.purpose = EXCHANGE 건은 FULFILLMENT 집계에서 격리)

---
**최종 결과: 23 PASSED (100% 성공)**
