import hashlib
import html
import math
import random
import smtplib

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import midtransclient

from flask import current_app


# =========================================================
# OTP
# =========================================================

def make_otp():
    return f"{random.randint(0, 999999):06d}"


def otp_hash(v):
    return hashlib.sha256(v.encode()).hexdigest()


# =========================================================
# EMAIL OTP
# =========================================================

def send_email_otp(to_email, otp):
    cfg = current_app.config

    if not cfg.get("SMTP_USER") or not cfg.get("SMTP_PASSWORD"):
        current_app.logger.error(
            "SMTP_USER atau SMTP_PASSWORD belum dikonfigurasi."
        )
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Kode Verifikasi Pasar Remboken"
        msg["From"] = cfg["SMTP_USER"]
        msg["To"] = to_email

        text_content = f"""
Kode verifikasi Pasar Remboken Anda: {otp}

Kode OTP ini berlaku selama 10 menit.

Jika Anda tidak melakukan permintaan kode ini, abaikan email ini.
"""

        html_content = f"""
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kode Verifikasi Pasar Remboken</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;
             font-family:Arial,Helvetica,sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background-color:#f1f5f9;padding:40px 15px;">
        <tr>
            <td align="center">
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="max-width:520px;background-color:#ffffff;
                              border-radius:16px;overflow:hidden;">
                    <tr>
                        <td align="center"
                            style="background-color:#0f766e;padding:30px 20px;">
                            <div style="font-size:42px;margin-bottom:10px;">🛒</div>
                            <div style="color:#ffffff;font-size:26px;font-weight:bold;">
                                Pasar Remboken
                            </div>
                            <div style="color:#ccfbf1;font-size:14px;margin-top:6px;">
                                Pasar Lokal, Mudah dan Terpercaya
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:35px 30px;">
                            <div style="text-align:center;color:#334155;
                                        font-size:15px;line-height:1.6;">
                                Gunakan kode berikut untuk memverifikasi akun Anda.
                            </div>
                            <div style="text-align:center;margin-top:25px;
                                        color:#64748b;font-size:12px;
                                        font-weight:bold;letter-spacing:2px;">
                                KODE VERIFIKASI
                            </div>
                            <div style="text-align:center;margin:12px 0 25px;">
                                <span style="display:inline-block;
                                             background-color:#f0fdfa;
                                             color:#0f766e;border:1px solid #99f6e4;
                                             border-radius:12px;padding:15px 30px;
                                             font-size:32px;font-weight:bold;
                                             letter-spacing:8px;">
                                    {html.escape(str(otp))}
                                </span>
                            </div>
                            <div style="background-color:#f8fafc;border-radius:10px;
                                        padding:15px;text-align:center;
                                        color:#475569;font-size:13px;line-height:1.6;">
                                Kode OTP ini berlaku selama <strong>10 menit</strong>.
                            </div>
                            <div style="margin-top:22px;color:#64748b;font-size:12px;
                                        line-height:1.6;text-align:center;">
                                Demi keamanan akun Anda, jangan berikan kode OTP
                                ini kepada siapa pun.
                                <br><br>
                                Jika Anda tidak meminta kode ini, abaikan email ini.
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td align="center"
                            style="background-color:#f8fafc;
                                   border-top:1px solid #e2e8f0;padding:20px;">
                            <div style="color:#94a3b8;font-size:11px;line-height:1.5;">
                                Email otomatis dari sistem Pasar Remboken.
                                <br>Mohon tidak membalas email ini.
                            </div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

        msg.attach(MIMEText(text_content, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        with smtplib.SMTP(
            cfg["SMTP_HOST"],
            cfg["SMTP_PORT"],
            timeout=20,
        ) as smtp:
            smtp.starttls()
            smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            smtp.send_message(msg)

        current_app.logger.info("OTP email berhasil dikirim.")
        return True

    except Exception:
        current_app.logger.exception("Gagal mengirim OTP email.")
        return False


# =========================================================
# WHATSAPP OTP VIA FONNTE
# =========================================================

def send_fonnte(phone, otp):
    token = current_app.config.get("FONNTE_TOKEN")

    if not token:
        current_app.logger.error("FONNTE_TOKEN belum dikonfigurasi.")
        return False

    if not phone:
        current_app.logger.error("Nomor WhatsApp penerima kosong.")
        return False

    try:
        response = requests.post(
            "https://api.fonnte.com/send",
            headers={"Authorization": token},
            data={
                "target": phone,
                "message": (
                    f"Kode verifikasi Pasar Remboken: {otp}. "
                    "Berlaku 10 menit."
                ),
            },
            timeout=20,
        )

        response.raise_for_status()

        try:
            return response.json().get("status") is True
        except ValueError:
            current_app.logger.error(
                "Respons Fonnte bukan JSON yang valid."
            )
            return False

    except Exception:
        current_app.logger.exception(
            "Gagal mengirim OTP melalui WhatsApp Fonnte."
        )
        return False


# =========================================================
# NOTIFIKASI PESANAN VIA EMAIL DAN WHATSAPP
# =========================================================

def send_order_notification(to_email, phone, subject, message):
    """
    Mengirim notifikasi melalui email dan WhatsApp.

    Return:
        {
            "email": True/False,
            "whatsapp": True/False
        }
    """
    cfg = current_app.config

    result = {
        "email": False,
        "whatsapp": False,
    }

    # -----------------------------------------------------
    # EMAIL
    # -----------------------------------------------------

    if (
        to_email
        and cfg.get("SMTP_USER")
        and cfg.get("SMTP_PASSWORD")
    ):
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = cfg["SMTP_USER"]
            msg["To"] = to_email

            msg.attach(MIMEText(message, "plain", "utf-8"))

            safe_subject = html.escape(subject)
            safe_message = html.escape(message).replace("\n", "<br>\n")

            html_content = f"""
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:24px;background:#f1f5f9;
             font-family:Arial,Helvetica,sans-serif;color:#334155;">
    <div style="max-width:560px;margin:auto;background:#ffffff;
                border-radius:14px;overflow:hidden;">
        <div style="background:#0f766e;color:#ffffff;
                    padding:22px;text-align:center;">
            <h2>Pasar Remboken</h2>
        </div>
        <div style="padding:24px;line-height:1.7;">
            <h3>{safe_subject}</h3>
            <p>{safe_message}</p>
        </div>
        <div style="padding:16px;text-align:center;
                    background:#f8fafc;color:#64748b;font-size:12px;">
            Pesan otomatis dari sistem Pasar Remboken.
        </div>
    </div>
</body>
</html>
"""

            msg.attach(MIMEText(html_content, "html", "utf-8"))

            with smtplib.SMTP(
                cfg["SMTP_HOST"],
                cfg["SMTP_PORT"],
                timeout=20,
            ) as smtp:
                smtp.starttls()
                smtp.login(
                    cfg["SMTP_USER"],
                    cfg["SMTP_PASSWORD"],
                )
                smtp.send_message(msg)

            result["email"] = True

        except Exception:
            current_app.logger.exception(
                "Gagal mengirim notifikasi pesanan melalui email."
            )

    # -----------------------------------------------------
    # WHATSAPP VIA FONNTE
    # -----------------------------------------------------

    token = cfg.get("FONNTE_TOKEN")

    if phone and token:
        try:
            response = requests.post(
                "https://api.fonnte.com/send",
                headers={"Authorization": token},
                data={
                    "target": phone,
                    "message": f"{subject}\n\n{message}",
                },
                timeout=20,
            )

            response.raise_for_status()

            try:
                result["whatsapp"] = (
                    response.json().get("status") is True
                )
            except ValueError:
                result["whatsapp"] = False

        except Exception:
            current_app.logger.exception(
                "Gagal mengirim notifikasi pesanan melalui WhatsApp."
            )

    return result


# =========================================================
# MIDTRANS
# =========================================================

def snap_client():
    server_key = current_app.config.get("MIDTRANS_SERVER_KEY")

    if not server_key:
        raise RuntimeError(
            "MIDTRANS_SERVER_KEY belum dikonfigurasi."
        )

    return midtransclient.Snap(
        is_production=current_app.config["MIDTRANS_IS_PRODUCTION"],
        server_key=server_key,
    )


def create_snap(order_id, gross_amount, customer):
    try:
        amount = int(gross_amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("Total pembayaran tidak valid.") from exc

    if amount <= 0:
        raise ValueError("Total pembayaran harus lebih dari nol.")

    if not order_id:
        raise ValueError("Nomor pesanan tidak boleh kosong.")

    return snap_client().create_transaction(
        {
            "transaction_details": {
                "order_id": str(order_id),
                "gross_amount": amount,
            },
            "customer_details": {
                "first_name": customer.name or "Pembeli",
                "email": customer.email,
                "phone": customer.phone or "",
            },
        }
    )


# =========================================================
# BIAYA PENGANTARAN
# =========================================================

def delivery_fee(distance_km):
    try:
        distance_km = float(distance_km)
        base_fee = int(current_app.config["DELIVERY_BASE_FEE"])
        per_km = int(current_app.config["DELIVERY_PER_KM"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(
            "Data atau konfigurasi ongkos kirim tidak valid."
        ) from exc

    if not math.isfinite(distance_km) or distance_km < 0:
        raise ValueError("Jarak pengantaran tidak valid.")

    if base_fee < 0 or per_km < 0:
        raise ValueError("Konfigurasi ongkos kirim tidak valid.")

    return base_fee + math.ceil(distance_km * per_km)