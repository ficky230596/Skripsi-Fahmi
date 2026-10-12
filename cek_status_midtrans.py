
import os
from decimal import Decimal
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()

SERVER_KEY = os.getenv("MIDTRANS_SERVER_KEY")
IS_PRODUCTION = (
    os.getenv("MIDTRANS_IS_PRODUCTION", "False").strip().lower()
    in ("true", "1", "yes")
)

ORDER_NUMBER = "PR-20261010202759-2ADBE"
EXPECTED_AMOUNT = Decimal("14160.00")

if not SERVER_KEY:
    raise SystemExit("ERROR: MIDTRANS_SERVER_KEY tidak tersedia.")

base_url = (
    "https://api.midtrans.com"
    if IS_PRODUCTION
    else "https://api.sandbox.midtrans.com"
)

url = f"{base_url}/v2/{quote(ORDER_NUMBER, safe='')}/status"

try:
    response = requests.get(
        url,
        auth=(SERVER_KEY, ""),
        timeout=20,
    )

    print("HTTP Status:", response.status_code)

    if response.status_code != 200:
        print("Gagal memeriksa status transaksi.")
        print("Respons:", response.text[:500])
        raise SystemExit(1)

    data = response.json()

    print("Order ID cocok:", data.get("order_id") == ORDER_NUMBER)
    print("Transaction Status:", data.get("transaction_status"))
    print("Payment Type:", data.get("payment_type"))
    print("Gross Amount cocok:",
          Decimal(str(data.get("gross_amount", "0"))) == EXPECTED_AMOUNT)

    if (
        data.get("order_id") != ORDER_NUMBER
        or Decimal(str(data.get("gross_amount", "0"))) != EXPECTED_AMOUNT
    ):
        raise SystemExit(
            "BERHENTI: nomor pesanan atau nominal tidak cocok."
        )

    if data.get("transaction_status") == "settlement":
        print("\nTERVERIFIKASI: transaksi berstatus settlement.")
        print("Langkah berikutnya: sinkronisasi database.")
    else:
        print("\nTransaksi belum berstatus settlement.")
        print("Database jangan diubah dulu.")

except requests.RequestException as exc:
    raise SystemExit(f"Gagal menghubungi Midtrans: {exc}")

