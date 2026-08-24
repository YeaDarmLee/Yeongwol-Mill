# 🛍️ 영월고향방앗간 쇼핑몰 오픈 전 Production Readiness 전수 감사 및 최종 개발 명세서

**검사 및 최종 개정 일시**: 2026년 8월 24일  
**감사 대상**: 영월고향방앗간(Yeongwol-Mill) 온라인 쇼핑몰 전체 코드베이스 및 비즈니스 아키텍처  
**최종 운영 준비도 판정**: 🛑 **NOT READY (실제 오픈 불가 - 8대 P0 및 Go-Live Gate 미충족)**  
**문서 성격**: 본 문서는 1차 감사, 2차 리뷰, 6대 명세 보정을 거쳐 최종 3대 보정(CANCEL_REQUESTED Reconciliation, Stale Outbox Recovery, Non-blocking Refund Saga 용어 정립, 16대 E2E Test)을 완료한 **최종 단일 진실 원천(Single Source of Truth) 개발 명세서**입니다.

---

# 1. Executive Summary

### Production Readiness: **NOT READY**

> **"이 쇼핑몰을 오늘 실제 고객에게 공개하고 실제 주문을 받기 시작해서는 안 됩니다."**
> 
> 현재 코드베이스는 기본 UI 시안 및 DB 구조, Atomic 재고 예약 쿼리가 작성되어 있으나, **[1] 결제창 이탈 시 0원 무료 결제 승인 결함**, **[2] PG 승인 취소 API 미연동(DB만 변경)**, **[3] 취소 시 재고 보상 미처리**, **[4] 무인증 IDOR 개인정보 노출 취약점**, **[5] 배송중 상태 주문의 불법 취소 허용**, **[6] 15분 미결제 재고 만료 자동 실행 주체 부재**, **[7] 관리자 대시보드 브라우저 JS 렌더링 에러**, **[8] `/complete` API의 PG REST API 재조회 미실시** 등 실제 오픈 시 금전 손실, 환불 오류, 법적 분쟁 및 CS 마비를 야기할 **8개의 P0(오픈 차단)** 결함이 존재합니다.

### 이슈 및 배포 체크포인트 구분

| 구분 | 정의 | 개수 및 성격 |
| :--- | :--- | :---: |
| 🚨 **P0 (오픈 차단 결함)** | 서비스 구현 중 즉시 발생할 수 있는 금전 손실, 개인정보 유출, 주문 처리 불능 결함 | **8개** |
| 🎯 **Go-Live Gate** | 코드 구현과 별개로 실제 서비스 공개(Open) 직전에 100% 충족되어야 하는 배포 체크포인트 | **12개** |
| ⚠️ **P1 (우선 기능)** | 마이페이지 조회, 실시간 배송조회 URL, SMS/LMS Outbox 알림 등 정상 운영 보완 | **7개** |
| 💡 **P2 / P3 (향후 보완)** | 리뷰, 평점, 쿠폰, 포인트, Audit Log, GA4 분석 등 성장 단계 기능 | **8개** |

---

# 2. 🚨 8대 LAUNCH BLOCKERS (P0 오픈 차단 결함)

| # | P0 결함명 | 실제 비즈니스/운영 영향 | 관련 코드 위치 | 필수 해결 방향 |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **결제창 이탈/취소 시 무료 결제 승인 결함** | 악의적 사용자가 결제창을 닫거나 카드 승인을 취소해도 프론트엔드가 `/complete`를 강제 호출하여 **0원에 무상 주문 승인 처리됨** | [checkout.html:L405](file:///c:/workspace/Yeongwol-Mill/web_app/static/checkout.html#L405) | JS catch/finally 절의 강제 `/complete` 호출 제거 및 백엔드 사전 승인 검증 필수화 |
| **2** | **`/complete` API의 PG REST API 재조회 검증 부재** | 클라이언트 파라미터만 신뢰하고 PG API 조회를 안 하여 **클라이언트를 결제의 Source of Truth로 사용함** | [payment.py:L212](file:///c:/workspace/Yeongwol-Mill/web_app/routes/payment.py#L212) | 백엔드가 PortOne REST API를 직접 조회하여 결제 상태(`paid`) 및 금액 100% 검증 시만 `PAID` 승인 |
| **3** | **PortOne PG 승인 취소 API 미연동** | 관리자가 주문 취소를 눌러도 DB 상태만 `REFUNDED`로 바뀔 뿐 **실제 PG 카드 승인이 취소되지 않아 돈이 환불 안 됨** | [payment.py:L232](file:///c:/workspace/Yeongwol-Mill/web_app/routes/payment.py#L232) | Two-step Non-blocking Refund Saga 기반 PortOne Cancel REST API 연동 |
| **4** | **주문 취소 시 시점별 재고 보상(Compensation) 누락** | 결제 전/후 취소 시점 구분 없이 재고 복구가 완전히 누락되어 **상품 재고 원장이 영구 불일치함** | [payment.py:L271](file:///c:/workspace/Yeongwol-Mill/web_app/routes/payment.py#L271) | `refunds.inventory_compensated` 플래그 기반 `PENDING`은 `reserved_stock` 차감, `CONFIRMED`는 `stock` 원상복구 |
| **5** | **GET `/api/orders/{no}` IDOR 무인증 개인정보 노출** | 주문번호만 알면 인증 없이 **모든 타인 고객의 수령인 이름, 연락처, 주소를 무단 열람 가능함** | [orders.py:L224](file:///c:/workspace/Yeongwol-Mill/web_app/routes/orders.py#L224) | 주문 단건 조회 시 JWT 토큰 또는 비회원 비밀번호 검증 미들웨어 필수화 |
| **6** | **배송 시작(`SHIPPING`) 이후 일반 주문 취소 허용** | 이미 상품이 택배 출고된 `SHIPPING` 주문도 취소 요청 시 **가드 없이 DB상 `CANCELLED` 처리되어 물품 손실** | [payment.py:L243](file:///c:/workspace/Yeongwol-Mill/web_app/routes/payment.py#L243) | 취소 API 호출 시 `order_status IN ('PENDING', 'CONFIRMED', 'PREPARING')` 상태만 취소 가능 가드 적용 |
| **7** | **15분 미결제 재고 예약 만료 자동 실행 주체 부재** | CLI 명령만 존재하고 자동 구동 Cron/스케줄러가 없어 **결제 이탈 시 재고가 영구 예약 상태로 묶임** | [cli.py:L32](file:///c:/workspace/Yeongwol-Mill/web_app/cli.py#L32) | systemd timer / OS Cron 기반 1분 주기 `flask expire-reservations` 실행 환경 구축 |
| **8** | **관리자 대시보드 브라우저 JS 렌더링 에러** | 백엔드 반환 JSON 객체 구조와 프론트엔드 JS 접근 키가 달라 **브라우저에서 `TypeError`로 화면 깨짐 및 사용 불능** | [admin.html:L431](file:///c:/workspace/Yeongwol-Mill/web_app/static/admin.html#L431)<br>[admin.py:L79](file:///c:/workspace/Yeongwol-Mill/web_app/routes/admin.py#L79) | `admin_dashboard()`의 JSON 데이터 구조를 `admin.html` JS 인터페이스와 1:1로 맞춤 동기화 |

---

# 3. 🎯 Go-Live Gate (실제 공개 전 100% 필수 체크포인트)

코드 개발 P0 항목과 별개로, 실제 운영 서비스를 공개(Go-Live)하기 전에 100% 완료되어야 하는 12대 배포 체크포인트입니다.

```text
[ Go-Live Checkpoints ]
 ├── 1. Nginx + Gunicorn + SSL (HTTPS) 적용 완료
 ├── 2. app.py 내 debug=False 설정 전환
 ├── 3. Production MySQL DB 서버 연결 및 인덱스 점검
 ├── 4. PortOne Production API Key / Secret / ChannelKey 환경변수 적용
 ├── 5. PortOne Webhook Production URL 등록 및 SSL 검증
 ├── 6. 실 테스트 결제 (100원 결제 승인) 검증 완료
 ├── 7. 실 카드 승인 취소 (100원 실제 환불) 검증 완료
 ├── 8. mysqldump + Cron 기반 일일 DB 백업 구축
 ├── 9. DB Restore 검증 완료 (백업파일을 Test DB에 복구 후 orders/payments/users row 정상 검증 1회 통과)
 ├── 10. systemd timer / Cron 기반 예약재고 만료 및 SMS Outbox 배치 정상 구동 확인
 ├── 11. 관리자 초기 비밀번호 변경 및 계정 보안화
 └── 12. Secret 보안 관리 (.gitignore 등록, 600 파일 권한, 로그 출력 금지, Dev/Prod Secret 분리)
```

---

# 4. Ecommerce Architecture & DB Schema 명세 및 마이그레이션

### Database Schema 마이그레이션 (DB Schema Migration)

코드에 정의될 상태 ENUM 및 추가 필드가 DB 스키마에 명시적으로 적용되어야 합니다.

```sql
-- 1. orders 테이블 payment_status ENUM / VARCHAR 확장
ALTER TABLE orders MODIFY COLUMN payment_status VARCHAR(30) NOT NULL DEFAULT 'READY';
-- 허용 상태값: READY, PAY_PENDING, PAID, CANCEL_REQUESTED, REFUND_PENDING, REFUND_FAILED, PARTIALLY_REFUNDED, REFUNDED, FAILED

-- 2. refunds 테이블 확장 (PortOne V2 수용 및 재고 보상 플래그 추가)
ALTER TABLE refunds 
    ADD COLUMN portone_cancellation_id VARCHAR(100) NULL AFTER cancellation_id,
    ADD COLUMN requested_amount INT NOT NULL DEFAULT 0 AFTER amount,
    ADD COLUMN confirmed_amount INT NOT NULL DEFAULT 0 AFTER requested_amount,
    ADD COLUMN current_cancellable_amount INT NULL AFTER confirmed_amount,
    ADD COLUMN inventory_compensated TINYINT(1) NOT NULL DEFAULT 0 AFTER status,
    ADD COLUMN inventory_compensated_at DATETIME NULL AFTER inventory_compensated;

-- 3. notifications 테이블 신규 생성 (Transactional Outbox)
CREATE TABLE IF NOT EXISTS notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL, -- ORDER_PAID, ORDER_SHIPPED, ORDER_REFUNDED, ADMIN_NEW_ORDER, REFUND_FAILED, REFUND_REVIEW_REQUIRED
    order_id INT NULL,
    recipient VARCHAR(50) NOT NULL, -- 실제 발송용 전화번호 (마스킹 금지)
    provider VARCHAR(30) NOT NULL DEFAULT 'SOLAPI',
    message_type VARCHAR(10) NOT NULL DEFAULT 'SMS', -- SMS, LMS
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSING, SENT, FAILED
    provider_message_id VARCHAR(100) NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    last_attempt_at DATETIME NULL,
    next_retry_at DATETIME NULL,
    error_code VARCHAR(50) DEFAULT '',
    error_message TEXT,
    idempotency_key VARCHAR(100) NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    sent_at DATETIME NULL,
    INDEX idx_notifications_order_id (order_id),
    INDEX idx_notifications_status_retry (status, next_retry_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

---

# 5. 주문 & 환불 State Machine 완결 설계 (Two-step Non-blocking Refund Saga)

### 1) 주문 승인 권한 (Source of Truth) 확립

> **원칙: 클라이언트는 절대로 `PAID` 승인 권한을 갖지 않습니다.**  
> 오직 서버가 **(1) Webhook Signature 검증 + (2) paymentId/order 매핑 검증 + (3) status=PAID 검증 + (4) 실제 결제금액 100% 검증 + (5) Idempotency 검증**을 완료하거나, 사후 검증 API에서 서버가 PortOne REST API를 직접 조회하여 위 조건들을 모두 검증했을 때만 `PAID`로 전환합니다.

### 2) Two-step Refund Saga & Crash/Timeout Reconciliation

DB Lock을 잡은 상태로 외부 PG HTTP 통신을 수행하면 통신 지연 시 DB Connection이 마비됩니다. 이에 따라 **Two-step Non-blocking Refund Saga** 아키텍처로 설계합니다.

```text
[ Transaction A (DB Lock 획득 및 선 반영) ]
   1. SELECT ... FOR UPDATE (주문 상태 및 취소가능금액 검증)
   2. orders.payment_status = 'CANCEL_REQUESTED'
   3. refunds 레코드 생성 (status = 'PENDING', refund_request_id 생성, requested_amount 기록)
   4. COMMIT (DB Row Lock 즉시 해제)

[ External HTTP Request (Non-blocking) ]
   5. PortOne REST API (/payments/{paymentId}/cancel) 호출 (currentCancellableAmount 검증 포함)

[ Transaction B (결과 반영 및 재고 원자적 보상) ]
   6. SELECT refunds WHERE id = ? FOR UPDATE
   7. PG 응답 결과 판정:
      ├── [성공 (Success)]
      │    ↳ PG 응답의 portone_cancellation_id, confirmed_amount 저장
      │    ↳ IF inventory_compensated == 0:
      │           stock 복구 (CONFIRMED 상태 건)
      │           inventory_compensated = 1, inventory_compensated_at = NOW()
      │    ↳ refunds.status = 'COMPLETED'
      │    ↳ orders.payment_status = 'REFUNDED', order_status = 'CANCELLED'
      │    ↳ Outbox에 ORDER_REFUNDED:{order_id} SMS 등록
      │
      ├── [명확한 PG 실패 (Explicit Failure)]
      │    ↳ orders.payment_status = 'REFUND_FAILED'
      │    ↳ refunds.status = 'FAILED', error_message 저장
      │    ↳ Outbox에 REFUND_FAILED:{refund_id} 관리자 SMS 등록
      │
      └── [Network Timeout / 서버 Crash / 불확실 (Unknown)]
           ↳ orders.payment_status = 'REFUND_PENDING' (또는 CANCEL_REQUESTED 유지)
           ↳ refunds.status = 'PENDING' (고객 환불완료 SMS 발송 금지)
           ↳ PG Refund Reconciliation Job이 PortOne 상태 재조회 후 성공/실패 확정
           ↳ (30분 이상 미해결 시 REFUND_REVIEW_REQUIRED 관리자 SMS 발송)
   8. COMMIT
```

### 3) CANCEL_REQUESTED & REFUND_PENDING Reconciliation 복구 배치
Transaction A 완료 후 Python 프로세스가 강제 종료되거나 Timeout 발생 시 고립되는 건을 해결합니다.
* **배치 대상**:
  - `CANCEL_REQUESTED` 상태로 5분 이상 경과된 환불건
  - `REFUND_PENDING` 상태로 5분 이상 경과된 환불건
* **복구 로직**: PortOne 결제 상세 조회 API를 호출하여 해당 `payment_id`의 실제 취소 내역(cancellation) 존재 여부 검증 ➔ 실제 취소 성공 시 `REFUNDED` 및 재고 1회 보상 / 취소 미발생 시 `REFUND_FAILED` 처리.

---

# 6. 시점별 원자적 재고 보상 설계 (Idempotent Inventory Compensation)

재고 보상 여부를 `payment_status`로 추론하면 `REFUNDED`로 변경되자마자 스킵되는 결함이 생깁니다. 따라서 **`refunds.inventory_compensated` 전용 DB 컬럼**으로 관리합니다.

### 1) 취소 시점별 재고 처리 룰

* **결제 전 취소 (`PENDING` / `READY`)**:
  ```sql
  UPDATE stock_reservations SET status = 'RELEASED' WHERE order_id = ? AND status = 'RESERVED';
  UPDATE product_options SET reserved_stock = CASE WHEN reserved_stock >= ? THEN reserved_stock - ? ELSE 0 END WHERE id = ?;
  /* stock(물리재고)은 변경하지 않음 */
  ```
* **결제 완료 후 출고 전 취소 (`CONFIRMED` / `PREPARING`)**:
  ```sql
  /* refunds.inventory_compensated = 0 확인 후 1회만 물리재고 복구 */
  UPDATE product_options SET stock = stock + ? WHERE id = ?;
  UPDATE refunds SET inventory_compensated = 1, inventory_compensated_at = NOW() WHERE id = ?;
  ```
* **배송 후 반품 (`SHIPPING` / `DELIVERED`)**:
  일반 취소 API 사용을 엄격히 차단하며, 반품 접수(`RETURN_REQUESTED`) 후 식품 검수를 거쳐 재판매 가능 판정을 받은 경우에만 관리자가 수동 재고 복구를 수행합니다.

---

# 7. 📱 Transactional Outbox 기반 SMS/LMS Notification System 명세

### 1) Worker 동시 실행 레이스 조건 방지 & Stale Processing Recovery

Worker가 2개 이상 구동되거나 프로세스가 Crash 되어 동일 문자가 중복 전송되거나 묶이는 현상을 차단합니다.

```text
[ Notification Outbox Flow & Recovery ]
   1. [일반 처리]
      SELECT * FROM notifications 
      WHERE status = 'PENDING' AND (next_retry_at IS NULL OR next_retry_at <= NOW())
   
   2. [Stale Recovery (프로세스 Crash 복구)]
      UPDATE notifications 
      SET status = 'PENDING', next_retry_at = NOW() 
      WHERE status = 'PROCESSING' AND last_attempt_at < NOW() - INTERVAL 10 MINUTE;

   3. [전점 권한 획득]
      UPDATE notifications 
      SET status = 'PROCESSING', last_attempt_at = NOW(), attempt_count = attempt_count + 1 
      WHERE id = ? AND status = 'PENDING';

   4. affected_rows == 1 인 Worker만 전점 권한을 얻어 실제로 SmsProvider.send() 호출!
   5. 결과 수신:
      ├── 성공 ➔ status = 'SENT', sent_at = NOW()
      └── 실패 ➔ attempt_count >= 3 ➔ status = 'FAILED'
                 attempt_count < 3  ➔ status = 'PENDING', next_retry_at = NOW() + 5분
```
* **발송 보장 성격**: SMS 시스템은 At-Least-Once + Provider Client Reference/Idempotency Identifier 사용으로 중복 발송을 최소화합니다.

### 2) 5대 이벤트 & Idempotency Key & 마스킹 정책

* **이벤트**: `ORDER_PAID`, `ORDER_SHIPPED`, `ORDER_REFUNDED`, `ADMIN_NEW_ORDER`, `REFUND_FAILED` (Timeout/Unknown 시 문자 발송 금지, 30분 초과 미해결 시 `REFUND_REVIEW_REQUIRED`).
* **Idempotency Key**: `ORDER_PAID:{order_id}`, `ORDER_SHIPPED:{order_id}`, `ORDER_REFUNDED:{order_id}`, `ADMIN_NEW_ORDER:{order_id}`, `REFUND_FAILED:{refund_id}`.
* **마스킹 정책**: **DB에는 실제 발송용 전화번호(`01012345678`)를 마스킹 없이 저장** (재시도 가능성 보장). 개인정보 마스킹(`010-****-5678`)은 **Application Log 및 관리자 UI 화면 출력 시에만 적용**.

---

# 8. 8대 시스템 불변조건 (Invariants) & 12대 Production 검증

### 8대 시스템 불변조건 검증

| 불변조건 (Invariant) | 코드 검증 결과 | 상태 | 조치 방향 |
| :--- | :--- | :---: | :--- |
| **Invariance 1. PG 실제 결제 검증 없이 `PAID` 전환 금지** | `checkout.html` 결제창 닫아도 `/complete` 호출 + `payment.py` `/complete`에서 PG REST API 미조회 | **🔴 VIOLATED** | 클라이언트 결제 승인 권한 완전 박탈 및 백엔드 PG REST API 재조회 필수화 |
| **Invariance 2. 동일 요청 중복 호출 시 Idempotency 보장** | Webhook은 Unique Key 검증하나 `/cancel` 중복 호출 시 DB `refunds` 중복 생성 및 재고 락 부재 | **⚠️ PARTIAL** | `notifications` Outbox 및 `inventory_compensated` 플래그 적용 |
| **Invariance 3. 결제 전/후 취소 시점별 재고 분리 보상** | 현재 취소 API는 `reserved_stock`이나 `stock` 재고 조정을 전혀 안 함 | **🔴 VIOLATED** | `PENDING`은 예약재고, `CONFIRMED`는 물리재고 복구 |
| **Invariance 4. PG 취소 성공과 DB Refund 상태 일치** | `payment.py` `/cancel`에서 PG Cancel API를 안 부르고 DB만 `REFUNDED`로 바꿈 | **🔴 VIOLATED** | Two-step Refund Saga 기반 PortOne REST API 호출 구현 |
| **Invariance 5. 배송 시작 이후 일반 주문 취소 차단** | `payment.py` `/cancel`에서 `order_status IN ('SHIPPING', 'DELIVERED')` 가드 조건 없음 | **🔴 VIOLATED** | 출고된 배송중 주문 취소 요청 시 400/409 차단 가드 적용 |
| **Invariance 6. PG/DB Partial Failure 시나리오 대응** | 2-Phase Commit (`CANCEL_REQUESTED -> PG Cancel -> REFUNDED/REFUND_FAILED/REFUND_PENDING`) 미구현 | **🔴 VIOLATED** | CANCEL_REQUESTED 및 REFUND_PENDING 대상 Reconciliation Job 구현 |
| **Invariance 7. 외부 알림 실패의 주문 트랜잭션 격리** | 현재 알림 시스템 미구현 | **⚪ N/A** | Transactional Outbox 패턴으로 완전 격리 |
| **Invariance 8. 모든 금전 및 재고 API의 Idempotent 보상** | 중복 환불 및 중복 재고 복구 방지 Lock 없음 | **⚠️ PARTIAL** | DB Row Lock 및 Idempotency Key 적용 |

---

# 9. 25대 핵심 질문 종합 답변

* **Q1. 오늘 실제 고객에게 공개해도 되는가?** ➔ **절대 불가 (NOT READY)**. (8대 P0 결함 및 Go-Live Gate 미충족)
* **Q2. 실제 돈을 받기 전 반드시 수정해야 하는 것은?** ➔ P0 8대 결함 (결제 무결성, PG 승인 취소, 재고 보상, IDOR, 취소 가드 등).
* **Q3. 신규 주문 시 관리자 알림 방식은?** ➔ Transactional Outbox 기반 `ADMIN_NEW_ORDER` SMS 발송 (`PAID` 확정 후만 발송).
* **Q5. 송장번호 등록 기능이 있는가?** ➔ **예**, Admin UI 및 `/api/admin/orders/<id>/shipping` API가 존재하여 `SHIPPING` 전환 가능.
* **Q6. 배송 Tracking API 연결 여부는?** ➔ 1차 오픈 시 마이페이지 내 택배사 배송조회 URL 연결로 구현.
* **Q8. 배송 완료를 자동으로 알 수 있는가?** ➔ 출고 7일 자동 전환은 배제하며, 마이페이지 배송조회 URL 및 관리자 수동 배송완료 API로 연동.
* **Q9. 주문 취소 시 실제 PG 결제까지 취소되는가?** ➔ 현재는 안 됨. Two-step Refund Saga 기반 PortOne Cancel API 연동 필수.
* **Q10. 취소 시 재고가 복구되는가?** ➔ 현재는 안 됨. 시점별 원자적 재고 보상 SQL 반영 필수.
* **Q15. 동시 주문 Overselling 차단 여부는?** ➔ **차단됨 (IMPLEMENTED)**. (`orders.py`에서 Atomic UPDATE `stock - reserved >= qty` 쿼리로 안전 보장).
* **Q17. IDOR 개인정보 노출 문제가 없는가?** ➔ **심각한 IDOR 존재**. (GET `/api/orders/<order_number>` 무인증 전면 노출 ➔ JWT/비밀번호 검증 필수).
* **Q22. 오픈 전 필수 계약 서비스는?** ➔ (1) PortOne PG 정식 계약, (2) Solapi/Aligo 등 SMS/LMS Provider 계약, (3) Nginx+SSL HTTPS 배포 서버 구축.

---

# 10. 🚀 Phase-by-Phase 순차적 개발 로드맵 & 16대 E2E 검증 테스트

개발 시 전체를 동시에 고치지 않고 **4단계 Phase**로 분할 구사하며, 각 Phase가 끝난 후 단위/통합 테스트를 100% PASS해야 다음 Phase로 진입합니다.

```text
[ PHASE 1 — 결제/금전 무결성 (Core Finance Integrity) ]
 ├── 1. DB Schema Migration 실행 (payment_status, refunds, notifications 확장)
 ├── 2. Client /complete 승인 권한 제거 & 백엔드 PG REST API 재조회 승인 검증 (Source of Truth)
 ├── 3. Two-step Refund Saga (CANCEL_REQUESTED ➔ PG Cancel ➔ REFUNDED/REFUND_FAILED/REFUND_PENDING)
 ├── 4. CANCEL_REQUESTED 및 REFUND_PENDING 대상 PG Refund Reconciliation 재검증 Job 구현
 └── 5. refunds.inventory_compensated 컬럼 기반 시점별 원자적 재고 보상 구현

[ PHASE 2 — 보안 및 주문 상태 가드 (Security & State Guards) ]
 ├── 6. GET /api/orders/{order_number} IDOR 인증 검증 데코레이터 적용
 ├── 7. SHIPPING (배송중) 및 DELIVERED (배송완료) 주문의 일반 취소 차단 가드 적용
 └── 8. admin.py /api/admin/orders/{id}/delivered 수동 배송완료 API 구현

[ PHASE 3 — 운영 안정성 (Operational Stability) ]
 ├── 9. systemd timer / OS Cron 기반 1분 주기 flask expire-reservations 배치 등록
 ├── 10. admin.py 대시보드 반환 JSON 키와 admin.html 인터페이스 동기화 (JS 에러 해결)
 └── 11. Production Config (Gunicorn + Nginx + SSL(HTTPS), debug=False, DB 백업 및 Restore 검증)

[ PHASE 4 — 운영 기능 (Operational Features) ]
 ├── 12. Transactional Outbox 기반 SMS/LMS Notification Engine (PROCESSING & Stale Recovery 적용)
 ├── 13. 마이페이지 회원 주문목록 (/api/orders/my) 구현 및 실시간 택배사 배송조회 URL 연결
 └── 14. Admin 상품/옵션 Soft Delete (ACTIVE/INACTIVE/SOLD_OUT/HIDDEN) 및 수동 재고 조정 구현
```

### 🧪 16대 E2E 자동 검증 테스트 시나리오 (E2E Test Suites)

1. **결제 미실행 취소 시**: `/complete` 호출되어도 DB가 절대 `PAID`로 변경되지 않음.
2. **정상 결제 승인 시**: PG 검증 성공 시 `PAID` 및 `CONFIRMED`가 정확히 1회 적용됨.
3. **Webhook 3회 중복 통지 시**: Idempotency Key에 의해 재고가 1회만 차감됨.
4. **환불 요청 3회 연속 클릭 시**: Non-blocking Lock에 의해 PortOne 취소가 1회만 호출됨.
5. **PG 환불 API 실패 시**: DB 재고가 복구되지 않고 `REFUND_FAILED` 기록됨.
6. **PG 환불 API 성공 시**: PG 승인 취소 확인 후 `inventory_compensated=1` 기록되며 물리 재고(`stock`)가 정확히 1회 복구됨.
7. **PG Cancel Network Timeout 발생 시**: `REFUND_PENDING`으로 저장되고 `REFUNDED`로 조기 단정하지 않음.
8. **배송중(`SHIPPING`) 주문 취소 시**: 취소 요청이 400/409 HTTP Error로 거부됨.
9. **예약 만료 Job과 결제 Webhook 동시 실행 시**: DB Lock에 의해 재고 Race Condition 없이 안전 처리됨.
10. **`REFUND_PENDING` 상태 재조회 성공 시**: Reconciliation Job이 `REFUNDED`로 정상 확정 및 재고 1회 복구.
11. **`REFUND_PENDING` 상태 재조회 실제 실패 시**: `REFUND_FAILED`로 처리되어 잘못된 환불 확정 방지.
12. **Outbox Worker 2개 동시 실행 시**: `PROCESSING` 선격리로 인해 동일 SMS가 1회만 발송됨.
13. **잘못된 결제금액 Webhook 들어올 시**: `AMOUNT_MISMATCH` 기록되며 절대 `PAID`로 처리되지 않음.
14. **회원 A가 회원 B 주문번호 무단 조회 시**: IDOR 차단 미들웨어에 의해 403/404 거부됨.
15. **PG Cancel 성공 직후 서버 프로세스 강제 종료 시**: `CANCEL_REQUESTED` 상태가 Reconciliation에 의해 자동 복구되어 최종 `REFUNDED` 전환 및 재고 1회 복구.
16. **SMS Worker가 `PROCESSING` 변경 후 강제 종료 시**: Stale PROCESSING (10분 초과) 탐지 배치에 의해 `PENDING`으로 자동 복구되어 알림 영구 유실 방지.

---

# 11. 📋 PHASE 1 구현 및 산출물 제출 지침

개발 시작 시 Phase 1부터 4까지 한꺼번에 구현하지 않고, **PHASE 1 (결제/금전 무결성)**을 독자적인 단위 작업으로 수행합니다.

### PHASE 1 완료 보고 시 제출 필수 증적:
1. **변경된 파일 목록** (수정된 파이썬 파일 및 SQL 파일)
2. **실제 DB Schema Migration 수행 결과** (`orders`, `refunds`, `notifications` 스키마 캡처/출력)
3. **결제 및 환불 State Transition 증적** (`READY` ➔ `PAID`, `CANCEL_REQUESTED` ➔ `REFUNDED`/`REFUND_FAILED`/`REFUND_PENDING`)
4. **PortOne Mock REST API 호출 횟수 검증**
5. **각 E2E 테스트별 DB Before / After 스냅샷**
6. **16대 E2E 테스트 전체 PASS 로그**
