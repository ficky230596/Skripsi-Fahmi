import os
from decimal import Decimal, InvalidOperation
from datetime import datetime

import requests
from dotenv import load_dotenv

from app import app, db, Order, Payment

load_dotenv()

ORDER_NUMBER = "PR-20261010202759-2ADBE"
EXPECTED_AMOUNT = Decimal("14160.00")

SERVER_KEY = os.getenv("MIDTRANS_SERVER_KEY")
IS_PRODUCTION = (
    os.getenv("MIDTRANS_IS_PRODUCTION", "False").strip().lower()
    in ("true", "1", "yes")
)

if not SERVER_KEY:
    raise SystemExit("ERROR: MIDTRANS_SERVER_KEY tidak tersedia.")

BASE_URL = (
    "https://api.midtrans.com"
    if IS_PRODUCTION
    else "https://api.sandbox.midtrans.com"
)


def main():
    # 1. VERIFIKASI STATUS TERBARU DARI MIDTRANS
    url = f"{BASE_URL}/v2/{ORDER_NUMBER}/status"

    try:
        response = requests.get(
            url,
            auth=(SERVER_KEY, ""),
            timeout=20,
        )
        response.raise_for_status()
        midtrans_data = response.json()
    except requests.RequestException as exc:
        raise SystemExit(f"Gagal memeriksa Midtrans: {exc}")

    if midtrans_data.get("order_id") != ORDER_NUMBER:
        raise SystemExit("BERHENTI: nomor pesanan Midtrans tidak cocok.")

    if midtrans_data.get("transaction_status") != "settlement":
        raise SystemExit(
            "BERHENTI: status Midtrans bukan settlement."
        )

    try:
        midtrans_amount = Decimal(
            str(midtrans_data.get("gross_amount", "0"))
        )
    except InvalidOperation:
        raise SystemExit("BERHENTI: nominal Midtrans tidak valid.")

    if midtrans_amount != EXPECTED_AMOUNT:
        raise SystemExit("BERHENTI: nominal Midtrans tidak cocok.")

    # 2. COCOKKAN PESANAN DAN PEMBAYARAN LOKAL
    with app.app_context():
        order = Order.query.filter_by(
            order_number=ORDER_NUMBER
        ).with_for_update().first()

        if not order:
            raise SystemExit("BERHENTI: pesanan lokal tidak ditemukan.")

        payment = Payment.query.filter_by(
            order_id=order.id,
            provider="midtrans",
        ).first()

        if not payment:
            raise SystemExit("BERHENTI: data pembayaran tidak ditemukan.")

        try:
            order_amount = Decimal(str(order.total)).quantize(
                Decimal("0.01")
            )
            payment_amount = Decimal(
                str(payment.gross_amount)
            ).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError):
            raise SystemExit("BERHENTI: nominal lokal tidak valid.")

        if (
            order_amount != midtrans_amount
            or payment_amount != midtrans_amount
        ):
            raise SystemExit(
                "BERHENTI: nominal pesanan, pembayaran, "
                "dan Midtrans tidak cocok."
            )

        # Pastikan tidak mengganti transaksi lokal yang berbeda.
        midtrans_transaction_id = midtrans_data.get("transaction_id")

        if (
            payment.transaction_id
            and midtrans_transaction_id
            and payment.transaction_id != midtrans_transaction_id
        ):
            raise SystemExit(
                "BERHENTI: transaction_id tidak cocok."
            )

        # 3. SINKRONISASI STATUS
        try:
            order.payment_status = "paid"
            order.order_status = "Dibayar"
            order.seller_amount_status = "Dana Ditahan"

            payment.transaction_id = midtrans_transaction_id
            payment.payment_type = midtrans_data.get("payment_type")
            payment.transaction_status = "settlement"

            if not payment.paid_at:
                payment.paid_at = datetime.utcnow()

            payment.raw_response = str(midtrans_data)

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise

        print("\n========== SINKRONISASI BERHASIL ==========")
        print("Nomor pesanan:", order.order_number)
        print("Status pesanan:", order.order_status)
        print("Status pembayaran:", order.payment_status)
        print("Status dana pedagang:", order.seller_amount_status)
        print("Status transaksi Midtrans:", payment.transaction_status)
        print("Nominal:", order.total)
        print("============================================")


if __name__ == "__main__":
    main()
id="sy6xqk"