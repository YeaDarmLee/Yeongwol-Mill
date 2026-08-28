import sys
import os
import click
import datetime
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db.db_connection import query_db, execute_db, get_db_connection

def register_cli_commands(app):
    """Flask 커스텀 CLI 명령어를 등록합니다."""

    @app.cli.command("create-admin")
    @click.option("--email", prompt="관리자 이메일", help="관리자 로그인 이메일 계정")
    @click.option("--name", prompt="관리자 이름", help="관리자 성함")
    @click.option("--password", prompt="관리자 비밀번호", hide_input=True, confirmation_prompt=True, help="비밀번호")
    def create_admin(email, name, password):
        """인터랙티브 CLI 기반 관리자 계정 생성"""
        existing = query_db("SELECT * FROM admin_users WHERE email = %s", (email,), one=True)
        if existing:
            click.echo(f"오류: 이미 존재하 관리자 이메일입니다: {email}")
            return

        pw_hash = generate_password_hash(password, method='pbkdf2:sha256')
        admin_id = execute_db("""
            INSERT INTO admin_users (email, name, password_hash, role)
            VALUES (%s, %s, %s, 'ADMIN')
        """, (email, name, pw_hash))

        click.echo(f"성공: 관리자 계정(ID: {admin_id}, 이메일: {email})이 성공적으로 생성되었습니다!")

    @app.cli.command("expire-reservations")
    def expire_reservations():
        """15분 이상 경과한 미결제 재고 예약을 원자적으로 만료 해제합니다."""
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        expired_reservations = query_db("""
            SELECT * FROM stock_reservations 
            WHERE status = 'RESERVED' AND expires_at < %s
        """, (now_str,))

        if not expired_reservations:
            click.echo("만료 대상 재고 예약이 없습니다.")
            return

        count = 0
        for res in expired_reservations:
            conn = get_db_connection()
            try:
                adapted_res = query_db("SELECT * FROM stock_reservations WHERE id = %s AND status = 'RESERVED'", (res['id'],), one=True)
                if adapted_res:
                    # 1. 예약 상태 EXPIRED로 변경
                    execute_db("UPDATE stock_reservations SET status = 'EXPIRED' WHERE id = %s", (res['id'],))
                    # 2. reserved_stock 원자적 해제
                    execute_db("""
                        UPDATE product_options 
                        SET reserved_stock = CASE WHEN reserved_stock >= %s THEN reserved_stock - %s ELSE 0 END 
                        WHERE id = %s
                    """, (res['quantity'], res['quantity'], res['product_option_id']))
                    count += 1
            except Exception as e:
                click.echo(f"예약 ID {res['id']} 만료 처리 중 에러: {e}")
            finally:
                conn.close()

        click.echo(f"성공: 총 {count}건의 미결제 재고 예약이 만료 해제(reserved_stock 복구)되었습니다.")

    @app.cli.command("reconcile-refunds")
    def reconcile_refunds_cmd():
        """REFUND_PENDING 및 CANCEL_REQUESTED 대상 PG Refund Reconciliation 실행"""
        from routes.payment import reconcile_pending_refunds
        count = reconcile_pending_refunds()
        click.echo(f"성공: 총 {count}건의 환불 대사 및 상태 복구가 처리되었습니다.")

    @app.cli.command("process-notifications")
    @click.option("--batch-size", default=10, help="한 번에 발송할 notification_jobs 수")
    @click.option("--worker-id", default="worker-1", help="Worker ID")
    def process_notifications_cmd(batch_size, worker_id):
        """PENDING 알림을 Claim하여 알리고 API로 1:1 발송합니다."""
        from services.notification_service import NotificationService
        count = NotificationService().process_pending_jobs(batch_size=batch_size, worker_id=worker_id)
        click.echo(f"성공: 총 {count}건의 알림 발송 처리(Aligo Dispatched)가 완료되었습니다.")

    @app.cli.command("reconcile-notifications")
    @click.option("--batch-size", default=20, help="한 번에 대사할 notification_jobs 수")
    def reconcile_notifications_cmd(batch_size):
        """ACCEPTED 및 SEND_UNKNOWN 알림에 대한 2-Step Reconciliation을 수행합니다."""
        from services.notification_service import NotificationService
        count = NotificationService().reconcile_jobs(batch_size=batch_size)
        click.echo(f"성공: 총 {count}건의 알림 수신 결과 대사(Reconciled)가 완료되었습니다.")

    @app.cli.command("track-delivery")
    @click.option("--batch-size", default=50, help="한 번에 조회할 우체국 운송장 수")
    def track_delivery_cmd(batch_size):
        """status='SHIPPED' 상태의 우체국 운송장 배송상태를 주기적으로 Polling합니다."""
        from services.delivery.epost_provider import EPostDeliveryTracker
        count = EPostDeliveryTracker().process_polling_shipments(batch_size=batch_size)
        click.echo(f"성공: 총 {count}건의 배송완료(DELIVERED) 상태 업데이트 및 알림톡 큐 생성이 완료되었습니다.")

