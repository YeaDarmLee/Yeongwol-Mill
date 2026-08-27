"""
test_import_tracking_csv.py
운송장 일괄 CSV 업로드 기능 테스트 (15개 케이스)
"""
import io
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import app
from db.db_connection import get_db_connection, query_db
from middlewares.auth import generate_jwt_token, hash_password


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def admin_token():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM admin_users WHERE email = 'csv_test@test.com'")
            admin = cursor.fetchone()
            if not admin:
                ph = hash_password("test123!")
                cursor.execute(
                    "INSERT INTO admin_users (email, password_hash, name, role) VALUES (%s, %s, 'csv_tester', 'ADMIN')",
                    ("csv_test@test.com", ph)
                )
                conn.commit()
                cursor.execute("SELECT * FROM admin_users WHERE email = 'csv_test@test.com'")
                admin = cursor.fetchone()
        return generate_jwt_token(admin["id"], admin["email"], role=admin["role"])
    finally:
        conn.close()


def _create_ready_to_ship_order(suffix=""):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM categories LIMIT 1")
            cat_row = cursor.fetchone()
            cat_id = cat_row["id"] if cat_row else None
            if not cat_id:
                cursor.execute("INSERT INTO categories (name) VALUES ('기타')")
                cat_id = cursor.lastrowid

            cursor.execute("SELECT id FROM users WHERE email = 'csv_wf_user@test.com'")
            u_row = cursor.fetchone()
            user_id = u_row["id"] if u_row else None
            if not user_id:
                cursor.execute(
                    "INSERT INTO users (email, name, phone, status) VALUES ('csv_wf_user@test.com', 'CSV유저', '010-9999-0000', 'ACTIVE')"
                )
                user_id = cursor.lastrowid

            ts = int(datetime.datetime.now().timestamp() * 1000)
            order_number = f"CSV-{ts}{suffix}"
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute(
                "INSERT INTO orders (order_number, user_id, total_amount, order_status, payment_status, "
                "recipient_name, recipient_phone, created_at) "
                "VALUES (%s, %s, 30000, 'READY_TO_SHIP', 'PAID', '테스트수령인', '010-0000-1234', %s)",
                (order_number, user_id, now_str)
            )
            order_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO shipments (order_id, purpose, status) VALUES (%s, 'FULFILLMENT', 'READY')",
                (order_id,)
            )
            shipment_id = cursor.lastrowid
            conn.commit()
            return order_id, shipment_id, order_number
    finally:
        conn.close()


def _make_csv_bytes(rows, header=True, encoding="utf-8-sig", with_comments=True):
    lines = []
    if with_comments:
        lines += [
            "# [주의] shipment_id와 order_number는 절대 수정하지 마세요.",
            "# carrier_code 허용값: CJ / LOTTE / HANJIN / POST / LOGEN / EPOST",
            "# tracking_number는 문자열로 입력하세요."
        ]
    if header:
        lines.append("shipment_id,order_number,recipient_name,recipient_phone,carrier_code,tracking_number")
    for row in rows:
        lines.append(",".join(str(c) for c in row))
    return "\n".join(lines).encode(encoding)


def _upload(client, token, csv_bytes, filename="test.csv"):
    return client.post(
        "/api/admin/orders/import-tracking-csv",
        data={"file": (io.BytesIO(csv_bytes), filename)},
        headers={"Authorization": f"Bearer {token}"},
        content_type="multipart/form-data"
    )


# TC-01: UTF-8 BOM 정상 Import
def test_tc01_utf8_bom(client, admin_token):
    _, sid, onum = _create_ready_to_ship_order("01")
    resp = _upload(client, admin_token, _make_csv_bytes([(sid, onum, "", "", "CJ", "1234567890")], encoding="utf-8-sig"))
    assert resp.status_code == 200
    assert resp.get_json()["success"] == 1


# TC-02: CP949 정상 Import
def test_tc02_cp949(client, admin_token):
    _, sid, onum = _create_ready_to_ship_order("02")
    resp = _upload(client, admin_token, _make_csv_bytes([(sid, onum, "홍길동", "", "LOTTE", "9876543210")], encoding="cp949"))
    assert resp.status_code == 200
    assert resp.get_json()["success"] == 1


# TC-03: quoted comma 파싱
def test_tc03_quoted_comma(client, admin_token):
    _, sid, onum = _create_ready_to_ship_order("03")
    raw = (
        "# comment\n"
        "shipment_id,order_number,recipient_name,recipient_phone,carrier_code,tracking_number\n"
        f'{sid},{onum},"김,철수","010-2222-3333",CJ,0011223344\n'
    )
    resp = _upload(client, admin_token, raw.encode("utf-8-sig"))
    assert resp.status_code == 200
    assert resp.get_json()["success"] == 1


# TC-04: 필수 헤더 누락 → 400
def test_tc04_missing_header(client, admin_token):
    raw = "shipment_id,order_number,carrier_code\n1,X,CJ\n"
    resp = _upload(client, admin_token, raw.encode("utf-8-sig"))
    assert resp.status_code == 400
    assert "tracking_number" in resp.get_json().get("error", "")


# TC-05: 동일 shipment_id 중복 → DUPLICATE_SHIPMENT
def test_tc05_duplicate_shipment_id(client, admin_token):
    _, sid, onum = _create_ready_to_ship_order("05")
    csv_bytes = _make_csv_bytes([(sid, onum, "", "", "CJ", "111"), (sid, onum, "", "", "CJ", "222")])
    resp = _upload(client, admin_token, csv_bytes)
    assert resp.status_code == 200
    reasons = [r["reason"] for r in resp.get_json()["results"] if not r["success"] and not r["skipped"]]
    assert "DUPLICATE_SHIPMENT" in reasons


# TC-06: 동일 order_number + 다른 shipment_id → 허용
def test_tc06_same_order_diff_shipment_allowed(client, admin_token):
    oid, sid_a, onum = _create_ready_to_ship_order("06")
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO shipments (order_id, purpose, status) VALUES (%s, 'FULFILLMENT', 'READY')", (oid,))
            sid_b = cursor.lastrowid
            conn.commit()
    finally:
        conn.close()
    csv_bytes = _make_csv_bytes([(sid_a, onum, "", "", "CJ", "111111"), (sid_b, onum, "", "", "HANJIN", "222222")])
    resp = _upload(client, admin_token, csv_bytes)
    assert resp.status_code == 200
    assert resp.get_json()["success"] == 2


# TC-07: 잘못된 carrier_code → INVALID_CARRIER
def test_tc07_invalid_carrier(client, admin_token):
    _, sid, onum = _create_ready_to_ship_order("07")
    resp = _upload(client, admin_token, _make_csv_bytes([(sid, onum, "", "", "롯데택베", "999999")]))
    assert resp.status_code == 200
    assert resp.get_json()["results"][0]["reason"] == "INVALID_CARRIER"


# TC-08: 빈 tracking_number → TRACKING_REQUIRED
def test_tc08_empty_tracking(client, admin_token):
    _, sid, onum = _create_ready_to_ship_order("08")
    resp = _upload(client, admin_token, _make_csv_bytes([(sid, onum, "", "", "CJ", "")]))
    assert resp.status_code == 200
    assert resp.get_json()["results"][0]["reason"] == "TRACKING_REQUIRED"


# TC-09: SHIPPED Shipment → INVALID_SHIPMENT_STATUS (건너뜀, NOT NOT_FOUND)
def test_tc09_shipped_shipment_skipped(client, admin_token):
    _, sid, onum = _create_ready_to_ship_order("09")
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE shipments SET status = 'SHIPPED' WHERE id = %s", (sid,))
            conn.commit()
    finally:
        conn.close()
    resp = _upload(client, admin_token, _make_csv_bytes([(sid, onum, "", "", "CJ", "123456")]))
    assert resp.status_code == 200
    r = resp.get_json()["results"][0]
    assert r["skipped"] is True
    assert r["reason"] == "INVALID_SHIPMENT_STATUS"


# TC-10: order_number 불일치 → ORDER_MISMATCH
def test_tc10_order_mismatch(client, admin_token):
    _, sid, _ = _create_ready_to_ship_order("10")
    resp = _upload(client, admin_token, _make_csv_bytes([(sid, "WRONG-999999", "", "", "CJ", "123456")]))
    assert resp.status_code == 200
    assert resp.get_json()["results"][0]["reason"] == "ORDER_MISMATCH"


# TC-11: # 주석 포함 Template 재업로드 → 정상 파싱
def test_tc11_template_with_comments(client, admin_token):
    _, sid, onum = _create_ready_to_ship_order("11")
    raw = (
        "# [주의] shipment_id와 order_number는 절대 수정하지 마세요. 수정 시 오등록됩니다.\n"
        "# carrier_code 허용값: CJ / EPOST / HANJIN / LOGEN / LOTTE / POST\n"
        "# tracking_number는 문자열로 입력하세요. 앞자리 0이 사라지지 않도록 주의하세요.\n"
        "shipment_id,order_number,recipient_name,recipient_phone,carrier_code,tracking_number\n"
        f"{sid},{onum},테스트수령인,010-0000-1234,POST,0011223344\n"
    )
    resp = _upload(client, admin_token, raw.encode("utf-8-sig"))
    assert resp.status_code == 200
    assert resp.get_json()["success"] == 1


# TC-12: 일부 성공/실패 혼합 (Partial Batch)
def test_tc12_partial_batch(client, admin_token):
    _, sid_ok, ord_ok = _create_ready_to_ship_order("12OK")
    _, sid_bad, ord_bad = _create_ready_to_ship_order("12BAD")
    csv_bytes = _make_csv_bytes([
        (sid_ok, ord_ok, "", "", "CJ", "111111"),
        (sid_bad, ord_bad, "", "", "잘못된", "222222"),
    ])
    resp = _upload(client, admin_token, csv_bytes)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] == 1
    assert data["failed"] == 1


# TC-13: AuditLog TRACKING_CSV_IMPORTED 생성
def test_tc13_audit_log(client, admin_token):
    _, sid, onum = _create_ready_to_ship_order("13")
    resp = _upload(client, admin_token, _make_csv_bytes([(sid, onum, "", "", "LOGEN", "555555")]))
    assert resp.status_code == 200
    assert resp.get_json()["success"] == 1
    logs = query_db("SELECT * FROM admin_audit_logs WHERE action_type = 'TRACKING_CSV_IMPORTED' AND target_id = %s", (sid,))
    assert logs and len(logs) >= 1


# TC-14: Shipment = Source of Truth (앞자리 0 보존)
def test_tc14_shipment_source_of_truth(client, admin_token):
    oid, sid, onum = _create_ready_to_ship_order("14")
    tracking = "00998877665"
    resp = _upload(client, admin_token, _make_csv_bytes([(sid, onum, "", "", "EPOST", tracking)]))
    assert resp.status_code == 200
    assert resp.get_json()["success"] == 1
    ships = query_db("SELECT * FROM shipments WHERE id = %s", (sid,))
    assert ships[0]["tracking_number"] == tracking
    assert ships[0]["carrier_code"] == "EPOST"
    orders = query_db("SELECT tracking_number FROM orders WHERE id = %s", (oid,))
    assert orders[0]["tracking_number"] == tracking


# TC-15: 5MB 초과 파일 → 400
def test_tc15_file_too_large(client, admin_token):
    oversized = b"x" * (5 * 1024 * 1024 + 1)
    resp = _upload(client, admin_token, oversized, filename="big.csv")
    assert resp.status_code == 400
    assert "MB" in resp.get_json().get("error", "")

