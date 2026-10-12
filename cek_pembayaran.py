
from app import app, db
from sqlalchemy import text


def cek_pembayaran(order_id):
    with app.app_context():
        sql = text("""
            SELECT
                o.id AS order_id,
                o.order_number,
                o.order_status,
                o.payment_status,
                o.total,
                p.id AS payment_id,
                p.provider,
                p.transaction_id,
                p.snap_token,
                p.gross_amount,
                p.payment_type,
                p.transaction_status,
                p.paid_at,
                p.raw_response
            FROM `order` AS o
            LEFT JOIN payment AS p
                ON p.order_id = o.id
            WHERE o.id = :order_id
        """)

        try:
            result = db.session.execute(
                sql,
                {"order_id": order_id}
            ).mappings().first()

            if not result:
                print(f"Pesanan ID {order_id} tidak ditemukan.")
                return

            print("\n========== PEMERIKSAAN PEMBAYARAN ==========")

            for key, value in result.items():
                if key == "snap_token" and value:
                    value = f"{value[:8]}...{value[-4:]}"

                print(f"{key}: {value}")

            print("============================================")

        except Exception as e:
            db.session.rollback()
            print("Gagal memeriksa pembayaran.")
            print("Jenis error:", type(e).__name__)
            print("Detail:", str(e))


if __name__ == "__main__":
    cek_pembayaran(15)
