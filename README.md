# Pasar Remboken — Flask Marketplace

Sistem digitalisasi pasar lokal berbasis Flask + MySQL XAMPP dengan role Pembeli, Pedagang dan Admin.

## Fitur
- Registrasi/login + OTP email
- Pedagang: NIK, KTP, data toko, verifikasi admin
- Katalog, kategori, stok, keranjang, checkout
- Pickup atau delivery
- Leaflet + OpenStreetMap + OSRM untuk estimasi jarak
- Midtrans Snap
- Status pesanan dan saldo pedagang
- Rating produk/pedagang setelah selesai
- Notifikasi database
- Penarikan saldo dengan persetujuan admin
- Dashboard admin, verifikasi, laporan
- Tailwind CSS + Font Awesome + SweetAlert2

## Instalasi Windows/XAMPP
1. Jalankan Apache dan MySQL dari XAMPP.
2. Buat database `pasar_remboken` melalui phpMyAdmin, atau jalankan `schema.sql`.
3. Salin `.env.example` menjadi `.env` lalu isi kredensial.
4. Buat virtual environment:
   `py -m venv venv`
5. Aktifkan:
   `venv\\Scripts\\activate`
6. Install:
   `pip install -r requirements.txt`
7. Inisialisasi:
   `flask --app app init-db`
8. Jalankan:
   `python run.py`
9. Buka `http://127.0.0.1:5000`

## Admin awal
Email: `admin@pasarremboken.local`
Password: `admin12345`
Segera ubah password admin setelah login.

## Konfigurasi penting
- `MARKET_LAT` dan `MARKET_LNG` harus diisi koordinat nyata Pasar Remboken.
- Midtrans Sandbox memakai Snap sandbox. Untuk produksi ubah `MIDTRANS_IS_PRODUCTION=True` dan gunakan credential production.
- SMTP Gmail memakai App Password, bukan password Gmail biasa.
- Fonnte opsional bila OTP WhatsApp ingin digunakan.
- Untuk pencairan dana, sistem ini memakai saldo internal + persetujuan admin. Pembayaran pembeli diproses Midtrans; transfer ke rekening pedagang dilakukan berdasarkan proses pencairan admin.
