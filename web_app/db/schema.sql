-- MySQL Schema for 영월고향방앗간 (v2.2 Gold Master)

CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    price INT NOT NULL,
    capacity VARCHAR(50) DEFAULT '',
    description TEXT,
    badge VARCHAR(50) DEFAULT '',
    image_url VARCHAR(255),
    is_active TINYINT(1) DEFAULT 1,
    shelf_life_text VARCHAR(100) DEFAULT '제조일로부터 12개월',
    origin_info TEXT,
    food_type VARCHAR(100) DEFAULT '식용유지류',
    contents_capacity VARCHAR(100) DEFAULT '',
    raw_ingredients TEXT,
    manufacturer VARCHAR(100) DEFAULT '영월고향방앗간',
    storage_method VARCHAR(255) DEFAULT '직사광선을 피하고 서늘한 곳에 보관',
    allergy_notice VARCHAR(255) DEFAULT '참깨, 들깨 함유',
    nutrition_facts TEXT,
    cs_phone VARCHAR(50) DEFAULT '033-000-0000',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS product_options (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    option_name VARCHAR(100) NOT NULL DEFAULT 'DEFAULT',
    additional_price INT NOT NULL DEFAULT 0,
    stock INT NOT NULL DEFAULT 100,
    reserved_stock INT NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    INDEX idx_product_options_product_id (product_id),
    CONSTRAINT chk_stock_valid CHECK (reserved_stock >= 0 AND stock >= 0 AND reserved_stock <= stock)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NULL,
    name VARCHAR(50) NULL,
    phone VARCHAR(20) NULL,
    token_version INT NOT NULL DEFAULT 0,
    marketing_email_agreed TINYINT(1) NOT NULL DEFAULT 0,
    marketing_sms_agreed TINYINT(1) NOT NULL DEFAULT 0,
    marketing_email_updated_at DATETIME NULL,
    marketing_sms_updated_at DATETIME NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    deleted_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    used_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    request_ip VARCHAR(45) NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_reset_token_hash (token_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS admin_users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(50) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'ADMIN',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_number VARCHAR(50) NOT NULL UNIQUE,
    user_id INT NULL,
    guest_name VARCHAR(50),
    guest_phone VARCHAR(20),
    guest_password_hash VARCHAR(255),
    subtotal_amount INT NOT NULL DEFAULT 0,
    base_shipping_fee INT NOT NULL DEFAULT 0,
    remote_area_surcharge INT NOT NULL DEFAULT 0,
    discount_amount INT NOT NULL DEFAULT 0,
    total_amount INT NOT NULL,
    refund_calculation_mode VARCHAR(20) NOT NULL DEFAULT 'AUTO',
    order_status VARCHAR(30) NOT NULL DEFAULT 'PENDING', -- PENDING, CONFIRMED, PREPARING, SHIPPING, DELIVERED, CANCELLED
    payment_status VARCHAR(30) NOT NULL DEFAULT 'READY', -- READY, PAY_PENDING, PAID, PARTIALLY_REFUNDED, REFUNDED, FAILED
    integrity_status VARCHAR(50) NOT NULL DEFAULT 'NORMAL', -- NORMAL, AMOUNT_MISMATCH
    recipient_name VARCHAR(50) NOT NULL DEFAULT '',
    recipient_phone VARCHAR(20) NOT NULL DEFAULT '',
    postal_code VARCHAR(10) DEFAULT '',
    address VARCHAR(255) NOT NULL DEFAULT '',
    address_detail VARCHAR(255),
    delivery_memo VARCHAR(255),
    courier_name VARCHAR(50) DEFAULT '',
    tracking_number VARCHAR(100) DEFAULT '',
    shipped_at DATETIME NULL,
    delivered_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_orders_order_status (order_status, created_at),
    INDEX idx_orders_payment_status (payment_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    option_id INT NULL,
    product_name_snapshot VARCHAR(100) NOT NULL,
    option_name_snapshot VARCHAR(100) NOT NULL DEFAULT 'DEFAULT',
    capacity VARCHAR(50) DEFAULT '',
    quantity INT NOT NULL,
    cancelled_qty INT NOT NULL DEFAULT 0,
    shipped_qty INT NOT NULL DEFAULT 0,
    returned_qty INT NOT NULL DEFAULT 0,
    item_gross_amount BIGINT NULL,
    item_discount_allocated BIGINT NULL,
    item_paid_amount BIGINT NULL,
    unit_price INT NOT NULL,
    option_price INT NOT NULL DEFAULT 0,
    final_unit_price INT NOT NULL,
    subtotal INT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (option_id) REFERENCES product_options(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stock_reservations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    product_option_id INT NOT NULL,
    quantity INT NOT NULL,
    expires_at DATETIME NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'RESERVED', -- RESERVED, CONFIRMED, EXPIRED, RELEASED
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (product_option_id) REFERENCES product_options(id) ON DELETE CASCADE,
    INDEX idx_reservations_status_expires (status, expires_at),
    INDEX idx_reservations_order (order_id),
    CONSTRAINT chk_reservation_qty CHECK (quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    payment_id VARCHAR(100) NOT NULL,
    transaction_id VARCHAR(100) NULL UNIQUE,
    pg_provider VARCHAR(50) DEFAULT 'PORTONE',
    method VARCHAR(50) DEFAULT 'CARD',
    status VARCHAR(30) NOT NULL DEFAULT 'READY', -- READY, PAY_PENDING, PAID, FAILED
    amount INT NOT NULL,
    paid_at DATETIME NULL,
    failed_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    INDEX idx_payments_order_id (order_id),
    INDEX idx_payments_payment_id (payment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS refunds (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    payment_id VARCHAR(100) NOT NULL,
    refund_request_id VARCHAR(255) NOT NULL UNIQUE,
    cancellation_id VARCHAR(100) NULL UNIQUE,
    portone_cancellation_id VARCHAR(100) NULL,
    amount INT NOT NULL,
    requested_amount INT NOT NULL DEFAULT 0,
    confirmed_amount INT NOT NULL DEFAULT 0,
    current_cancellable_amount INT NULL,
    reason VARCHAR(255) DEFAULT '',
    requester VARCHAR(50) DEFAULT 'ADMIN',
    status VARCHAR(30) NOT NULL DEFAULT 'REQUESTED', -- REQUESTED, PENDING, COMPLETED, FAILED
    inventory_compensated TINYINT(1) NOT NULL DEFAULT 0,
    inventory_compensated_at DATETIME NULL,
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    pending_at DATETIME NULL,
    completed_at DATETIME NULL,
    failed_at DATETIME NULL,
    error_code VARCHAR(100) DEFAULT '',
    error_message TEXT,
    raw_response TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    INDEX idx_refunds_order_id (order_id),
    INDEX idx_refunds_payment_id (payment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    revoked_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS revoked_access_tokens (
    jti VARCHAR(255) PRIMARY KEY,
    expires_at DATETIME NOT NULL,
    revoked_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS webhook_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_key VARCHAR(100) NOT NULL UNIQUE,
    event_type VARCHAR(100) NOT NULL,
    payment_id VARCHAR(100),
    transaction_id VARCHAR(100),
    cancellation_id VARCHAR(100),
    payload TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'PROCESSED', -- PROCESSED, FAILED, IGNORED
    error_message TEXT,
    received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_webhook_payment_id (payment_id),
    INDEX idx_webhook_status_received (status, received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL, -- ORDER_PAID, ORDER_SHIPPED, ORDER_REFUNDED, ADMIN_NEW_ORDER, REFUND_FAILED, REFUND_REVIEW_REQUIRED
    order_id INT NULL,
    recipient VARCHAR(50) NOT NULL,
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

CREATE TABLE IF NOT EXISTS remote_shipping_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    postal_code_prefix VARCHAR(10) NOT NULL,
    region_name VARCHAR(100) NOT NULL,
    surcharge INT NOT NULL DEFAULT 3000
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS email_verifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(100) NOT NULL,
    code_hash VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    verified_at DATETIME NULL,
    consumed_at DATETIME NULL,
    attempt_count INT DEFAULT 0,
    last_sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email_verifications_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_consents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    consent_type VARCHAR(50) NOT NULL,
    action VARCHAR(20) NOT NULL DEFAULT 'AGREED',
    consent_version VARCHAR(50) NOT NULL DEFAULT 'marketing-2026-08-v1',
    agreed TINYINT(1) NOT NULL DEFAULT 1,
    agreed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_consents_user (user_id, consent_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notification_outbox (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    email VARCHAR(100) NULL,
    type VARCHAR(50) NULL,
    payload TEXT NULL,
    event_type VARCHAR(50) NULL,
    channel VARCHAR(20) NOT NULL DEFAULT 'EMAIL',
    recipient VARCHAR(100) NULL,
    payload_json JSON NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    retry_count INT NOT NULL DEFAULT 0,
    next_retry_at DATETIME NULL,
    dedup_key VARCHAR(100) NULL UNIQUE,
    last_error TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    sent_at DATETIME NULL,
    INDEX idx_outbox_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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


