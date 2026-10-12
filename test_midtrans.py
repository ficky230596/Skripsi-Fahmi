from app import app
from services.integrations import create_snap


class DummyCustomer:
    name = "Test Pembeli"
    email = "test@pasarremboken.com"
    phone = "081234567890"


with app.app_context():
    try:
        result = create_snap(
            order_id="TEST-PASAR-REMBOKEN-001",
            gross_amount=10000,
            customer=DummyCustomer()
        )

        print("=" * 60)
        print("TES TRANSAKSI MIDTRANS")
        print("=" * 60)
        print("STATUS : BERHASIL")
        print("ORDER ID :", "TEST-PASAR-REMBOKEN-001")
        print("GROSS AMOUNT :", 10000)
        print("SNAP TOKEN :", result.get("token"))
        print("REDIRECT URL :", result.get("redirect_url"))
        print("=" * 60)

    except Exception as e:
        print("=" * 60)
        print("TES TRANSAKSI MIDTRANS")
        print("=" * 60)
        print("STATUS : GAGAL")
        print("ERROR :", repr(e))
        print("=" * 60)