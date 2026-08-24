-- v2.3 Admin System Upgrade Migration Schema
-- 영월고향방앗간 P0-A/P0-B 관리자 시스템 및 멱등 환불 스키마 업그레이드

-- 1. orders 테이블 컬럼 추가
ALTER TABLE orders 
ADD COLUMN IF NOT EXISTS refund_calculation_mode VARCHAR(20) NOT NULL DEFAULT 'AUTO';

-- 2. order_items 테이블 컬럼 추가 및 수량 검증 제약 조건
ALTER TABLE order_items 
ADD COLUMN IF NOT EXISTS cancelled_qty INT NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS shipped_qty INT NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS returned_qty INT NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS item_gross_amount BIGINT NULL,
ADD COLUMN IF NOT EXISTS item_discount_allocated BIGINT NULL,
ADD COLUMN IF NOT EXISTS item_paid_amount BIGINT NULL;

-- 3. 1대N 환불 테이블 refund_requests 및 refund_request_items 생성
CREATE TABLE IF NOT EXISTS refund_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    operation_id VARCHAR(64) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(64) NOT NULL,
    portone_payment_id VARCHAR(100) NULL,
    portone_cancellation_id VARCHAR(100) NULL,
    requested_amount BIGINT NOT NULL,
    confirmed_refund_amount BIGINT NULL,
    cancellable_amount_before BIGINT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    reason VARCHAR(255) NOT NULL,
    last_error_message TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE RESTRICT,
    UNIQUE KEY uk_refund_operation (operation_id),
    UNIQUE KEY uk_refund_idempotency (idempotency_key),
    KEY idx_refund_reconciliation (status, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS refund_request_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    refund_request_id INT NOT NULL,
    order_item_id INT NOT NULL,
    requested_qty INT NOT NULL,
    refund_amount BIGINT NOT NULL,
    inventory_compensation_qty INT NOT NULL DEFAULT 0,
    FOREIGN KEY (refund_request_id) REFERENCES refund_requests(id) ON DELETE CASCADE,
    FOREIGN KEY (order_item_id) REFERENCES order_items(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. 재고 불변 이력 테이블 inventory_transactions 생성 (RESTRICT)
CREATE TABLE IF NOT EXISTS inventory_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_option_id INT NOT NULL,
    change_qty INT NOT NULL,
    previous_stock INT NOT NULL,
    current_stock INT NOT NULL,
    reason_code VARCHAR(30) NOT NULL,
    source_type VARCHAR(30) NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    source_line_id VARCHAR(64) NOT NULL DEFAULT 'MAIN',
    movement_type VARCHAR(30) NOT NULL DEFAULT 'CANCEL_RESTOCK',
    admin_id INT NULL,
    memo VARCHAR(255) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_option_id) REFERENCES product_options(id) ON DELETE RESTRICT,
    UNIQUE KEY uk_inventory_source_line (source_type, source_id, source_line_id, movement_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. 반품 클레임 return_claims, return_items, return_item_dispositions 생성
CREATE TABLE IF NOT EXISTS return_claims (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    claim_number VARCHAR(64) NOT NULL UNIQUE,
    claim_reason_code VARCHAR(30) NOT NULL,
    shipping_fee_payer VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'RETURN_REQUESTED',
    admin_memo TEXT NULL,
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS return_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    return_claim_id INT NOT NULL,
    order_item_id INT NOT NULL,
    requested_qty INT NOT NULL,
    approved_qty INT NOT NULL,
    received_qty INT NOT NULL,
    FOREIGN KEY (return_claim_id) REFERENCES return_claims(id) ON DELETE RESTRICT,
    FOREIGN KEY (order_item_id) REFERENCES order_items(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS return_item_dispositions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    return_item_id INT NOT NULL,
    disposition VARCHAR(30) NOT NULL,
    quantity INT NOT NULL,
    FOREIGN KEY (return_item_id) REFERENCES return_items(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. 관리자 운영 감사로그 admin_audit_logs 생성 (고객 PII 저장 금지 Allowlist)
CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    admin_id INT NOT NULL,
    admin_email VARCHAR(100) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    target_type VARCHAR(50) NULL,
    target_id VARCHAR(50) NULL,
    request_id VARCHAR(64) NULL,
    before_data JSON NULL,
    after_data JSON NULL,
    reason VARCHAR(255) NULL,
    result VARCHAR(20) NOT NULL,
    record_count INT DEFAULT 0,
    request_ip VARCHAR(45) NOT NULL,
    user_agent VARCHAR(255) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. 비동기 알림 아웃박스 notification_outbox 생성 (dedup_key UNIQUE)
CREATE TABLE IF NOT EXISTS notification_outbox (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    channel VARCHAR(20) NOT NULL,
    recipient VARCHAR(100) NOT NULL,
    payload_json JSON NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    retry_count INT DEFAULT 0,
    next_retry_at DATETIME NULL,
    dedup_key VARCHAR(100) NOT NULL UNIQUE,
    last_error TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    sent_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
