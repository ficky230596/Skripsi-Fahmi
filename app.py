import os
import math
import uuid
import re
import time
import pandas as pd
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation

from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    send_file,
    abort,
    session,
    current_app,
    Response,
    stream_with_context,
)

from flask_sqlalchemy import SQLAlchemy

from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)

from werkzeug.utils import secure_filename

from dotenv import load_dotenv

from services.integrations import (
    make_otp,
    otp_hash,
    send_email_otp,
    send_fonnte,
    send_order_notification,
    create_snap,
    delivery_fee,
)


load_dotenv()
app = Flask(__name__)
app.config.from_object("config.Config")
db = SQLAlchemy(app)
login = LoginManager(app)
login.login_view = "login"
UPLOAD = os.path.join(app.root_path, "static", "uploads")
KTP = os.path.join(UPLOAD, "ktp")
PROD = os.path.join(UPLOAD, "products")
os.makedirs(KTP, exist_ok=True)
os.makedirs(PROD, exist_ok=True)



def rupiah(nilai):
    try:
        nilai = float(nilai or 0)
        return f"Rp{nilai:,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return "Rp0"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    phone = db.Column(db.String(30))
    password_hash = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    profile_photo = db.Column(db.String(255), nullable=True)

    def set_password(self, p):
        self.password_hash = generate_password_hash(p)

    def check_password(self, p):
        return check_password_hash(self.password_hash, p)
    
    

class BuyerAddress(db.Model):
    __tablename__ = 'buyer_address'

    id = db.Column(db.Integer, primary_key=True)

    buyer_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False,
        index=True
    )

    label = db.Column(db.String(50), nullable=False)
    recipient_name = db.Column(db.String(120), nullable=False)
    recipient_phone = db.Column(db.String(30), nullable=False)
    full_address = db.Column(db.Text, nullable=False)
    address_note = db.Column(db.Text)

    latitude = db.Column(db.Numeric(10, 7), nullable=False)
    longitude = db.Column(db.Numeric(10, 7), nullable=False)

    is_primary = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    buyer = db.relationship(
        'User',
        backref=db.backref('saved_addresses', lazy=True)
    )



class SellerProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True)
    nik = db.Column(db.String(30))
    address = db.Column(db.Text)
    store_name = db.Column(db.String(160))
    store_address = db.Column(db.Text)
    ktp_file = db.Column(db.String(255))
    verification_status = db.Column(db.String(20), default="pending")
    rejection_reason = db.Column(db.Text)
    verified_at = db.Column(db.DateTime)
    verified_by = db.Column(db.Integer)
    user = db.relationship("User", backref=db.backref("seller_profile", uselist=False))


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    slug = db.Column(db.String(120), unique=True)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"))
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Integer, nullable=False)
    stock = db.Column(db.Integer, default=0)
    image = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    seller = db.relationship("User", backref="products")
    category = db.relationship("Category")


class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id"),
        nullable=False
    )
    image = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    product = db.relationship(
        "Product",
        backref=db.backref(
            "images",
            cascade="all, delete-orphan",
            order_by="ProductImage.id"
        )
    )


class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True)
    buyer = db.relationship("User")
    items = db.relationship("CartItem", backref="cart", cascade="all,delete-orphan")


class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"))
    qty = db.Column(db.Integer, default=1)
    product = db.relationship("Product")



class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(40), unique=True)

    # Penanda apakah stok sudah dikembalikan
    stock_restored = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    subtotal = db.Column(db.Integer, default=0)
    delivery_method = db.Column(db.String(20), default="pickup")
    delivery_address = db.Column(db.Text)
    recipient_name = db.Column(db.String(120), nullable=True)
    recipient_phone = db.Column(db.String(30), nullable=True)
    delivery_note = db.Column(db.Text, nullable=True)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    distance_km = db.Column(db.Float, default=0)
    delivery_fee = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    order_status = db.Column(
        db.String(30),
        default="Menunggu Pembayaran"
    )
    payment_status = db.Column(db.String(30), default="pending")
    seller_amount_status = db.Column(
        db.String(30),
        default="Menunggu Pembayaran"
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    buyer = db.relationship("User", backref="orders")
    items = db.relationship(
        "OrderItem",
        backref="order",
        cascade="all,delete-orphan"
    )
    payment = db.relationship(
        "Payment",
        backref="order",
        uselist=False
    )



class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"))
    product_id = db.Column(db.Integer)
    seller_id = db.Column(db.Integer)
    product_name = db.Column(db.String(160))
    price = db.Column(db.Integer)
    qty = db.Column(db.Integer)
    subtotal = db.Column(db.Integer)
    



class Payment(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), unique=True)

    provider = db.Column(db.String(30), default="midtrans")

    transaction_id = db.Column(db.String(120))

    snap_token = db.Column(db.String(255))

    gross_amount = db.Column(db.Integer)

    payment_type = db.Column(db.String(50))

    transaction_status = db.Column(db.String(50))

    paid_at = db.Column(db.DateTime)

    raw_response = db.Column(db.Text)


class Rating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"))
    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    seller_id = db.Column(db.Integer)
    product_id = db.Column(db.Integer)
    seller_rating = db.Column(db.Integer)
    product_rating = db.Column(db.Integer)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    title = db.Column(db.String(160))
    message = db.Column(db.Text)
    type = db.Column(db.String(40))
    reference_id = db.Column(db.Integer)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref="notifications")


class OTP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    channel = db.Column(db.String(20))
    destination = db.Column(db.String(160))
    code_hash = db.Column(db.String(128))
    expires_at = db.Column(db.DateTime)
    verified_at = db.Column(db.DateTime)


class SellerBalance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True)
    available_balance = db.Column(db.Integer, default=0)
    held_balance = db.Column(db.Integer, default=0)
    total_earned = db.Column(db.Integer, default=0)
    total_withdrawn = db.Column(db.Integer, default=0)
    seller = db.relationship("User", backref=db.backref("balance", uselist=False))


class Withdrawal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    amount = db.Column(db.Integer)
    bank_name = db.Column(db.String(100))
    bank_account = db.Column(db.String(80))
    account_name = db.Column(db.String(120))
    status = db.Column(db.String(20), default="pending")
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)
    processed_by = db.Column(db.Integer)
    note = db.Column(db.Text)
    seller = db.relationship("User", backref="withdrawals")


@login.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))


def roles(*r):
    def d(f):
        @wraps(f)
        def w(*a, **k):
            if not current_user.is_authenticated:
                return login.unauthorized()
            if current_user.role not in r:
                abort(403)
            return f(*a, **k)

        return w

    return d


def notify(uid, title, msg, typ="system", ref=None):
    db.session.add(
        Notification(user_id=uid, title=title, message=msg, type=typ, reference_id=ref)
    )


def seller_ok():
    return (
        current_user.role == "seller"
        and current_user.seller_profile
        and current_user.seller_profile.verification_status == "approved"
    )


def cart_for(uid):
    c = Cart.query.filter_by(buyer_id=uid).first()
    if not c:
        c = Cart(buyer_id=uid)
        db.session.add(c)
        db.session.flush()
    return c


@app.context_processor
def globals():
    return {
        "unread_count": (
            Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
            if current_user.is_authenticated
            else 0
        ),
        "rupiah": lambda n: f"Rp {n:,.0f}".replace(",", "."),
        "now": datetime.utcnow,
    }



@app.route("/")
def home():

    products = (
        Product.query
        .filter_by(is_active=True)
        .order_by(Product.created_at.desc())
        .limit(12)
        .all()
    )

    for product in products:

        # ==========================================
        # RATING PRODUK
        # ==========================================
        rating = (
            db.session.query(
                db.func.avg(Rating.product_rating)
            )
            .filter(
                Rating.product_id == product.id,
                Rating.product_rating.isnot(None)
            )
            .scalar()
        )

        product.product_rating = (
            float(rating)
            if rating is not None
            else 0.0
        )


        # ==========================================
        # JUMLAH PRODUK TERJUAL
        # HANYA PESANAN SELESAI
        # ==========================================
        sold_count = (
            db.session.query(
                db.func.coalesce(
                    db.func.sum(OrderItem.qty),
                    0
                )
            )
            .join(
                Order,
                Order.id == OrderItem.order_id
            )
            .filter(
                OrderItem.product_id == product.id,
                Order.order_status == "Selesai"
            )
            .scalar()
            or 0
        )

        product.sold_count = int(sold_count)


    return render_template(
        "buyer/dashboard.html",
        products=products,
        public=True
    )
    
    
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        role = request.form.get("role", "buyer")
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone", "").strip()
        verification_method = request.form.get(
            "verification_method",
            "email"
        )

        # Validasi metode verifikasi
        if verification_method not in ("email", "whatsapp"):
            flash("Metode verifikasi tidak valid.", "error")
            return redirect(url_for("register"))

        # Jika memilih WhatsApp, nomor wajib diisi
        if verification_method == "whatsapp" and not phone:
            flash(
                "Nomor WhatsApp wajib diisi untuk verifikasi melalui WhatsApp.",
                "error",
            )
            return redirect(url_for("register"))

        # Cek email sudah terdaftar
        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            if existing_user.is_verified:
                flash(
                    "Email sudah terdaftar. Silakan login menggunakan akun tersebut.",
                    "error"
                )
                return redirect(url_for("login"))

            flash(
                "Email sudah terdaftar tetapi belum diverifikasi. Silakan verifikasi email Anda.",
                "error"
            )
            return redirect(url_for("verify", uid=existing_user.id))

        # Cek nomor WhatsApp jika diisi
        if phone and User.query.filter_by(phone=phone).first():
            flash("Nomor WhatsApp sudah terdaftar.", "error")
            return redirect(url_for("register"))

        # Buat akun pengguna
        u = User(
            name=request.form["name"],
            email=email,
            phone=phone or None,
            role=role,
            is_verified=False,
        )

        u.set_password(request.form["password"])

        db.session.add(u)
        db.session.flush()

        # Data khusus pedagang
        if role == "seller":
            if (
                not request.form.get("nik")
                or not request.form.get("store_name")
                or "ktp" not in request.files
            ):
                db.session.rollback()
                flash("Data pedagang dan KTP wajib diisi.", "error")
                return redirect(url_for("register"))

            f = request.files["ktp"]

            if not f or not f.filename:
                db.session.rollback()
                flash("File KTP wajib diunggah.", "error")
                return redirect(url_for("register"))

            fn = secure_filename(f.filename)
            fn = f"{uuid.uuid4().hex}_{fn}"

            f.save(os.path.join(KTP, fn))

            db.session.add(
                SellerProfile(
                    user_id=u.id,
                    nik=request.form["nik"],
                    address=request.form.get("address"),
                    store_name=request.form["store_name"],
                    store_address=request.form.get("store_address"),
                    ktp_file=fn,
                )
            )

        # Buat saldo pengguna sesuai alur sebelumnya
        db.session.add(
            SellerBalance(
                seller_id=u.id
            )
        )

        # Notifikasi pendaftaran khusus pedagang
        if role == "seller":

            # Notifikasi kepada pedagang yang mendaftar
            notify(
                u.id,
                "Pendaftaran Pedagang Diterima",
                "Pendaftaran berhasil dibuat. Silakan verifikasi akun Anda. "
                "Data pedagang akan menunggu persetujuan admin.",
                "seller_verification",
            )

            # Notifikasi kepada seluruh admin
            admins = User.query.filter_by(
                role="admin"
            ).all()

            for admin in admins:
                notify(
                    admin.id,
                    "Pedagang Baru Mendaftar",
                    f"Pedagang {u.name} baru saja mendaftar "
                    "dan menunggu pemeriksaan serta persetujuan admin.",
                    "seller_verification",
                    u.id,
                )

        # Buat OTP
        otp = make_otp()

        destination = (
            email
            if verification_method == "email"
            else phone
        )

        db.session.add(
            OTP(
                user_id=u.id,
                channel=verification_method,
                destination=destination,
                code_hash=otp_hash(otp),
                expires_at=datetime.utcnow() + timedelta(minutes=10),
            )
        )

        # Simpan akun, profil, saldo, notifikasi, dan OTP
        db.session.commit()

        # Kirim OTP sesuai pilihan pengguna
        sent = False

        try:
            if verification_method == "whatsapp":
                sent = send_fonnte(phone, otp)
            else:
                sent = send_email_otp(email, otp)
        except Exception:
            app.logger.exception(
                "Gagal mengirim OTP untuk akun %s.",
                email
            )
            sent = False

        if not sent:
            flash(
                "Akun berhasil dibuat, tetapi OTP gagal dikirim. "
                "Periksa konfigurasi Email atau WhatsApp.",
                "error",
            )
        else:
            if verification_method == "whatsapp":
                flash(
                    "Akun berhasil dibuat. Kode OTP telah dikirim melalui WhatsApp.",
                    "success",
                )
            else:
                flash(
                    "Akun berhasil dibuat. Kode OTP telah dikirim melalui Email.",
                    "success",
                )

        return redirect(url_for("verify", uid=u.id))

    return render_template("auth/register.html")


@app.route("/verify/<int:uid>", methods=["GET", "POST"])
def verify(uid):
    u = db.session.get(User, uid) or abort(404)

    if u.is_verified:
        login_user(u)
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        otp_input = request.form.get("otp", "").strip()

        if not otp_input:
            flash("Kode OTP wajib diisi.", "error")
            return redirect(url_for("verify", uid=uid))

        o = (
            OTP.query
            .filter_by(
                user_id=uid,
                verified_at=None
            )
            .order_by(OTP.id.desc())
            .first()
        )

        if not o:
            flash(
                "Kode OTP tidak ditemukan. Silakan kirim ulang kode.",
                "error"
            )
            return redirect(url_for("verify", uid=uid))

        if o.expires_at <= datetime.utcnow():
            flash(
                "Kode OTP sudah kedaluwarsa. Silakan kirim ulang kode.",
                "error"
            )
            return redirect(url_for("verify", uid=uid))

        if o.code_hash != otp_hash(otp_input):
            flash(
                "Kode OTP salah. Silakan coba lagi.",
                "error"
            )
            return redirect(url_for("verify", uid=uid))

        # Berhasil diverifikasi
        u.is_verified = True
        o.verified_at = datetime.utcnow()

        db.session.commit()

        login_user(u)

        flash(
            "Verifikasi email berhasil.",
            "success"
        )

        return redirect(url_for("dashboard"))

    return render_template(
        "auth/verify.html",
        user=u
    )


@app.route("/resend-otp/<int:uid>", methods=["POST"])
def resend_otp(uid):
    u = db.session.get(User, uid) or abort(404)

    if u.is_verified:
        flash("Akun sudah terverifikasi.", "success")
        return redirect(url_for("login"))

    # Nonaktifkan OTP sebelumnya
    OTP.query.filter_by(
        user_id=uid,
        verified_at=None
    ).update(
        {
            "verified_at": datetime.utcnow()
        },
        synchronize_session=False
    )

    # Buat OTP baru
    otp = make_otp()

    new_otp = OTP(
        user_id=u.id,
        channel="email",
        destination=u.email,
        code_hash=otp_hash(otp),
        expires_at=datetime.utcnow() + timedelta(minutes=10)
    )

    db.session.add(new_otp)
    db.session.commit()

    sent = False

    try:
        sent = send_email_otp(u.email, otp)
    except Exception as e:
        print("ERROR RESEND OTP:", repr(e))
        sent = False

    if sent:
        flash(
            "Kode OTP baru telah dikirim ke email Anda.",
            "success"
        )
    else:
        flash(
            "Kode OTP gagal dikirim. Silakan coba lagi.",
            "error"
        )

    return redirect(url_for("verify", uid=u.id))


@app.route("/edit-phone/<int:uid>", methods=["POST"])
def edit_phone(uid):

    u = db.session.get(User, uid) or abort(404)

    if u.is_verified:
        flash(
            "Akun sudah terverifikasi.",
            "success"
        )
        return redirect(url_for("login"))

    new_phone = request.form.get("phone", "").strip()

    if not re.fullmatch(r"[0-9]{10,15}", new_phone):
        flash(
            "Nomor WhatsApp harus terdiri dari 10–15 digit angka.",
            "error"
        )
        return redirect(
            url_for(
                "verify",
                uid=uid
            )
        )

    existing_phone = (
        User.query
        .filter(
            User.phone == new_phone,
            User.id != u.id
        )
        .first()
    )

    if existing_phone:
        flash(
            "Nomor WhatsApp sudah digunakan oleh akun lain.",
            "error"
        )
        return redirect(
            url_for(
                "verify",
                uid=uid
            )
        )

    OTP.query.filter_by(
        user_id=uid,
        verified_at=None
    ).update(
        {
            "verified_at": datetime.utcnow()
        },
        synchronize_session=False
    )

    u.phone = new_phone

    otp = make_otp()

    new_otp = OTP(
        user_id=u.id,
        channel="whatsapp",
        destination=new_phone,
        code_hash=otp_hash(otp),
        expires_at=datetime.utcnow() + timedelta(minutes=10)
    )

    db.session.add(new_otp)
    db.session.commit()

    sent = False

    try:
        sent = send_fonnte(
            new_phone,
            otp
        )
    except Exception as e:
        print(
            "ERROR EDIT NOMOR + OTP:",
            repr(e)
        )
        sent = False

    if sent:
        flash(
            "Nomor WhatsApp berhasil diperbarui. "
            "Kode OTP baru telah dikirim ke nomor tersebut.",
            "success"
        )
    else:
        flash(
            "Nomor WhatsApp berhasil diperbarui, "
            "tetapi OTP gagal dikirim. Silakan kirim ulang kode.",
            "error"
        )

    return redirect(
        url_for(
            "verify",
            uid=u.id
        )
    )




@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_input = request.form.get("login", "").strip()
        password = request.form.get("password", "")

        # Login menggunakan email
        if "@" in login_input:
            u = User.query.filter_by(
                email=login_input.lower()
            ).first()

        # Login menggunakan nomor telepon
        else:
            phone = "".join(
                c for c in login_input if c.isdigit()
            )

            # Ubah format 62... menjadi 0...
            if phone.startswith("62"):
                phone = "0" + phone[2:]

            # Nomor 8... menjadi 08...
            elif phone.startswith("8"):
                phone = "0" + phone

            u = User.query.filter_by(
                phone=phone
            ).first()

        if not u or not u.check_password(password):
            flash(
                "Email/nomor telepon atau password salah.",
                "error"
            )
            return redirect(url_for("login"))

        # Verifikasi email tetap berlaku
        if not u.is_verified:
            flash(
                "Email Anda belum diverifikasi. Silakan masukkan kode OTP.",
                "error"
            )
            return redirect(url_for("verify", uid=u.id))

        login_user(u)

        return redirect(url_for("dashboard"))

    return render_template("auth/login.html")





# ============================================================
# LUPA PASSWORD
# ============================================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        identifier = request.form.get("identifier", "").strip()

        if not identifier:
            return jsonify({
                "success": False,
                "message": "Email atau nomor WhatsApp wajib diisi."
            }), 400

        # ----------------------------------------------------
        # TENTUKAN SALURAN PENGIRIMAN OTP
        # ----------------------------------------------------

        if "@" in identifier:

            channel = "email"
            user = User.query.filter_by(
                email=identifier.lower()
            ).first()

            if not user:
                return jsonify({
                    "success": False,
                    "message": "Email tidak ditemukan."
                }), 404

            destination = user.email

        else:

            # Normalisasi nomor telepon ke format database: 08xxx
            phone = "".join(
                char for char in identifier if char.isdigit()
            )

            if phone.startswith("62"):
                phone = "0" + phone[2:]
            elif phone.startswith("8"):
                phone = "0" + phone

            user = User.query.filter_by(
                phone=phone
            ).first()

            if not user:
                return jsonify({
                    "success": False,
                    "message": "Nomor WhatsApp tidak ditemukan."
                }), 404

            if not user.phone:
                return jsonify({
                    "success": False,
                    "message": "Akun ini belum memiliki nomor WhatsApp."
                }), 400

            channel = "whatsapp"
            destination = user.phone

        # ----------------------------------------------------
        # HAPUS OTP RESET PASSWORD LAMA YANG BELUM DIVERIFIKASI
        # ----------------------------------------------------

        OTP.query.filter_by(
            user_id=user.id,
            verified_at=None
        ).delete(synchronize_session=False)

        # ----------------------------------------------------
        # BUAT OTP BARU
        # ----------------------------------------------------

        code = make_otp()

        otp = OTP(
            user_id=user.id,
            channel=channel,
            destination=destination,
            code_hash=otp_hash(code),
            expires_at=datetime.utcnow() + timedelta(minutes=5)
        )

        db.session.add(otp)
        db.session.commit()

        # ----------------------------------------------------
        # KIRIM OTP SESUAI SALURAN
        # ----------------------------------------------------

        try:

            if channel == "email":
                sent = send_email_otp(destination, code)
            else:
                sent = send_fonnte(destination, code)

            if not sent:
                db.session.delete(otp)
                db.session.commit()

                return jsonify({
                    "success": False,
                    "message": "OTP gagal dikirim. Silakan coba lagi."
                }), 500

        except Exception as e:

            db.session.delete(otp)
            db.session.commit()

            print("ERROR KIRIM OTP RESET PASSWORD:", e)

            return jsonify({
                "success": False,
                "message": "Terjadi kesalahan saat mengirim OTP."
            }), 500

        # ----------------------------------------------------
        # SIMPAN KONTEKS VERIFIKASI DALAM SESSION
        # ----------------------------------------------------

        session["forgot_password_user_id"] = user.id
        session["forgot_password_channel"] = channel
        session["forgot_password_destination"] = destination

        channel_label = (
            "WhatsApp" if channel == "whatsapp" else "email"
        )

        return jsonify({
            "success": True,
            "message": f"Kode OTP telah dikirim ke {channel_label} Anda.",
            "redirect": url_for(
                "forgot_password_verify",
                uid=user.id
            )
        })

    return render_template("auth/forgot_password.html")


# ============================================================
# VERIFIKASI OTP LUPA PASSWORD
# ============================================================

@app.route("/forgot-password/verify/<int:uid>", methods=["GET", "POST"])
def forgot_password_verify(uid):

    # Pastikan pengguna melewati proses permintaan OTP terlebih dahulu.
    if session.get("forgot_password_user_id") != uid:
        return redirect(url_for("forgot_password"))

    user = db.session.get(User, uid)

    if not user:
        session.pop("forgot_password_user_id", None)
        session.pop("forgot_password_channel", None)
        session.pop("forgot_password_destination", None)
        return redirect(url_for("forgot_password"))

    channel = session.get("forgot_password_channel")
    destination = session.get("forgot_password_destination")

    if channel not in ("email", "whatsapp") or not destination:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":

        code = request.form.get("otp", "").strip()

        if not code:
            return jsonify({
                "success": False,
                "message": "Kode OTP wajib diisi."
            }), 400

        if not code.isdigit() or len(code) != 6:
            return jsonify({
                "success": False,
                "message": "Kode OTP harus terdiri dari 6 digit."
            }), 400

        # ----------------------------------------------------
        # CARI OTP BERDASARKAN USER DAN SALURAN
        # ----------------------------------------------------

        otp = OTP.query.filter_by(
            user_id=user.id,
            channel=channel,
            verified_at=None
        ).order_by(
            OTP.id.desc()
        ).first()

        if not otp:
            return jsonify({
                "success": False,
                "message": "Kode OTP tidak ditemukan. Silakan minta OTP baru."
            }), 400

        # ----------------------------------------------------
        # CEK MASA BERLAKU OTP
        # ----------------------------------------------------

        if datetime.utcnow() > otp.expires_at:
            return jsonify({
                "success": False,
                "message": "Kode OTP sudah kedaluwarsa."
            }), 400

        # ----------------------------------------------------
        # CEK KODE OTP
        # ----------------------------------------------------

        if otp.code_hash != otp_hash(code):
            return jsonify({
                "success": False,
                "message": "Kode OTP salah."
            }), 400

        # ----------------------------------------------------
        # OTP VALID
        # ----------------------------------------------------

        otp.verified_at = datetime.utcnow()
        db.session.commit()

        # Session yang digunakan route reset_password tetap sama.
        session["reset_password_user_id"] = user.id

        # Hapus konteks verifikasi OTP.
        session.pop("forgot_password_user_id", None)
        session.pop("forgot_password_channel", None)
        session.pop("forgot_password_destination", None)

        return jsonify({
            "success": True,
            "message": "OTP berhasil diverifikasi.",
            "redirect": url_for("reset_password")
        })

    return render_template(
        "auth/forgot_password_verify.html",
        user=user,
        channel=channel,
        destination=destination
    )


# ============================================================
# KIRIM ULANG OTP LUPA PASSWORD
# ============================================================

@app.route("/forgot-password/resend/<int:uid>", methods=["POST"])
def forgot_password_resend(uid):

    # Pastikan permintaan ulang berasal dari alur yang sama.
    if session.get("forgot_password_user_id") != uid:
        return jsonify({
            "success": False,
            "message": "Sesi permintaan OTP tidak valid. Silakan ulangi."
        }), 403

    user = db.session.get(User, uid)

    if not user:
        return jsonify({
            "success": False,
            "message": "Akun tidak ditemukan."
        }), 404

    channel = session.get("forgot_password_channel")
    destination = session.get("forgot_password_destination")

    if channel not in ("email", "whatsapp") or not destination:
        return jsonify({
            "success": False,
            "message": "Saluran OTP tidak valid. Silakan ulangi."
        }), 400

    # --------------------------------------------------------
    # HAPUS OTP LAMA YANG BELUM DIVERIFIKASI
    # --------------------------------------------------------

    OTP.query.filter_by(
        user_id=user.id,
        verified_at=None
    ).delete(synchronize_session=False)

    # --------------------------------------------------------
    # BUAT OTP BARU
    # --------------------------------------------------------

    code = make_otp()

    otp = OTP(
        user_id=user.id,
        channel=channel,
        destination=destination,
        code_hash=otp_hash(code),
        expires_at=datetime.utcnow() + timedelta(minutes=5)
    )

    db.session.add(otp)
    db.session.commit()

    # --------------------------------------------------------
    # KIRIM ULANG SESUAI SALURAN YANG DIPILIH
    # --------------------------------------------------------

    try:

        if channel == "email":
            sent = send_email_otp(destination, code)
        else:
            sent = send_fonnte(destination, code)

        if not sent:
            db.session.delete(otp)
            db.session.commit()

            return jsonify({
                "success": False,
                "message": "OTP gagal dikirim. Silakan coba lagi."
            }), 500

    except Exception as e:

        db.session.delete(otp)
        db.session.commit()

        print("ERROR RESEND OTP RESET PASSWORD:", e)

        return jsonify({
            "success": False,
            "message": "Terjadi kesalahan saat mengirim OTP."
        }), 500

    channel_label = (
        "WhatsApp" if channel == "whatsapp" else "email"
    )

    return jsonify({
        "success": True,
        "message": f"OTP baru telah dikirim ke {channel_label} Anda."
    })




# ============================================================
# RESET PASSWORD
# ============================================================

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():

    user_id = session.get("reset_password_user_id")

    if not user_id:
        return redirect(
            url_for("forgot_password")
        )

    user = User.query.get_or_404(user_id)

    if request.method == "POST":

        password = request.form.get("password", "")
        password_confirmation = request.form.get(
            "password_confirmation",
            ""
        )

        if not password:
            return jsonify({
                "success": False,
                "message": "Password baru wajib diisi."
            }), 400

        if len(password) < 8:
            return jsonify({
                "success": False,
                "message": "Password minimal 8 karakter."
            }), 400

        if password != password_confirmation:
            return jsonify({
                "success": False,
                "message": "Konfirmasi password tidak cocok."
            }), 400

        # ====================================================
        # UPDATE PASSWORD
        # ====================================================

        user.password_hash = generate_password_hash(
            password
        )

        db.session.commit()

        # Hapus session reset password
        session.pop(
            "reset_password_user_id",
            None
        )

        return jsonify({
            "success": True,
            "message": "Password berhasil diubah. Silakan login kembali.",
            "redirect": url_for("login")
        })

    return render_template(
        "auth/reset_password.html"
    )





@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == "admin":
        return redirect(url_for("admin_dashboard"))
    if current_user.role == "seller":
        return redirect(url_for("seller_dashboard"))
    return redirect(url_for("buyer_dashboard"))


@app.route("/buyer")
@login_required
@roles("buyer")
def buyer_dashboard():
    return render_template(
        "buyer/dashboard.html",
        products=Product.query.filter_by(is_active=True)
        .order_by(Product.created_at.desc())
        .limit(12)
        .all(),
    )



@app.route("/catalog")
def catalog():

    products = (
        Product.query
        .filter_by(is_active=True)
        .order_by(Product.created_at.desc())
        .all()
    )

    for product in products:

        rating = (
            db.session.query(
                db.func.avg(Rating.product_rating)
            )
            .filter(
                Rating.product_id == product.id,
                Rating.product_rating.isnot(None)
            )
            .scalar()
        )

        product.product_rating = (
            float(rating)
            if rating is not None
            else 0.0
        )

        sold_count = (
            db.session.query(
                db.func.coalesce(
                    db.func.sum(OrderItem.qty),
                    0
                )
            )
            .join(
                Order,
                Order.id == OrderItem.order_id
            )
            .filter(
                OrderItem.product_id == product.id,
                Order.order_status == "Selesai"
            )
            .scalar()
            or 0
        )

        product.sold_count = int(sold_count)

    return render_template(
        "buyer/catalog.html",
        products=products,
        categories=Category.query.order_by(Category.name).all(),
    )


    



@app.route("/product/<int:pid>")
def product_detail(pid):

    product = Product.query.filter_by(
        id=pid,
        is_active=True
    ).first_or_404()


    # ==================================================
    # INFORMASI PEDAGANG
    # ==================================================

    seller = User.query.get(product.seller_id)

    seller_profile = SellerProfile.query.filter_by(
        user_id=product.seller_id
    ).first()


    # ==================================================
    # JUMLAH PRODUK YANG SUDAH TERJUAL
    # ==================================================

    sold_count = (
        db.session.query(
            db.func.coalesce(
                db.func.sum(OrderItem.qty),
                0
            )
        )
        .join(
            Order,
            Order.id == OrderItem.order_id
        )
        .filter(
            OrderItem.product_id == product.id,
            Order.order_status == "Selesai"
        )
        .scalar()
        or 0
    )


    # ==================================================
    # RATING PRODUK
    # ==================================================

    product_rating = (
        db.session.query(
            db.func.avg(Rating.product_rating)
        )
        .filter(
            Rating.product_id == product.id,
            Rating.product_rating.isnot(None)
        )
        .scalar()
        or 0
    )


    product_rating_count = (
        Rating.query
        .filter(
            Rating.product_id == product.id,
            Rating.product_rating.isnot(None)
        )
        .count()
    )


    # ==================================================
    # RATING TOKO
    # ==================================================

    seller_rating = (
        db.session.query(
            db.func.avg(Rating.seller_rating)
        )
        .filter(
            Rating.seller_id == product.seller_id,
            Rating.seller_rating.isnot(None)
        )
        .scalar()
        or 0
    )


    seller_rating_count = (
        Rating.query
        .filter(
            Rating.seller_id == product.seller_id,
            Rating.seller_rating.isnot(None)
        )
        .count()
    )


    # ==================================================
    # JUMLAH PRODUK AKTIF MILIK TOKO
    # ==================================================

    seller_product_count = Product.query.filter_by(
        seller_id=product.seller_id,
        is_active=True
    ).count()


    # ==================================================
    # ULASAN PRODUK
    # ==================================================

    reviews = (
        db.session.query(
            Rating,
            User
        )
        .join(
            User,
            User.id == Rating.buyer_id
        )
        .filter(
            Rating.product_id == product.id
        )
        .order_by(
            Rating.created_at.desc()
        )
        .all()
    )


    # ==================================================
    # PRODUK LAIN DARI TOKO YANG SAMA
    # ==================================================

    other_products = (
        Product.query
        .filter(
            Product.seller_id == product.seller_id,
            Product.id != product.id,
            Product.is_active == True
        )
        .order_by(
            Product.created_at.desc()
        )
        .limit(8)
        .all()
    )


    # ==================================================
    # RATING DAN JUMLAH TERJUAL PRODUK LAINNYA
    # ==================================================

    for p in other_products:

        # Rata-rata rating produk
        avg_rating = (
            db.session.query(
                db.func.avg(Rating.product_rating)
            )
            .filter(
                Rating.product_id == p.id,
                Rating.product_rating.isnot(None)
            )
            .scalar()
        )

        p.product_rating = float(avg_rating or 0)


        # Jumlah unit terjual dari pesanan selesai
        total_sold = (
            db.session.query(
                db.func.coalesce(
                    db.func.sum(OrderItem.qty),
                    0
                )
            )
            .join(
                Order,
                Order.id == OrderItem.order_id
            )
            .filter(
                OrderItem.product_id == p.id,
                Order.order_status == "Selesai"
            )
            .scalar()
        )

        p.sold_count = int(total_sold or 0)


    # ==================================================
    # DEBUG
    # ==================================================

    print("PRODUCT ID:", product.id)
    print("PRODUCT RATING:", product_rating)
    print("PRODUCT RATING COUNT:", product_rating_count)

    print("SELLER RATING:", seller_rating)
    print("SELLER RATING COUNT:", seller_rating_count)

    print("REVIEWS:", reviews)

    for p in other_products:
        print(
            "OTHER PRODUCT:",
            p.id,
            p.name,
            "RATING:",
            p.product_rating,
            "SOLD:",
            p.sold_count
        )


    # ==================================================
    # RENDER
    # ==================================================

    return render_template(
        "buyer/product_detail.html",

        product=product,

        seller=seller,

        seller_profile=seller_profile,

        sold_count=int(sold_count),

        product_rating=float(product_rating),

        product_rating_count=product_rating_count,

        seller_rating=float(seller_rating),

        seller_rating_count=seller_rating_count,

        seller_product_count=seller_product_count,

        reviews=reviews,

        other_products=other_products,
    )




@app.post("/cart/add/<int:pid>")
@login_required
@roles("buyer")
def cart_add(pid):
    p = db.session.get(Product, pid) or abort(404)

    qty = max(1, int(request.form.get("qty", 1)))
    c = cart_for(current_user.id)

    item = CartItem.query.filter_by(
        cart_id=c.id,
        product_id=pid
    ).first()

    # Pastikan jumlah akhir di keranjang tidak melebihi stok
    current_qty = item.qty if item else 0
    total_qty = current_qty + qty

    if total_qty > p.stock:
        flash(
            f"Stok tidak mencukupi. Stok tersedia: {p.stock}, "
            f"jumlah di keranjang: {current_qty}.",
            "error"
        )
        return redirect(request.referrer or url_for("catalog"))

    if item:
        item.qty = total_qty
    else:
        db.session.add(
            CartItem(
                cart_id=c.id,
                product_id=pid,
                qty=qty
            )
        )

    db.session.commit()

    flash("Produk ditambahkan ke keranjang.", "success")
    return redirect(request.referrer or url_for("catalog"))


@app.route("/cart")
@login_required
@roles("buyer")
def cart():
    return render_template("buyer/cart.html", cart=cart_for(current_user.id))


@app.post("/cart/update/<int:item_id>")
@login_required
@roles("buyer")
def cart_update(item_id):
    i = db.session.get(CartItem, item_id) or abort(404)
    i.qty = max(1, min(i.product.stock, int(request.form["qty"])))
    db.session.commit()
    return redirect(url_for("cart"))


@app.post("/cart/remove/<int:item_id>")
@login_required
@roles("buyer")
def cart_remove(item_id):
    db.session.delete(db.session.get(CartItem, item_id))
    db.session.commit()
    return redirect(url_for("cart"))



@app.route("/checkout", methods=["GET", "POST"])
@login_required
@roles("buyer")
def checkout():
    import math
    from decimal import Decimal

    c = cart_for(current_user.id)

    # Ambil ID item yang dipilih.
    if request.method == "GET":
        raw_ids = request.args.getlist("items")
    else:
        raw_ids = request.form.getlist("items")

    # POST wajib menyertakan pilihan produk.
    if request.method == "POST" and not raw_ids:
        flash(
            "Pilih produk yang ingin dibayar terlebih dahulu.",
            "error"
        )
        return redirect(url_for("cart"))

    if raw_ids:
        try:
            selected_ids = [int(item_id) for item_id in raw_ids]

            if (
                any(item_id <= 0 for item_id in selected_ids)
                or len(selected_ids) != len(set(selected_ids))
            ):
                raise ValueError

        except (TypeError, ValueError):
            flash("Pilihan produk tidak valid.", "error")
            return redirect(url_for("cart"))

        # Pastikan semua item berada di keranjang pembeli ini.
        cart_items_by_id = {
            item.id: item for item in c.items
        }

        if any(
            item_id not in cart_items_by_id
            for item_id in selected_ids
        ):
            flash("Ada produk yang tidak valid.", "error")
            return redirect(url_for("cart"))

        items = [
            cart_items_by_id[item_id]
            for item_id in selected_ids
        ]

    else:
        # GET tanpa pilihan tetap menampilkan keranjang lama.
        items = list(c.items)
        selected_ids = [item.id for item in items]

    if not items:
        flash(
            "Pilih minimal satu produk untuk checkout.",
            "error"
        )
        return redirect(url_for("cart"))

    # ==================================================
    # 1. TAMPILAN CHECKOUT
    # ==================================================
    if request.method == "GET":
        subtotal = sum(
            item.qty * item.product.price
            for item in items
        )

        addresses = BuyerAddress.query.filter_by(
            buyer_id=current_user.id
        ).order_by(
            BuyerAddress.is_primary.desc(),
            BuyerAddress.created_at.desc()
        ).all()


        return render_template(
            "buyer/checkout.html",
            cart=c,
            items=items,
            selected_item_ids=selected_ids,
            subtotal=subtotal,
            payment_page=False,
            addresses=addresses,
        )


    # ==================================================
    # 2. VALIDASI METODE PENGANTARAN
    # ==================================================
    method = request.form.get("delivery_method", "pickup")

    if method not in ("pickup", "delivery"):
        flash("Metode pengantaran tidak valid.", "error")
        return redirect(url_for("checkout", items=selected_ids))

    addr = request.form.get("delivery_address", "").strip()
    lat_raw = request.form.get("latitude", "").strip()
    lng_raw = request.form.get("longitude", "").strip()
    saved_address_id = request.form.get(
        "saved_address_id", ""
    ).strip()

    selected_address = None
    lat = None
    lng = None
    dist = 0.0

    if method == "delivery":
        if saved_address_id:
            try:
                address_id = int(saved_address_id)
            except (TypeError, ValueError):
                flash("Alamat yang dipilih tidak valid.", "error")
                return redirect(url_for("checkout"))

            selected_address = BuyerAddress.query.filter_by(
                id=address_id,
                buyer_id=current_user.id
            ).first()

            if not selected_address:
                flash("Alamat yang dipilih tidak valid.", "error")
                return redirect(url_for("checkout"))

            addr = selected_address.full_address or ""
            lat_raw = (
                str(selected_address.latitude)
                if selected_address.latitude is not None
                else ""
            )
            lng_raw = (
                str(selected_address.longitude)
                if selected_address.longitude is not None
                else ""
            )

        if not addr or not lat_raw or not lng_raw:
            flash(
                "Alamat dan lokasi pengantaran wajib diisi.",
                "error"
            )
            return redirect(url_for("checkout"))

        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
            dist = float(request.form.get("distance_km") or 0)
        except (TypeError, ValueError):
            flash(
                "Koordinat atau jarak pengantaran tidak valid.",
                "error"
            )
            return redirect(url_for("checkout"))

        if (
            not math.isfinite(lat)
            or not math.isfinite(lng)
            or not math.isfinite(dist)
            or not -90 <= lat <= 90
            or not -180 <= lng <= 180
            or dist < 0
        ):
            flash(
                "Lokasi atau jarak pengantaran tidak valid.",
                "error"
            )
            return redirect(url_for("checkout"))

    recipient_name = (
        selected_address.recipient_name
        if selected_address else None
    )
    recipient_phone = (
        selected_address.recipient_phone
        if selected_address else None
    )
    delivery_note = (
        selected_address.address_note
        if selected_address else None
    )

    # ==================================================
    # 3. VALIDASI PRODUK DAN STOK
    # ==================================================
    try:
        product_ids = sorted({
            item.product_id for item in items
        })

        if not product_ids:
            flash("Keranjang tidak berisi produk valid.", "error")
            return redirect(url_for("cart"))

        locked_products = (
            Product.query
            .filter(
                Product.id.in_(product_ids),
                Product.is_active.is_(True)
            )
            .order_by(Product.id)
            .with_for_update()
            .populate_existing()
            .all()
        )

        products_by_id = {
            product.id: product
            for product in locked_products
        }

        if len(products_by_id) != len(product_ids):
            db.session.rollback()
            flash(
                "Ada produk yang sudah tidak tersedia.",
                "error"
            )
            return redirect(url_for("cart"))

        subtotal = Decimal("0")

        for cart_item in items:
            product = products_by_id.get(cart_item.product_id)

            if not product or product.seller_id is None:
                db.session.rollback()
                flash("Produk tidak valid.", "error")
                return redirect(url_for("cart"))

            if (
                not isinstance(cart_item.qty, int)
                or isinstance(cart_item.qty, bool)
                or cart_item.qty <= 0
            ):
                db.session.rollback()
                flash("Jumlah produk tidak valid.", "error")
                return redirect(url_for("cart"))

            if product.stock is None or product.stock < cart_item.qty:
                db.session.rollback()
                flash(
                    f"Stok {product.name} tidak mencukupi. "
                    f"Stok tersedia: {product.stock or 0}.",
                    "error"
                )
                return redirect(url_for("cart"))

            price = Decimal(str(product.price))

            if not price.is_finite() or price < 0:
                db.session.rollback()
                flash(
                    f"Harga produk {product.name} tidak valid.",
                    "error"
                )
                return redirect(url_for("cart"))

            subtotal += price * cart_item.qty

        # ==================================================
        # 4. HITUNG ONGKOS KIRIM
        # ==================================================
        fee = delivery_fee(dist) if method == "delivery" else 0

        if (
            isinstance(fee, bool)
            or not isinstance(fee, (int, float))
            or not math.isfinite(fee)
            or fee < 0
            or not float(fee).is_integer()
        ):
            raise ValueError("Ongkos kirim tidak valid.")

        fee = int(fee)
        total = subtotal + Decimal(fee)

        # Midtrans menerima nominal dalam satuan rupiah bulat.
        if (
            not subtotal.is_finite()
            or not total.is_finite()
            or total <= 0
            or subtotal != subtotal.to_integral_value()
            or total != total.to_integral_value()
        ):
            raise ValueError(
                "Total pembayaran harus berupa rupiah bulat "
                "dan lebih dari nol."
            )

        # ==================================================
        # 5. BUAT PESANAN DAN DETAIL PRODUK
        # ==================================================
        o = Order(
            order_number=(
                "PR-"
                + datetime.now().strftime("%Y%m%d%H%M%S")
                + "-"
                + uuid.uuid4().hex[:5].upper()
            ),
            buyer_id=current_user.id,
            subtotal=subtotal,
            delivery_method=method,
            delivery_address=addr if method == "delivery" else None,
            recipient_name=recipient_name,
            recipient_phone=recipient_phone,
            delivery_note=delivery_note,
            latitude=lat,
            longitude=lng,
            distance_km=dist,
            delivery_fee=fee,
            total=total,
            order_status="Menunggu Pembayaran",
            payment_status="pending",
            seller_amount_status="Menunggu Pembayaran",
            stock_restored=False,
        )

        db.session.add(o)
        db.session.flush()

        for cart_item in items:
            product = products_by_id[cart_item.product_id]
            item_subtotal = (
                Decimal(str(product.price)) * cart_item.qty
            )

            db.session.add(
                OrderItem(
                    order_id=o.id,
                    product_id=product.id,
                    seller_id=product.seller_id,
                    product_name=product.name,
                    price=product.price,
                    qty=cart_item.qty,
                    subtotal=item_subtotal,
                )
            )

            product.stock -= cart_item.qty

        payment = Payment(
            order_id=o.id,
            gross_amount=total,
        )
        db.session.add(payment)

        # Hapus keranjang dalam transaksi database yang sama.
        for cart_item in items:
            db.session.delete(cart_item)

        # Pesanan, detail, pembayaran, dan stok disimpan bersama.
        db.session.commit()

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            "Gagal membuat pesanan untuk pembeli ID %s",
            current_user.id,
        )

        flash(
            "Pesanan gagal dibuat. Silakan periksa keranjang "
            "dan coba kembali.",
            "error"
        )
        return redirect(url_for("cart"))

    # ==================================================
    # 6. BUAT TRANSAKSI MIDTRANS
    # ==================================================
    snap_token = ""

    try:
        snap = create_snap(
            o.order_number,
            o.total,
            current_user,
        )

        snap_token = snap.get("token")

        if not snap_token:
            raise ValueError(
                "Midtrans tidak mengembalikan token pembayaran."
            )

        payment.snap_token = snap_token
        db.session.commit()

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            "Gagal membuat transaksi Midtrans untuk pesanan %s",
            o.order_number,
        )

        flash(
            "Pesanan sudah tercatat, tetapi pembayaran belum "
            "dapat dibuka. Periksa status transaksi sebelum "
            "mencoba membuat pembayaran kembali.",
            "error",
        )

    # ==================================================
    # 7. NOTIFIKASI INTERNAL PEMBELI
    # ==================================================
    try:
        notify(
            current_user.id,
            "Pesanan dibuat",
            f"Pesanan {o.order_number} menunggu pembayaran.",
            "order",
            o.id,
        )
        db.session.commit()

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            "Gagal membuat notifikasi untuk pesanan %s",
            o.order_number,
        )

    # Notifikasi email/WhatsApp pedagang tetap dikirim oleh
    # webhook setelah pembayaran dikonfirmasi.

    return render_template(
        "buyer/checkout.html",
        order=o,
        snap_token=snap_token,
        client_key=app.config["MIDTRANS_CLIENT_KEY"],
        payment_page=True,
    )



@app.route("/orders/<int:oid>/pay")
@login_required
@roles("buyer")
def pay_order(oid):
    o = Order.query.filter_by(
        id=oid,
        buyer_id=current_user.id
    ).first_or_404()

    # Pesanan yang sudah dibayar tidak boleh dibayar ulang.
    if o.payment_status == "paid":
        flash("Pesanan ini sudah dibayar.", "success")
        return redirect(url_for("order_detail", oid=o.id))

    # Hanya pesanan yang masih menunggu pembayaran yang dapat dibayar.
    if o.order_status != "Menunggu Pembayaran":
        flash("Pesanan ini tidak dapat dibayar.", "error")
        return redirect(url_for("order_detail", oid=o.id))

    # Pesanan yang stoknya sudah dikembalikan tidak boleh dibayar.
    if o.stock_restored:
        current_app.logger.error(
            "Pembayaran ditolak karena stok sudah dikembalikan. "
            "Nomor pesanan: %s",
            o.order_number
        )
        flash(
            "Pesanan ini sudah tidak dapat dibayar. "
            "Silakan hubungi admin.",
            "error"
        )
        return redirect(url_for("order_detail", oid=o.id))

    # Ambil data pembayaran yang tersimpan.
    payment = Payment.query.filter_by(
        order_id=o.id
    ).first()

    if not payment:
        current_app.logger.error(
            "Data pembayaran tidak ditemukan untuk pesanan %s",
            o.order_number
        )
        flash(
            "Data pembayaran tidak ditemukan. Silakan hubungi admin.",
            "error"
        )
        return redirect(url_for("order_detail", oid=o.id))

    # Gunakan Snap Token yang sudah tersimpan.
    snap_token = payment.snap_token

    if not snap_token:
        current_app.logger.warning(
            "Token Snap kosong untuk pesanan %s. "
            "Status transaksi Midtrans perlu diperiksa sebelum "
            "membuat transaksi baru.",
            o.order_number
        )
        flash(
            "Sesi pembayaran belum tersedia. Silakan coba kembali "
            "nanti atau hubungi admin jika masalah berlanjut.",
            "error"
        )
        return redirect(url_for("order_detail", oid=o.id))

    # Tampilkan halaman pembayaran Midtrans.
    return render_template(
        "buyer/checkout.html",
        order=o,
        snap_token=snap_token,
        client_key=app.config["MIDTRANS_CLIENT_KEY"],
        payment_page=True
    )

@app.route("/orders/<int:oid>/cancel", methods=["POST"])
@login_required
@roles("buyer")
def cancel_order(oid):
    # Pastikan pesanan milik pembeli yang sedang login.
    o = Order.query.filter_by(
        id=oid,
        buyer_id=current_user.id
    ).first_or_404()

    try:
        # Kunci pesanan selama transaksi pembatalan.
        o = (
            Order.query
            .filter_by(
                id=oid,
                buyer_id=current_user.id
            )
            .with_for_update()
            .first()
        )

        if not o:
            db.session.rollback()
            flash("Pesanan tidak ditemukan.", "error")
            return redirect(url_for("orders"))

        # Pesanan yang sudah dibayar tidak dapat dibatalkan.
        if o.payment_status == "paid":
            db.session.rollback()
            flash(
                "Pesanan yang sudah dibayar tidak dapat dibatalkan.",
                "error"
            )
            return redirect(url_for("order_detail", oid=o.id))

        # Pesanan yang tidak lagi menunggu pembayaran tidak dapat dibatalkan.
        if o.order_status != "Menunggu Pembayaran":
            db.session.rollback()
            flash(
                "Pesanan hanya dapat dibatalkan saat menunggu pembayaran.",
                "error"
            )
            return redirect(url_for("order_detail", oid=o.id))

        # Jangan membatalkan jika stok sudah pernah dikembalikan.
        if o.stock_restored:
            db.session.rollback()
            flash(
                "Stok pesanan ini sudah dikembalikan. "
                "Silakan hubungi admin.",
                "error"
            )
            return redirect(url_for("order_detail", oid=o.id))

        # Kunci data pembayaran untuk memeriksa status terakhir di database.
        payment = (
            Payment.query
            .filter_by(order_id=o.id)
            .with_for_update()
            .first()
        )

        if not payment:
            db.session.rollback()
            current_app.logger.error(
                "Data pembayaran tidak ditemukan untuk pesanan %s",
                o.order_number
            )
            flash(
                "Data pembayaran tidak ditemukan. Silakan hubungi admin.",
                "error"
            )
            return redirect(url_for("order_detail", oid=o.id))

        # Cegah pembatalan jika database sudah mencatat transaksi sukses.
        if payment.transaction_status in ("settlement", "capture"):
            db.session.rollback()
            flash(
                "Pembayaran telah diterima atau perlu diverifikasi. "
                "Pesanan tidak dapat dibatalkan melalui menu ini.",
                "error"
            )
            return redirect(url_for("order_detail", oid=o.id))

        # Pulihkan stok produk dengan urutan penguncian konsisten.
        product_ids = sorted({
            item.product_id
            for item in o.items
            if item.product_id is not None
        })

        products = []

        if product_ids:
            products = (
                Product.query
                .filter(Product.id.in_(product_ids))
                .order_by(Product.id)
                .with_for_update()
                .all()
            )

        products_by_id = {
            product.id: product
            for product in products
        }

        for item in o.items:
            product = products_by_id.get(item.product_id)

            if product:
                product.stock += item.qty

        o.stock_restored = True
        o.order_status = "Dibatalkan"
        o.payment_status = "cancelled"
        o.seller_amount_status = "Dibatalkan"

        # Perbarui status pembayaran lokal tanpa mengubah transaksi
        # yang sudah berhasil atau sedang menunggu konfirmasi.
        if payment.transaction_status not in (
            "settlement",
            "capture",
            "pending"
        ):
            payment.transaction_status = "cancel"

        # Notifikasi internal pembeli.
        notify(
            current_user.id,
            "Pesanan Dibatalkan",
            f"Pesanan {o.order_number} berhasil dibatalkan.",
            "order",
            o.id
        )

        db.session.commit()

        flash(
            f"Pesanan {o.order_number} berhasil dibatalkan.",
            "success"
        )

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            "Gagal membatalkan pesanan ID %s",
            oid
        )

        flash(
            "Pesanan gagal dibatalkan. Silakan coba kembali.",
            "error"
        )

    return redirect(url_for("order_detail", oid=oid))



@app.route("/orders")
@login_required
@roles("buyer")
def orders():
    return render_template(
        "buyer/orders.html",
        orders=Order.query.filter_by(buyer_id=current_user.id)
        .order_by(Order.created_at.desc())
        .all(),
    )



@app.route("/orders/<int:oid>")
@login_required
def order_detail(oid):
    o = db.session.get(Order, oid) or abort(404)

    if current_user.role == "buyer" and o.buyer_id != current_user.id:
        abort(403)

    if current_user.role == "seller" and not any(
        x.seller_id == current_user.id for x in o.items
    ):
        abort(403)

    existing_rating = Rating.query.filter_by(
        order_id=o.id,
        buyer_id=current_user.id
    ).first()

    return render_template(
        "buyer/order_detail.html",
        order=o,
        existing_rating=existing_rating
    )




@app.post("/orders/<int:oid>/complete")
@login_required
@roles("buyer")
def complete_order(oid):
    try:
        # Kunci pesanan untuk mencegah penyelesaian bersamaan.
        o = (
            Order.query
            .filter_by(
                id=oid,
                buyer_id=current_user.id
            )
            .with_for_update()
            .first_or_404()
        )

        # Pesanan tidak boleh diselesaikan berulang kali.
        if o.order_status == "Selesai":
            db.session.rollback()
            flash(
                "Pesanan ini sudah diselesaikan.",
                "error"
            )
            return redirect(url_for("order_detail", oid=oid))

        # Pastikan pembayaran telah berhasil.
        if o.payment_status != "paid":
            db.session.rollback()
            flash(
                "Pesanan belum dibayar dan tidak dapat diselesaikan.",
                "error"
            )
            return redirect(url_for("order_detail", oid=oid))

        # Pastikan status pesanan memenuhi syarat.
        if o.order_status not in (
            "Siap Diambil",
            "Dalam Pengantaran"
        ):
            db.session.rollback()
            flash(
                "Pesanan belum dapat diselesaikan.",
                "error"
            )
            return redirect(url_for("order_detail", oid=oid))

        # Kelompokkan item berdasarkan pedagang.
        seller_ids = sorted({
            item.seller_id
            for item in o.items
        })

        # Validasi data item sebelum memindahkan saldo.
        if not seller_ids:
            db.session.rollback()
            flash(
                "Data pedagang pada pesanan tidak ditemukan.",
                "error"
            )
            return redirect(url_for("order_detail", oid=oid))

        seller_amounts = {}

        for sid in seller_ids:
            amount = sum(
                (
                    item.subtotal
                    for item in o.items
                    if item.seller_id == sid
                ),
                0
            )

            if amount <= 0:
                db.session.rollback()
                flash(
                    "Nominal dana pedagang tidak valid.",
                    "error"
                )
                return redirect(url_for("order_detail", oid=oid))

            seller_amounts[sid] = amount

        # Kunci saldo pedagang dalam urutan ID yang konsisten.
        balances = (
            SellerBalance.query
            .filter(SellerBalance.seller_id.in_(seller_ids))
            .order_by(SellerBalance.seller_id)
            .with_for_update()
            .all()
        )

        balances_by_seller = {
            balance.seller_id: balance
            for balance in balances
        }

        # Pastikan semua saldo tersedia dan mencukupi.
        for sid in seller_ids:
            balance = balances_by_seller.get(sid)

            if not balance:
                db.session.rollback()
                current_app.logger.error(
                    "Saldo pedagang %s tidak ditemukan "
                    "untuk pesanan %s.",
                    sid,
                    o.order_number
                )
                flash(
                    "Data saldo pedagang tidak ditemukan. "
                    "Silakan hubungi admin.",
                    "error"
                )
                return redirect(url_for("order_detail", oid=oid))

            if balance.held_balance < seller_amounts[sid]:
                db.session.rollback()
                current_app.logger.error(
                    "Saldo tertahan tidak mencukupi untuk "
                    "pedagang %s pada pesanan %s.",
                    sid,
                    o.order_number
                )
                flash(
                    "Dana tertahan tidak sesuai dengan data pesanan. "
                    "Silakan hubungi admin.",
                    "error"
                )
                return redirect(url_for("order_detail", oid=oid))

        # Periksa verifikasi setiap pedagang.
        seller_profiles = (
            SellerProfile.query
            .filter(SellerProfile.user_id.in_(seller_ids))
            .all()
        )

        profiles_by_seller = {
            profile.user_id: profile
            for profile in seller_profiles
        }

        all_sellers_verified = all(
            profiles_by_seller.get(sid) is not None
            and profiles_by_seller[sid].verification_status == "approved"
            for sid in seller_ids
        )

        # Pesanan selesai, tetapi dana hanya dilepas jika
        # seluruh pedagang sudah disetujui admin.
        if all_sellers_verified:
            for sid in seller_ids:
                balance = balances_by_seller[sid]
                amount = seller_amounts[sid]

                balance.held_balance -= amount
                balance.available_balance += amount
                balance.total_earned += amount

                notify(
                    sid,
                    "Dana tersedia",
                    (
                        f"Dana pesanan {o.order_number} "
                        "telah tersedia untuk dicairkan."
                    ),
                    "balance",
                    o.id
                )

            o.seller_amount_status = "Dana Dapat Dicairkan"

        else:
            # Dana tetap tertahan sampai verifikasi disetujui admin.
            o.seller_amount_status = "Menunggu Verifikasi Pedagang"

        # Tandai pesanan selesai setelah seluruh validasi berhasil.
        o.order_status = "Selesai"
        o.completed_at = datetime.utcnow()

        notify(
            current_user.id,
            "Pesanan selesai",
            (
                f"Pesanan {o.order_number} selesai. "
                "Silakan beri rating."
            ),
            "rating",
            o.id
        )

        db.session.commit()

        if all_sellers_verified:
            flash(
                "Pesanan diselesaikan. Dana pedagang telah tersedia.",
                "success"
            )
        else:
            flash(
                "Pesanan diselesaikan. Dana tetap ditahan "
                "sampai verifikasi pedagang disetujui admin.",
                "success"
            )

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            "Gagal menyelesaikan pesanan ID %s",
            oid
        )

        flash(
            "Pesanan gagal diselesaikan. Silakan coba kembali.",
            "error"
        )

    return redirect(url_for("order_detail", oid=oid))


@app.post("/orders/<int:oid>/rating")
@login_required
@roles("buyer")
def rating(oid):
    o = db.session.get(Order, oid) or abort(404)
    if o.buyer_id != current_user.id or o.order_status != "Selesai":
        abort(403)
    for i in o.items:
        if not Rating.query.filter_by(
            order_id=oid, buyer_id=current_user.id, product_id=i.product_id
        ).first():
            db.session.add(
                Rating(
                    order_id=oid,
                    buyer_id=current_user.id,
                    seller_id=i.seller_id,
                    product_id=i.product_id,
                    seller_rating=int(request.form["seller_rating"]),
                    product_rating=int(request.form["product_rating"]),
                    comment=request.form.get("comment"),
                )
            )
    db.session.commit()
    flash("Rating berhasil disimpan.", "success")
    return redirect(url_for("order_detail", oid=oid))



@app.post("/payment/notification")
def payment_notification():
    data = request.get_json(silent=True) or {}

    # 1. Verifikasi signature Midtrans
    server_key = (
        app.config.get("MIDTRANS_SERVER_KEY")
        or os.getenv("MIDTRANS_SERVER_KEY")
    )

    order_id = str(data.get("order_id", ""))
    status_code = str(data.get("status_code", ""))
    gross_amount = str(data.get("gross_amount", ""))
    signature_key = str(data.get("signature_key", ""))

    if not all((
        server_key,
        order_id,
        status_code,
        gross_amount,
        signature_key,
    )):
        current_app.logger.warning(
            "Webhook Midtrans ditolak: data signature tidak lengkap."
        )
        return jsonify(
            ok=False,
            message="Data signature tidak lengkap"
        ), 401

    signature_string = (
        order_id + status_code + gross_amount + server_key
    )

    expected_signature = hashlib.sha512(
        signature_string.encode("utf-8")
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature_key):
        current_app.logger.warning(
            "Webhook Midtrans ditolak: signature tidak valid."
        )
        return jsonify(
            ok=False,
            message="Signature tidak valid"
        ), 403

    # 2. Proses notifikasi dalam transaksi database
    try:
        o = (
            Order.query
            .filter_by(order_number=order_id)
            .with_for_update()
            .first()
        )

        if not o:
            db.session.rollback()

            if order_id.startswith("payment_notif_test_"):
                current_app.logger.info(
                    "Notifikasi uji Midtrans diterima."
                )
                return jsonify(
                    ok=True,
                    message="Notifikasi uji berhasil diterima."
                ), 200

            current_app.logger.warning(
                "Pesanan tidak ditemukan untuk webhook: %s",
                order_id
            )
            return jsonify(
                ok=False,
                message="Pesanan tidak ditemukan"
            ), 404

        payment = (
            Payment.query
            .filter_by(order_id=o.id)
            .with_for_update()
            .first()
        )

        if not payment:
            db.session.rollback()
            current_app.logger.error(
                "Data pembayaran tidak ditemukan untuk pesanan %s",
                order_id
            )
            return jsonify(
                ok=False,
                message="Data pembayaran tidak ditemukan"
            ), 500

        status = data.get("transaction_status")

        allowed_statuses = {
            "settlement",
            "capture",
            "pending",
            "expire",
            "cancel",
            "deny",
        }

        if status not in allowed_statuses:
            db.session.rollback()
            current_app.logger.warning(
                "Status Midtrans tidak ditangani: %s",
                status
            )
            return jsonify(ok=True), 200

        # 3. Validasi nominal transaksi
        try:
            received_amount = Decimal(gross_amount)
            expected_amount = Decimal(str(o.total))

            if (
                not received_amount.is_finite()
                or received_amount != expected_amount
            ):
                db.session.rollback()
                current_app.logger.error(
                    "Nominal webhook tidak cocok untuk pesanan %s.",
                    order_id
                )
                return jsonify(
                    ok=False,
                    message="Nominal transaksi tidak cocok"
                ), 400

        except (InvalidOperation, ValueError):
            db.session.rollback()
            return jsonify(
                ok=False,
                message="Nominal transaksi tidak valid"
            ), 400

        # 4. Tentukan apakah transaksi benar-benar berhasil
        success = status == "settlement"

        if status == "capture":
            fraud_status = data.get("fraud_status")
            success = fraud_status == "accept"

            if not success:
                payment.transaction_id = data.get("transaction_id")
                payment.payment_type = data.get("payment_type")
                payment.transaction_status = status
                payment.raw_response = json.dumps(
                    data,
                    ensure_ascii=False
                )

                db.session.commit()

                current_app.logger.warning(
                    "Capture belum diterima untuk pesanan %s. "
                    "Fraud status: %s",
                    order_id,
                    fraud_status
                )

                return jsonify(
                    ok=True,
                    message="Transaksi capture belum diterima."
                ), 200

        # 5. Pertahankan status lunas jika notifikasi gagal
        # datang terlambat.
        if o.payment_status == "paid" and not success:
            payment.raw_response = json.dumps(
                data,
                ensure_ascii=False
            )
            db.session.commit()

            return jsonify(
                ok=True,
                message="Status pembayaran lunas dipertahankan."
            ), 200

        # Simpan informasi transaksi
        payment.transaction_id = data.get("transaction_id")
        payment.payment_type = data.get("payment_type")
        payment.raw_response = json.dumps(
            data,
            ensure_ascii=False
        )

        # 6. Pembayaran berhasil
        if success:
            already_paid = o.payment_status == "paid"

            cancelled_before_payment = (
                o.order_status == "Dibatalkan"
                or o.stock_restored
            )

            payment.transaction_status = status

            if not payment.paid_at:
                payment.paid_at = datetime.utcnow()

            # Pembayaran masuk setelah pembatalan atau stok dipulihkan.
            # Tandai untuk pemeriksaan admin, tanpa menambah saldo pedagang.
            if cancelled_before_payment:
                o.payment_status = "paid"
                o.order_status = "Perlu Pemeriksaan"
                o.seller_amount_status = "Perlu Pemeriksaan"

                db.session.commit()

                current_app.logger.error(
                    "Pembayaran masuk setelah pembatalan/pemulihan "
                    "stok. Pesanan %s memerlukan pemeriksaan admin.",
                    order_id
                )

                return jsonify(
                    ok=True,
                    message=(
                        "Pembayaran diterima dan memerlukan "
                        "pemeriksaan admin."
                    )
                ), 200

            # Jangan menambahkan saldo atau notifikasi dua kali.
            if already_paid:
                db.session.commit()

                return jsonify(
                    ok=True,
                    message="Pembayaran sudah diproses sebelumnya."
                ), 200

            # Kelompokkan subtotal produk berdasarkan pedagang.
            seller_amounts = {}

            for item in o.items:
                sid = item.seller_id

                seller_amounts[sid] = (
                    seller_amounts.get(sid, 0)
                    + item.subtotal
                )

            seller_ids = sorted(seller_amounts.keys())

            if not seller_ids:
                db.session.rollback()

                current_app.logger.error(
                    "Tidak ada item pedagang pada pesanan %s.",
                    order_id
                )

                return jsonify(
                    ok=False,
                    message="Item pedagang tidak ditemukan"
                ), 500

            # Validasi nominal setiap pedagang.
            for sid, amount in seller_amounts.items():
                if amount is None or amount <= 0:
                    db.session.rollback()

                    current_app.logger.error(
                        "Subtotal pedagang %s tidak valid "
                        "untuk pesanan %s.",
                        sid,
                        order_id
                    )

                    return jsonify(
                        ok=False,
                        message="Subtotal pedagang tidak valid"
                    ), 400

            # Kunci saldo dalam urutan seller_id yang konsisten.
            balances = (
                SellerBalance.query
                .filter(
                    SellerBalance.seller_id.in_(seller_ids)
                )
                .order_by(SellerBalance.seller_id)
                .with_for_update()
                .all()
            )

            balances_by_seller = {
                balance.seller_id: balance
                for balance in balances
            }

            # Pastikan seluruh pedagang memiliki data saldo.
            # Jika ada yang belum memiliki saldo, batalkan transaksi
            # agar pembayaran tidak tercatat lunas tanpa pencatatan dana.
            missing_sellers = [
                sid for sid in seller_ids
                if sid not in balances_by_seller
            ]

            if missing_sellers:
                db.session.rollback()

                current_app.logger.error(
                    "Saldo belum tersedia untuk pedagang %s "
                    "pada pesanan %s.",
                    missing_sellers,
                    order_id
                )

                return jsonify(
                    ok=False,
                    message="Data saldo pedagang belum tersedia"
                ), 500

            # CATAT DANA TERTAHAN.
            # Dilakukan hanya pada pembayaran pertama yang berhasil.
            for sid in seller_ids:
                balance = balances_by_seller[sid]
                balance.held_balance += seller_amounts[sid]

            # Perbarui status pembayaran dan pesanan.
            o.payment_status = "paid"
            o.order_status = "Dibayar"
            o.seller_amount_status = "Dana Ditahan"

            # Buat notifikasi internal.
            notify(
                o.buyer_id,
                "Pembayaran Berhasil",
                (
                    f"Pembayaran pesanan {o.order_number} berhasil "
                    f"dikonfirmasi. Total: {rupiah(o.total)}."
                ),
                "order",
                o.id,
            )

            for sid in seller_ids:
                notify(
                    sid,
                    "Pesanan baru",
                    f"Pesanan {o.order_number} sudah dibayar.",
                    "order",
                    o.id,
                )

            # Simpan status pembayaran, saldo tertahan, dan notifikasi
            # dalam satu transaksi database.
            db.session.commit()

            # 7. Kirim email/WhatsApp setelah transaksi tersimpan.
            try:
                buyer = db.session.get(User, o.buyer_id)
                buyer_name = buyer.name if buyer else "Pembeli"

                for sid in seller_ids:
                    seller = db.session.get(User, sid)

                    if not seller:
                        continue

                    seller_items = [
                        item for item in o.items
                        if item.seller_id == sid
                    ]

                    product_details = "\n".join(
                        f"- {item.product_name} x {item.qty} "
                        f"({rupiah(item.subtotal)})"
                        for item in seller_items
                    )

                    seller_subtotal = seller_amounts[sid]

                    message = (
                        f"Halo {seller.name or 'Pedagang'},\n\n"
                        "Ada pesanan baru yang sudah dibayar.\n\n"
                        f"Nomor pesanan: {o.order_number}\n"
                        f"Pembeli: {buyer_name}\n"
                        f"Produk:\n{product_details}\n\n"
                        f"Subtotal produk Anda: "
                        f"{rupiah(seller_subtotal)}\n"
                        f"Metode pesanan: {o.delivery_method}\n\n"
                        "Silakan buka sistem Pasar Remboken "
                        "untuk memproses pesanan."
                    )

                    send_order_notification(
                        seller.email,
                        seller.phone,
                        f"Pesanan baru {o.order_number}",
                        message,
                    )

            except Exception:
                current_app.logger.exception(
                    "Gagal mengirim email/WhatsApp untuk pesanan %s.",
                    order_id
                )

            return jsonify(ok=True), 200

        # 8. Pembayaran gagal, dibatalkan, atau kedaluwarsa
        if status in ("expire", "cancel", "deny"):
            # Jangan memulihkan stok dua kali.
            if (
                o.order_status == "Dibatalkan"
                or o.stock_restored
            ):
                db.session.commit()

                return jsonify(
                    ok=True,
                    message="Pesanan sudah dibatalkan sebelumnya."
                ), 200

            # Kunci produk berdasarkan urutan ID yang konsisten.
            product_ids = sorted({
                item.product_id
                for item in o.items
                if item.product_id is not None
            })

            locked_products = []

            if product_ids:
                locked_products = (
                    Product.query
                    .filter(Product.id.in_(product_ids))
                    .order_by(Product.id)
                    .with_for_update()
                    .all()
                )

            products_by_id = {
                product.id: product
                for product in locked_products
            }

            for item in o.items:
                product = products_by_id.get(item.product_id)

                if product:
                    product.stock += item.qty

            o.stock_restored = True
            o.payment_status = "failed"
            o.order_status = "Dibatalkan"
            o.seller_amount_status = "Dibatalkan"

            payment.transaction_status = status

            db.session.commit()

            current_app.logger.info(
                "Pesanan %s dibatalkan dengan status Midtrans %s; "
                "stok dipulihkan.",
                order_id,
                status
            )

            return jsonify(ok=True), 200

        # 9. Pembayaran masih menunggu
        if status == "pending":
            if (
                o.payment_status != "paid"
                and o.order_status != "Dibatalkan"
                and not o.stock_restored
            ):
                o.payment_status = "pending"
                payment.transaction_status = "pending"

            db.session.commit()
            return jsonify(ok=True), 200

        db.session.commit()
        return jsonify(ok=True), 200

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            "Gagal memproses webhook Midtrans untuk order_id %s",
            order_id
        )

        return jsonify(
            ok=False,
            message="Gagal memproses notifikasi pembayaran"
        ), 500


@app.route("/admin/reports/export-excel")
@login_required
@roles("admin")
def admin_reports_export_excel():

    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()
    status = request.args.get("status", "").strip()
    search = request.args.get("search", "").strip()
    delivery_method = request.args.get("delivery_method", "").strip()

    query = Order.query

    # Filter tanggal mulai
    if start:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            query = query.filter(Order.created_at >= start_date)
        except ValueError:
            pass

    # Filter tanggal selesai
    if end:
        try:
            end_date = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Order.created_at < end_date)
        except ValueError:
            pass

    # Filter status
    if status:
        query = query.filter(Order.order_status == status)

    # Filter metode pengiriman
    if delivery_method:
        query = query.filter(Order.delivery_method == delivery_method)

    # Filter pencarian
    if search:
        search_pattern = f"%{search}%"

        query = query.outerjoin(
            User,
            Order.buyer_id == User.id
        ).filter(
            db.or_(
                Order.order_number.ilike(search_pattern),
                User.name.ilike(search_pattern),
                User.email.ilike(search_pattern)
            )
        )

    orders = query.order_by(Order.created_at.desc()).all()

    # ==========================================
    # DATA LAPORAN
    # ==========================================

    data = []

    for no, order in enumerate(orders, start=1):

        if order.delivery_method == "pickup":
            metode = "Ambil di Tempat"
        elif order.delivery_method == "delivery":
            metode = "Pengantaran"
        else:
            metode = order.delivery_method or "-"

        data.append({
            "No": no,
            "Tanggal": (
                order.created_at.strftime("%d-%m-%Y %H:%M")
                if order.created_at else "-"
            ),
            "Nomor Order": order.order_number or "-",
            "Nama Pembeli": (
                order.buyer.name
                if order.buyer else "-"
            ),
            "Email Pembeli": (
                order.buyer.email
                if order.buyer else "-"
            ),
            "Metode": metode,
            "Status Pesanan": order.order_status or "-",
            "Status Pembayaran": order.payment_status or "-",
            "Subtotal": float(order.subtotal or 0),
            "Biaya Pengantaran": float(order.delivery_fee or 0),
            "Total": float(order.total or 0),
        })

    # ==========================================
    # DATAFRAME
    # ==========================================

    df = pd.DataFrame(data)

    # ==========================================
    # BUAT FILE EXCEL DI MEMORY
    # ==========================================

    output = BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        df.to_excel(
            writer,
            index=False,
            sheet_name="Laporan Transaksi"
        )

        workbook = writer.book
        worksheet = writer.sheets["Laporan Transaksi"]

        # ==========================================
        # FORMAT HEADER
        # ==========================================

        from openpyxl.styles import Font, Alignment, PatternFill

        header_fill = PatternFill(
            fill_type="solid",
            fgColor="1F2937"
        )

        header_font = Font(
            bold=True,
            color="FFFFFF"
        )

        for cell in worksheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(
                horizontal="center",
                vertical="center"
            )

        # ==========================================
        # FORMAT KOLOM
        # ==========================================

        currency_columns = [
            "Subtotal",
            "Biaya Pengantaran",
            "Total"
        ]

        for column_name in currency_columns:

            column_index = None

            for cell in worksheet[1]:

                if cell.value == column_name:
                    column_index = cell.column
                    break

            if column_index:

                for row in range(2, worksheet.max_row + 1):
                    worksheet.cell(
                        row=row,
                        column=column_index
                    ).number_format = '#,##0'

        # ==========================================
        # AUTO WIDTH
        # ==========================================

        for column_cells in worksheet.columns:

            max_length = 0
            column_letter = column_cells[0].column_letter

            for cell in column_cells:

                try:
                    value_length = len(str(cell.value))
                    if value_length > max_length:
                        max_length = value_length
                except Exception:
                    pass

            worksheet.column_dimensions[
                column_letter
            ].width = min(max_length + 3, 40)

        # ==========================================
        # FREEZE HEADER
        # ==========================================

        worksheet.freeze_panes = "A2"

        # ==========================================
        # FILTER EXCEL
        # ==========================================

        if worksheet.max_row >= 1:
            worksheet.auto_filter.ref = worksheet.dimensions

    output.seek(0)

    # ==========================================
    # NAMA FILE
    # ==========================================

    filename = "laporan_transaksi"

    if start and end:
        filename += f"_{start}_sampai_{end}"
    elif start:
        filename += f"_mulai_{start}"
    elif end:
        filename += f"_sampai_{end}"

    filename += ".xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )


@app.route("/seller")
@login_required
@roles("seller")
def seller_dashboard():
    return render_template(
        "seller/dashboard.html",
        products=Product.query.filter_by(seller_id=current_user.id).all(),
        orders=Order.query.join(OrderItem)
        .filter(OrderItem.seller_id == current_user.id)
        .distinct()
        .order_by(Order.created_at.desc())
        .limit(10)
        .all(),
        balance=current_user.balance,
    )


@app.route("/seller/products")
@login_required
@roles("seller")
def seller_products():
    return render_template(
        "seller/products.html",
        products=Product.query.filter_by(seller_id=current_user.id)
        .order_by(Product.created_at.desc())
        .all(),
        approved=seller_ok(),
    )


@app.route("/seller/products/new", methods=["GET", "POST"])
@login_required
@roles("seller")
def product_new():
    if not seller_ok():
        flash("Akun pedagang belum disetujui admin.", "error")
        return redirect(url_for("seller_products"))

    if request.method == "POST":

        files = request.files.getlist("images")
        files = [f for f in files if f and f.filename][:5]

        saved_images = []

        for f in files:
            fn = f"{uuid.uuid4().hex}_{secure_filename(f.filename)}"
            f.save(os.path.join(PROD, fn))
            saved_images.append(fn)

        p = Product(
            seller_id=current_user.id,
            category_id=request.form.get("category_id") or None,
            name=request.form["name"],
            description=request.form.get("description"),
            price=int(request.form["price"]),
            stock=int(request.form["stock"]),
            image=saved_images[0] if saved_images else "",
        )

        db.session.add(p)
        db.session.flush()

        for fn in saved_images:
            db.session.add(
                ProductImage(
                    product_id=p.id,
                    image=fn
                )
            )

        db.session.commit()

        flash("Produk ditambahkan.", "success")
        return redirect(url_for("seller_products"))

    return render_template(
        "seller/product_form.html",
        categories=Category.query.all(),
        product=None
    )


@app.route("/seller/products/<int:pid>/edit", methods=["GET", "POST"])
@login_required
@roles("seller")
def product_edit(pid):
    p = Product.query.filter_by(
        id=pid,
        seller_id=current_user.id
    ).first_or_404()

    # Jika produk lama masih menggunakan Product.image
    # dan belum memiliki data ProductImage, masukkan foto lama
    if not p.images and p.image:
        old_image = ProductImage(
            product_id=p.id,
            image=p.image
        )
        db.session.add(old_image)
        db.session.commit()

    if request.method == "POST":

        # ==================================================
        # DATA PRODUK
        # ==================================================
        p.name = request.form["name"]
        p.description = request.form.get("description")
        p.price = int(request.form["price"])
        p.stock = int(request.form["stock"])
        p.category_id = request.form.get("category_id") or None

        # ==================================================
        # HAPUS FOTO YANG DIPILIH
        # ==================================================
        delete_ids = request.form.getlist("delete_images")

        if delete_ids:
            images_to_delete = ProductImage.query.filter(
                ProductImage.product_id == p.id,
                ProductImage.id.in_([int(i) for i in delete_ids])
            ).all()

            for image in images_to_delete:

                image_path = os.path.join(
                    PROD,
                    image.image
                )

                if os.path.exists(image_path):
                    os.remove(image_path)

                db.session.delete(image)

        db.session.flush()

        # ==================================================
        # FOTO YANG MASIH TERSISA
        # ==================================================
        remaining_images = ProductImage.query.filter_by(
            product_id=p.id
        ).order_by(ProductImage.id).all()

        # ==================================================
        # FOTO BARU
        # ==================================================
        files = request.files.getlist("images")
        files = [
            f for f in files
            if f and f.filename
        ]

        available_slots = 5 - len(remaining_images)

        if len(files) > available_slots:
            flash(
                f"Foto produk maksimal 5. "
                f"Masih tersedia {available_slots} slot foto.",
                "error"
            )
            return redirect(
                url_for(
                    "product_edit",
                    pid=p.id
                )
            )

        for f in files:

            fn = f"{uuid.uuid4().hex}_{secure_filename(f.filename)}"

            f.save(
                os.path.join(PROD, fn)
            )

            new_image = ProductImage(
                product_id=p.id,
                image=fn
            )

            db.session.add(new_image)

        db.session.flush()

        # ==================================================
        # TENTUKAN FOTO UTAMA
        # ==================================================
        all_images = ProductImage.query.filter_by(
            product_id=p.id
        ).order_by(ProductImage.id).all()

        if all_images:
            p.image = all_images[0].image
        else:
            p.image = ""

        db.session.commit()

        flash("Produk diperbarui.", "success")

        return redirect(
            url_for("seller_products")
        )

    return render_template(
        "seller/product_form.html",
        categories=Category.query.all(),
        product=p
    )


@app.post("/seller/products/<int:pid>/delete")
@login_required
@roles("seller")
def product_delete(pid):
    p = Product.query.filter_by(id=pid, seller_id=current_user.id).first_or_404()
    p.is_active = False
    db.session.commit()
    flash("Produk dinonaktifkan.", "success")
    return redirect(url_for("seller_products"))


@app.route("/seller/orders")
@login_required
@roles("seller")
def seller_orders():
    return render_template(
        "seller/orders.html",
        orders=Order.query.join(OrderItem)
        .filter(OrderItem.seller_id == current_user.id)
        .distinct()
        .order_by(Order.created_at.desc())
        .all(),
    )



@app.post("/seller/orders/<int:oid>/status")
@login_required
@roles("seller")
def seller_status(oid):
    o = db.session.get(Order, oid) or abort(404)

    if not any(i.seller_id == current_user.id for i in o.items):
        abort(403)

    new_status = request.form.get("status")

    allowed_statuses = [
        "Diproses",
        "Siap Diambil",
        "Dalam Pengantaran",
        "Selesai",
    ]

    if new_status not in allowed_statuses:
        flash("Status pesanan tidak valid.", "error")
        return redirect(url_for("seller_orders"))

    # Pesanan harus sudah dibayar sebelum diproses
    if o.payment_status != "paid":
        flash("Pesanan belum dibayar.", "error")
        return redirect(url_for("seller_orders"))

    # Validasi alur status pesanan
    if o.order_status == "Dibayar":
        if new_status != "Diproses":
            flash("Pesanan harus diproses terlebih dahulu.", "error")
            return redirect(url_for("seller_orders"))

    elif o.order_status == "Diproses":
        if o.delivery_method == "pickup":
            if new_status != "Siap Diambil":
                flash(
                    "Pesanan ambil di pasar harus menjadi Siap Diambil.",
                    "error",
                )
                return redirect(url_for("seller_orders"))

        elif o.delivery_method == "delivery":
            if new_status != "Dalam Pengantaran":
                flash(
                    "Pesanan pengantaran harus menjadi Dalam Pengantaran.",
                    "error",
                )
                return redirect(url_for("seller_orders"))

    elif o.order_status == "Siap Diambil":
        if new_status != "Selesai":
            flash(
                "Pesanan siap diambil hanya dapat dilanjutkan ke Selesai.",
                "error",
            )
            return redirect(url_for("seller_orders"))

    elif o.order_status == "Dalam Pengantaran":
        if new_status != "Selesai":
            flash(
                "Pesanan dalam pengantaran hanya dapat dilanjutkan ke Selesai.",
                "error",
            )
            return redirect(url_for("seller_orders"))

    else:
        flash("Status pesanan tidak dapat diubah.", "error")
        return redirect(url_for("seller_orders"))

    # Simpan perubahan status
    o.order_status = new_status

    # Notifikasi internal kepada pembeli
    notify(
        o.buyer_id,
        "Status pesanan berubah",
        f"{o.order_number}: {o.order_status}.",
        "order",
        o.id,
    )

    db.session.commit()

    # ================================================
    # NOTIFIKASI EMAIL DAN WHATSAPP KEPADA PEMBELI
    # ================================================
    if (
        (
            o.delivery_method == "delivery"
            and new_status == "Dalam Pengantaran"
        )
        or (
            o.delivery_method == "pickup"
            and new_status == "Siap Diambil"
        )
    ):
        try:
            buyer = db.session.get(User, o.buyer_id)

            if buyer:
                if new_status == "Dalam Pengantaran":
                    message = (
                        f"Halo {buyer.name or 'Pembeli'},\n\n"
                        f"Pesanan Anda sedang dalam pengantaran.\n\n"
                        f"Nomor pesanan: {o.order_number}\n"
                        f"Status: Dalam Pengantaran\n"
                        f"Alamat tujuan: {o.delivery_address or '-'}\n\n"
                        "Silakan menunggu pesanan Anda."
                    )
                else:
                    message = (
                        f"Halo {buyer.name or 'Pembeli'},\n\n"
                        "Pesanan Anda sudah siap diambil.\n\n"
                        f"Nomor pesanan: {o.order_number}\n"
                        "Status: Siap Diambil\n\n"
                        "Silakan datang ke pasar untuk mengambil pesanan."
                    )

                try:
                    send_order_notification(
                        buyer.email,
                        buyer.phone,
                        f"Status pesanan {o.order_number}: {new_status}",
                        message,
                    )
                except Exception:
                    app.logger.exception(
                        "Gagal mengirim notifikasi kepada pembeli "
                        "untuk pesanan %s",
                        o.order_number,
                    )

        except Exception:
            app.logger.exception(
                "Terjadi kesalahan saat menyiapkan notifikasi pembeli "
                "untuk pesanan %s",
                o.order_number,
            )

    flash("Status pesanan diperbarui.", "success")
    return redirect(url_for("seller_orders"))


@app.route("/seller/balance", methods=["GET", "POST"])
@login_required
@roles("seller")
def seller_balance():
    if request.method == "POST":
        b = current_user.balance
        amount = int(request.form["amount"])

        if amount <= 0 or amount > b.available_balance:
            flash("Saldo tidak mencukupi.", "error")

        elif (
            not current_user.seller_profile
            or current_user.seller_profile.verification_status != "approved"
        ):
            flash("Profil pedagang harus disetujui admin.", "error")

        else:
            # Buat permintaan penarikan
            withdrawal = Withdrawal(
                seller_id=current_user.id,
                amount=amount,
                bank_name=request.form["bank_name"],
                bank_account=request.form["bank_account"],
                account_name=request.form["account_name"],
            )

            db.session.add(withdrawal)

            # Ambil ID permintaan penarikan sebelum membuat notifikasi
            db.session.flush()

            # Kurangi saldo yang tersedia
            b.available_balance -= amount

            # Notifikasi untuk pedagang
            notify(
                current_user.id,
                "Penarikan Diajukan",
                "Permintaan penarikan dana Anda berhasil dikirim "
                "dan sedang menunggu pemeriksaan admin.",
                "withdrawal",
                withdrawal.id,
            )

            # Notifikasi untuk seluruh admin
            admins = User.query.filter_by(role="admin").all()

            for admin in admins:
                notify(
                    admin.id,
                    "Permintaan Penarikan Dana",
                    f"Pedagang {current_user.name} mengajukan penarikan "
                    f"dana sebesar {rupiah(amount)}. "
                    "Silakan periksa dan proses permintaan tersebut.",
                    "withdrawal",
                    withdrawal.id,
                )

            # Simpan permintaan, perubahan saldo, dan notifikasi
            db.session.commit()

            flash("Permintaan penarikan dikirim.", "success")

    return render_template(
        "seller/balance.html",
        balance=current_user.balance,
        withdrawals=Withdrawal.query.filter_by(seller_id=current_user.id)
        .order_by(Withdrawal.requested_at.desc())
        .all(),
    )



@app.route("/seller/profile", methods=["GET", "POST"])
@login_required
@roles("seller")
def seller_profile():

    p = current_user.seller_profile

    if request.method == "POST":

        # =====================================================
        # DATA LAMA
        # =====================================================

        old_name = current_user.name
        old_phone = current_user.phone

        old_nik = p.nik
        old_address = p.address
        old_store_name = p.store_name
        old_store_address = p.store_address
        old_ktp_file = p.ktp_file

        # =====================================================
        # DATA AKUN
        # Email dan Password TIDAK memerlukan verifikasi admin
        # =====================================================

        current_user.name = request.form["name"].strip()
        current_user.email = request.form["email"].strip().lower()
        current_user.phone = request.form.get("phone", "").strip() or None

        # =====================================================
        # DATA PEDAGANG
        # =====================================================

        p.nik = request.form["nik"].strip()
        p.address = request.form.get("address", "").strip()
        p.store_name = request.form["store_name"].strip()
        p.store_address = request.form.get("store_address", "").strip()

        # =====================================================
        # DETEKSI PERUBAHAN DATA PENTING
        # =====================================================

        important_data_changed = (
            old_name != current_user.name
            or old_phone != current_user.phone
            or old_nik != p.nik
            or old_address != p.address
            or old_store_name != p.store_name
            or old_store_address != p.store_address
        )

        # =====================================================
        # UPLOAD KTP BARU
        # =====================================================

        f = request.files.get("ktp")

        if f and f.filename:

            fn = secure_filename(f.filename)

            fn = f"{uuid.uuid4().hex}_{fn}"

            f.save(os.path.join(KTP, fn))

            # Hapus KTP lama
            if p.ktp_file:

                old_path = os.path.join(KTP, p.ktp_file)

                if os.path.exists(old_path):
                    os.remove(old_path)

            p.ktp_file = fn

            # KTP merupakan data penting
            important_data_changed = True

        # =====================================================
        # GANTI PASSWORD
        # Password TIDAK memerlukan verifikasi admin
        # =====================================================

        password = request.form.get("password", "").strip()
        password_confirmation = request.form.get(
            "password_confirmation",
            ""
        ).strip()

        if password:

            if len(password) < 6:

                flash(
                    "Password baru minimal 6 karakter.",
                    "error"
                )

                return redirect(url_for("seller_profile"))

            if password != password_confirmation:

                flash(
                    "Konfirmasi password tidak cocok.",
                    "error"
                )

                return redirect(url_for("seller_profile"))

            current_user.set_password(password)

        # =====================================================
        # JIKA DATA PENTING BERUBAH
        # MAKA HARUS VERIFIKASI ADMIN
        # =====================================================

        if important_data_changed:

            p.verification_status = "pending"
            p.rejection_reason = None
            p.verified_at = None
            p.verified_by = None

            # Notifikasi ke pedagang
            notify(
                current_user.id,
                "Verifikasi Ulang Diperlukan",
                "Data penting pedagang Anda telah diubah. Perubahan tersebut harus diverifikasi kembali oleh admin.",
                "seller_verification",
            )

            # Notifikasi ke admin
            admins = User.query.filter_by(
                role="admin"
            ).all()

            for admin in admins:

                notify(
                    admin.id,
                    "Perubahan Data Pedagang",
                    f"Data penting pedagang {current_user.name} telah diubah dan membutuhkan verifikasi ulang.",
                    "seller_verification",
                    current_user.id,
                )

            message = (
                "Data berhasil diperbarui. "
                "Perubahan data penting sedang menunggu verifikasi admin."
            )

        else:

            # =================================================
            # HANYA EMAIL / PASSWORD YANG BERUBAH
            # TIDAK PERLU VERIFIKASI
            # =================================================

            message = "Profil berhasil diperbarui."

        # =====================================================
        # SIMPAN
        # =====================================================

        db.session.commit()

        flash(
            message,
            "success"
        )

        return redirect(
            url_for("seller_profile")
        )

    return render_template(
        "seller/profile.html",
        profile=p
    )
    
    
    

# =========================================================
# HALAMAN TOKO PENJUAL
# =========================================================
@app.route("/toko/<int:seller_id>")
def seller_store(seller_id):

    seller = User.query.filter_by(
        id=seller_id,
        role="seller"
    ).first_or_404()

    seller_profile = SellerProfile.query.filter_by(
        user_id=seller.id
    ).first()

    # =====================================================
    # DAFTAR KATEGORI UNTUK FILTER
    # =====================================================
    categories = Category.query.order_by(
        Category.name.asc()
    ).all()

    # =====================================================
    # PRODUK AKTIF MILIK TOKO
    # =====================================================
    products = (
        Product.query
        .filter_by(
            seller_id=seller.id,
            is_active=True
        )
        .order_by(Product.created_at.desc())
        .all()
    )

    # =====================================================
    # RATING DAN JUMLAH TERJUAL SETIAP PRODUK
    # =====================================================
    for p in products:

        # Rata-rata rating produk
        avg_rating = (
            db.session.query(
                db.func.avg(Rating.product_rating)
            )
            .filter(
                Rating.product_id == p.id,
                Rating.product_rating.isnot(None)
            )
            .scalar()
        )

        p.product_rating = float(avg_rating or 0)

        # Jumlah unit terjual dari pesanan selesai
        sold_count = (
            db.session.query(
                db.func.coalesce(
                    db.func.sum(OrderItem.qty),
                    0
                )
            )
            .join(
                Order,
                Order.id == OrderItem.order_id
            )
            .filter(
                OrderItem.product_id == p.id,
                OrderItem.seller_id == seller.id,
                Order.order_status == "Selesai"
            )
            .scalar()
        )

        p.sold_count = int(sold_count or 0)

    # =====================================================
    # RATING TOKO
    # =====================================================
    seller_rating = (
        db.session.query(
            db.func.avg(Rating.seller_rating)
        )
        .filter(
            Rating.seller_id == seller.id,
            Rating.seller_rating.isnot(None)
        )
        .scalar()
    )

    seller_rating = float(seller_rating or 0)

    # Jumlah penilaian toko yang memiliki rating
    seller_rating_count = (
        Rating.query
        .filter(
            Rating.seller_id == seller.id,
            Rating.seller_rating.isnot(None)
        )
        .count()
    )

    # =====================================================
    # ULASAN TOKO
    # =====================================================
    seller_reviews = (
        db.session.query(
            Rating,
            User
        )
        .join(
            User,
            User.id == Rating.buyer_id
        )
        .filter(
            Rating.seller_id == seller.id,
            Rating.seller_rating.isnot(None)
        )
        .order_by(
            Rating.created_at.desc()
        )
        .all()
    )

    # =====================================================
    # TAMPILKAN HALAMAN TOKO
    # =====================================================
    return render_template(
        "buyer/store_detail.html",
        seller=seller,
        seller_profile=seller_profile,
        products=products,
        categories=categories,
        seller_rating=seller_rating,
        seller_rating_count=seller_rating_count,
        seller_reviews=seller_reviews
    )
    



# =====================================================
# Buyer profile route
# =====================================================

@app.route("/buyer/profile", methods=["GET", "POST"])
@login_required
def buyer_profile():
    # Pastikan halaman ini hanya dapat diakses buyer.
    if current_user.role != "buyer":
        flash("Halaman ini hanya dapat diakses oleh pembeli.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()

        # Validasi input.
        if not name or not email or not phone:
            flash("Semua kolom wajib diisi.", "error")

        else:
            # Periksa apakah email digunakan akun lain.
            existing_email = User.query.filter(
                User.email == email,
                User.id != current_user.id
            ).first()

            if existing_email:
                flash("Email sudah digunakan akun lain.", "error")

            else:
                # Periksa apakah nomor WhatsApp digunakan akun lain.
                existing_phone = User.query.filter(
                    User.phone == phone,
                    User.id != current_user.id
                ).first()

                if existing_phone:
                    flash(
                        "Nomor WhatsApp sudah digunakan akun lain.",
                        "error"
                    )

                else:
                    try:
                        current_user.name = name
                        current_user.email = email
                        current_user.phone = phone

                        db.session.commit()

                        flash(
                            "Profil berhasil diperbarui.",
                            "success"
                        )
                        return redirect(url_for("buyer_profile"))

                    except Exception:
                        db.session.rollback()
                        flash(
                            "Profil gagal diperbarui. Silakan coba lagi.",
                            "error"
                        )

    # Ambil alamat milik pembeli yang sedang login.
    addresses = BuyerAddress.query.filter_by(
        buyer_id=current_user.id
    ).order_by(
        BuyerAddress.is_primary.desc(),
        BuyerAddress.created_at.desc()
    ).all()

    # Ambil pesanan milik pembeli yang sedang login.
    buyer_orders = Order.query.filter_by(
        buyer_id=current_user.id
    ).all()

    # Hitung total pesanan.
    total_orders = len(buyer_orders)

    # Hitung pesanan yang menunggu pembayaran.
    pending_orders = sum(
        1 for order in buyer_orders
        if order.order_status == "Menunggu Pembayaran"
    )

    # Hitung pesanan yang sedang diproses.
    processing_orders = sum(
        1 for order in buyer_orders
        if order.order_status in [
            "Diproses",
            "Siap Diambil",
            "Dalam Pengantaran"
        ]
    )

    # Hitung pesanan yang selesai.
    completed_orders = sum(
        1 for order in buyer_orders
        if order.order_status == "Selesai"
    )

    # Data ulasan akan diisi dari model rating yang digunakan
    # pada database aplikasi Anda.
    # Ambil ulasan yang pernah diberikan pembeli.
    reviews = (
        db.session.query(Rating, Product)
        .join(Product, Product.id == Rating.product_id)
        .filter(Rating.buyer_id == current_user.id)
        .order_by(Rating.created_at.desc())
        .all()
    )

    return render_template(
        "buyer/profile.html",
        user=current_user,
        addresses=addresses,
        total_orders=total_orders,
        pending_orders=pending_orders,
        processing_orders=processing_orders,
        completed_orders=completed_orders,
        reviews=reviews
    )
    
    

@app.route("/buyer/profile/photo", methods=["POST"])
@login_required
def update_buyer_photo():
    if current_user.role != "buyer":
        flash("Halaman ini hanya dapat diakses oleh pembeli.", "error")
        return redirect(url_for("buyer_profile"))

    file = request.files.get("profile_photo")

    if not file or not file.filename:
        flash("Silakan pilih foto terlebih dahulu.", "error")
        return redirect(url_for("buyer_profile"))

    allowed_extensions = {"jpg", "jpeg", "png", "webp"}
    original_name = secure_filename(file.filename)

    if "." not in original_name:
        flash("Format foto tidak valid.", "error")
        return redirect(url_for("buyer_profile"))

    extension = original_name.rsplit(".", 1)[1].lower()

    if extension not in allowed_extensions:
        flash("Format foto harus JPG, PNG, atau WEBP.", "error")
        return redirect(url_for("buyer_profile"))

    file.stream.seek(0, os.SEEK_END)
    file_size = file.stream.tell()
    file.stream.seek(0)

    if file_size == 0 or file_size > 2 * 1024 * 1024:
        flash("Ukuran foto harus lebih dari 0 dan maksimal 2 MB.", "error")
        return redirect(url_for("buyer_profile"))

    upload_folder = os.path.join(
        app.root_path, "static", "uploads", "profile_photos"
    )
    os.makedirs(upload_folder, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.{extension}"
    filepath = os.path.join(upload_folder, filename)

    try:
        file.save(filepath)

        old_photo = getattr(current_user, "profile_photo", None)

        current_user.profile_photo = filename
        db.session.commit()

        # Hapus foto lama setelah penyimpanan berhasil.
        if old_photo:
            old_path = os.path.abspath(
                os.path.join(upload_folder, old_photo)
            )

            if (
                os.path.dirname(old_path) == os.path.abspath(upload_folder)
                and os.path.isfile(old_path)
            ):
                os.remove(old_path)

        flash("Foto profil berhasil diperbarui.", "success")

    except Exception:
        db.session.rollback()

        if os.path.isfile(filepath):
            os.remove(filepath)

        app.logger.exception("Gagal memperbarui foto profil.")
        flash("Foto profil gagal diperbarui.", "error")

    return redirect(url_for("buyer_profile"))



@app.route("/buyer/addresses/<int:address_id>/edit", methods=["POST"])
@login_required
def edit_buyer_address(address_id):
    if current_user.role != "buyer":
        flash("Halaman ini hanya dapat diakses oleh pembeli.", "error")
        return redirect(url_for("login"))

    address = BuyerAddress.query.filter_by(
        id=address_id,
        buyer_id=current_user.id
    ).first_or_404()

    label = request.form.get("label", "").strip()
    recipient_name = request.form.get("recipient_name", "").strip()
    recipient_phone = request.form.get("recipient_phone", "").strip()
    full_address = request.form.get("full_address", "").strip()
    address_note = request.form.get("address_note", "").strip()
    latitude = request.form.get("latitude", "").strip()
    longitude = request.form.get("longitude", "").strip()
    is_primary = request.form.get("is_primary") == "1"

    if not all([
        label, recipient_name, recipient_phone,
        full_address, latitude, longitude
    ]):
        flash("Semua data alamat wajib diisi.", "error")
        return redirect(url_for("buyer_profile"))

    try:
        latitude = float(latitude)
        longitude = float(longitude)

        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError

    except (ValueError, TypeError):
        flash("Koordinat lokasi tidak valid.", "error")
        return redirect(url_for("buyer_profile"))

    try:
        if is_primary:
            BuyerAddress.query.filter_by(
                buyer_id=current_user.id
            ).update({"is_primary": False})

        address.label = label
        address.recipient_name = recipient_name
        address.recipient_phone = recipient_phone
        address.full_address = full_address
        address.address_note = address_note or None
        address.latitude = latitude
        address.longitude = longitude

        if is_primary:
            address.is_primary = True

        db.session.commit()
        flash("Alamat berhasil diperbarui.", "success")

    except Exception:
        db.session.rollback()
        app.logger.exception("Gagal memperbarui alamat.")
        flash("Alamat gagal diperbarui.", "error")

    return redirect(url_for("buyer_profile"))


@app.route("/buyer/addresses/<int:address_id>/delete", methods=["POST"])
@login_required
def delete_buyer_address(address_id):
    if current_user.role != "buyer":
        flash("Halaman ini hanya dapat diakses oleh pembeli.", "error")
        return redirect(url_for("login"))

    address = BuyerAddress.query.filter_by(
        id=address_id,
        buyer_id=current_user.id
    ).first_or_404()

    try:
        was_primary = address.is_primary

        db.session.delete(address)
        db.session.flush()

        # Jika alamat utama dihapus, pilih alamat lain sebagai utama.
        if was_primary:
            next_address = BuyerAddress.query.filter_by(
                buyer_id=current_user.id
            ).order_by(
                BuyerAddress.created_at.desc()
            ).first()

            if next_address:
                next_address.is_primary = True

        db.session.commit()
        flash("Alamat berhasil dihapus.", "success")

    except Exception:
        db.session.rollback()
        app.logger.exception("Gagal menghapus alamat pembeli.")
        flash("Alamat gagal dihapus. Silakan coba kembali.", "error")

    return redirect(url_for("buyer_profile"))



@app.route("/buyer/addresses/<int:address_id>/primary", methods=["POST"])
@login_required
def set_primary_address(address_id):
    if current_user.role != "buyer":
        flash("Halaman ini hanya dapat diakses oleh pembeli.", "error")
        return redirect(url_for("login"))

    address = BuyerAddress.query.filter_by(
        id=address_id,
        buyer_id=current_user.id
    ).first_or_404()

    try:
        # Hapus status alamat utama dari semua alamat pembeli ini.
        BuyerAddress.query.filter_by(
            buyer_id=current_user.id
        ).update({"is_primary": False})

        # Tetapkan alamat yang dipilih sebagai alamat utama.
        address.is_primary = True

        db.session.commit()
        flash("Alamat utama berhasil diperbarui.", "success")

    except Exception:
        db.session.rollback()
        app.logger.exception("Gagal menetapkan alamat utama.")
        flash("Gagal menetapkan alamat utama.", "error")

    return redirect(url_for("buyer_profile"))


@app.route("/buyer/addresses/add", methods=["POST"])
@login_required
def add_buyer_address():
    if current_user.role != "buyer":
        flash("Halaman ini hanya dapat diakses oleh pembeli.", "error")
        return redirect(url_for("login"))

    label = request.form.get("label", "").strip()
    recipient_name = request.form.get("recipient_name", "").strip()
    recipient_phone = request.form.get("recipient_phone", "").strip()
    full_address = request.form.get("full_address", "").strip()
    address_note = request.form.get("address_note", "").strip()
    latitude = request.form.get("latitude", "").strip()
    longitude = request.form.get("longitude", "").strip()
    is_primary = request.form.get("is_primary") == "1"

    if not all([
        label, recipient_name, recipient_phone,
        full_address, latitude, longitude
    ]):
        flash("Semua data alamat wajib diisi.", "error")
        return redirect(url_for("buyer_profile"))

    try:
        latitude = float(latitude)
        longitude = float(longitude)

        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError

    except (ValueError, TypeError):
        flash("Koordinat lokasi tidak valid.", "error")
        return redirect(url_for("buyer_profile"))

    try:
        existing_address = BuyerAddress.query.filter_by(
            buyer_id=current_user.id
        ).first()

        if is_primary or existing_address is None:
            BuyerAddress.query.filter_by(
                buyer_id=current_user.id
            ).update({"is_primary": False})

            is_primary = True

        address = BuyerAddress(
            buyer_id=current_user.id,
            label=label,
            recipient_name=recipient_name,
            recipient_phone=recipient_phone,
            full_address=full_address,
            address_note=address_note or None,
            latitude=latitude,
            longitude=longitude,
            is_primary=is_primary
        )

        db.session.add(address)
        db.session.commit()

        flash("Alamat pengiriman berhasil ditambahkan.", "success")

    except Exception:
        db.session.rollback()
        app.logger.exception("Gagal menyimpan alamat pembeli.")
        flash("Alamat gagal disimpan. Silakan coba kembali.", "error")

    return redirect(url_for("buyer_profile"))


@app.route("/admin")
@login_required
@roles("admin")
def admin_dashboard():
    return render_template(
        "admin/dashboard.html",
        users=User.query.count(),
        sellers=User.query.filter_by(role="seller").count(),
        buyers=User.query.filter_by(role="buyer").count(),
        orders=Order.query.count(),
        revenue=db.session.query(db.func.sum(Order.total))
        .filter(Order.payment_status == "paid")
        .scalar()
        or 0,
        pending=SellerProfile.query.filter_by(verification_status="pending").count(),
        withdrawals=Withdrawal.query.filter_by(status="pending").count(),
    )


@app.route("/admin/sellers")
@login_required
@roles("admin")
def admin_sellers():
    return render_template(
        "admin/sellers.html",
        sellers=User.query.filter_by(role="seller")
        .order_by(User.created_at.desc())
        .all(),
    )


@app.route("/admin/sellers/<int:uid>", methods=["GET", "POST"])
@login_required
@roles("admin")
def admin_seller_detail(uid):
    u = User.query.filter_by(id=uid, role="seller").first_or_404()
    p = u.seller_profile
    if request.method == "POST":
        p.verification_status = request.form["status"]
        p.rejection_reason = request.form.get("reason")
        p.verified_at = datetime.utcnow()
        p.verified_by = current_user.id
        db.session.commit()
        notify(
            u.id,
            "Status verifikasi pedagang",
            f"Verifikasi akun Anda: {p.verification_status}.",
            "verification",
        )
        db.session.commit()
        flash("Status pedagang diperbarui.", "success")
        return redirect(url_for("admin_sellers"))
    return render_template("admin/seller_detail.html", seller=u, profile=p)


@app.route("/admin/ktp/<int:uid>")
@login_required
@roles("admin")
def admin_ktp(uid):
    u = User.query.get_or_404(uid)
    p = u.seller_profile or abort(404)
    return send_file(os.path.join(KTP, p.ktp_file), download_name=p.ktp_file)


@app.route("/admin/withdrawals", methods=["GET", "POST"])
@login_required
@roles("admin")
def admin_withdrawals():
    if request.method == "POST":
        w = Withdrawal.query.get_or_404(int(request.form["id"]))
        status = request.form["status"]

        w.status = status
        w.processed_at = datetime.utcnow()
        w.processed_by = current_user.id

        if status == "rejected":
            w.seller.balance.available_balance += w.amount

        elif status == "paid":
            w.seller.balance.total_withdrawn += w.amount

        # Tentukan pesan notifikasi sesuai status penarikan
        if status == "approved":
            title = "Penarikan Dana Disetujui"
            message = (
                f"Pengajuan penarikan dana sebesar {rupiah(w.amount)} "
                "telah disetujui admin dan menunggu pembayaran."
            )

        elif status == "paid":
            title = "Penarikan Dana Berhasil Dibayar"
            message = (
                f"Penarikan dana sebesar {rupiah(w.amount)} "
                "telah ditandai sudah dibayar oleh admin."
            )

        elif status == "rejected":
            title = "Penarikan Dana Ditolak"
            message = (
                f"Pengajuan penarikan dana sebesar {rupiah(w.amount)} "
                "ditolak admin. Saldo Anda telah dikembalikan."
            )

        else:
            flash("Status penarikan tidak valid.", "error")
            return redirect(url_for("admin_withdrawals"))

        # Simpan perubahan status dan saldo
        db.session.flush()

        # Kirim notifikasi kepada pedagang terkait
        notify(
            w.seller_id,
            title,
            message,
            "withdrawal",
            w.id,
        )

        db.session.commit()

        flash("Penarikan diperbarui.", "success")

    return render_template(
        "admin/withdrawals.html",
        withdrawals=Withdrawal.query.order_by(
            Withdrawal.requested_at.desc()
        ).all(),
    )


@app.route("/admin/reports")
@login_required
@roles("admin")
def admin_reports():

    # =========================================================
    # AMBIL FILTER DARI URL
    # =========================================================

    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()
    status = request.args.get("status", "").strip()
    search = request.args.get("search", "").strip()
    delivery_method = request.args.get("delivery_method", "").strip()


    # =========================================================
    # QUERY DASAR
    # =========================================================

    query = Order.query


    # =========================================================
    # FILTER TANGGAL MULAI
    # =========================================================

    if start:
        try:
            start_date = datetime.strptime(
                start,
                "%Y-%m-%d"
            )

            query = query.filter(
                Order.created_at >= start_date
            )

        except ValueError:
            start = ""


    # =========================================================
    # FILTER TANGGAL AKHIR
    # =========================================================

    if end:
        try:
            end_date = datetime.strptime(
                end,
                "%Y-%m-%d"
            ) + timedelta(days=1)

            query = query.filter(
                Order.created_at < end_date
            )

        except ValueError:
            end = ""


    # =========================================================
    # FILTER STATUS
    # =========================================================

    if status:
        query = query.filter(
            Order.order_status == status
        )


    # =========================================================
    # FILTER METODE PENGAMBILAN
    # =========================================================

    if delivery_method:
        query = query.filter(
            Order.delivery_method == delivery_method
        )


    # =========================================================
    # PENCARIAN
    # =========================================================

    if search:

        search_pattern = f"%{search}%"

        query = query.outerjoin(
            User,
            Order.buyer_id == User.id
        ).filter(
            db.or_(
                Order.order_number.ilike(search_pattern),
                User.name.ilike(search_pattern),
                User.email.ilike(search_pattern)
            )
        )


    # =========================================================
    # AMBIL DATA SESUAI FILTER
    # =========================================================

    orders = (
        query
        .order_by(Order.created_at.desc())
        .all()
    )


    # =========================================================
    # RINGKASAN LAPORAN
    # =========================================================

    total_transactions = len(orders)


    total_revenue = sum(
        (o.total or 0)
        for o in orders
        if o.order_status == "Selesai"
    )


    completed_count = sum(
        1
        for o in orders
        if o.order_status == "Selesai"
    )


    cancelled_count = sum(
        1
        for o in orders
        if o.order_status == "Dibatalkan"
    )


    active_statuses = [
        "Diproses",
        "Siap Diambil",
        "Dalam Pengantaran"
    ]


    active_count = sum(
        1
        for o in orders
        if o.order_status in active_statuses
    )


    waiting_payment_count = sum(
        1
        for o in orders
        if o.order_status == "Menunggu Pembayaran"
    )


    pickup_count = sum(
        1
        for o in orders
        if o.delivery_method == "pickup"
    )


    delivery_count = sum(
        1
        for o in orders
        if o.delivery_method == "delivery"
    )


    # =========================================================
    # TOTAL NILAI SEMUA PESANAN
    # =========================================================

    total_order_value = sum(
        (o.total or 0)
        for o in orders
    )


    # =========================================================
    # KIRIM KE TEMPLATE
    # =========================================================

    return render_template(
        "admin/reports.html",

        orders=orders,

        # Filter
        start=start,
        end=end,
        status=status,
        search=search,
        delivery_method=delivery_method,

        # Ringkasan
        total_transactions=total_transactions,
        total_revenue=total_revenue,
        total_order_value=total_order_value,
        completed_count=completed_count,
        cancelled_count=cancelled_count,
        active_count=active_count,
        waiting_payment_count=waiting_payment_count,
        pickup_count=pickup_count,
        delivery_count=delivery_count
    )




@app.route("/notifications")
@login_required
def notifications():
    ns = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template("buyer/orders.html", notifications=ns, orders=[])


@app.post("/notifications/read")
@login_required
def notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update(
        {"is_read": True}
    )
    db.session.commit()
    return jsonify(ok=True)


@app.get("/notifications/preview")
@login_required
def notifications_preview():
    # Ambil 10 notifikasi terbaru milik pengguna yang sedang login.
    ns = (
        Notification.query
        .filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(10)
        .all()
    )

    # Hitung jumlah notifikasi yang belum dibaca.
    unread_count = Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).count()

    return jsonify({
        "unread_count": unread_count,
        "notifications": [
            {
                "id": n.id,
                "title": n.title or "Notifikasi",
                "message": n.message or "",
                "is_read": bool(n.is_read),
                "created_at": (
                    n.created_at.strftime("%d-%m-%Y %H:%M")
                    if n.created_at else ""
                ),
                "url": url_for("notifications")
            }
            for n in ns
        ]
    })




@app.get("/notifications/stream")
@login_required
def notifications_stream():
    # Simpan ID pengguna sebelum generator berjalan.
    user_id = current_user.id

    @stream_with_context
    def event_stream():
        import json

        last_notification_id = None
        last_unread_count = None
        last_heartbeat = time.monotonic()

        # Identitas koneksi SSE.
        yield "retry: 3000\n\n"

        while True:
            try:
                # Ambil ID notifikasi terbaru milik pengguna.
                latest_id = (
                    db.session.query(db.func.max(Notification.id))
                    .filter(Notification.user_id == user_id)
                    .scalar()
                ) or 0

                # Hitung notifikasi yang belum dibaca.
                unread_count = Notification.query.filter_by(
                    user_id=user_id,
                    is_read=False
                ).count()

                changed = (
                    last_notification_id is None
                    or latest_id != last_notification_id
                    or unread_count != last_unread_count
                )

                if changed:
                    payload = {
                        "unread_count": unread_count,
                        "latest_id": latest_id
                    }

                    yield (
                        "event: notifications\n"
                        f"data: {json.dumps(payload)}\n\n"
                    )

                    last_notification_id = latest_id
                    last_unread_count = unread_count
                    last_heartbeat = time.monotonic()

                elif time.monotonic() - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()

            except GeneratorExit:
                raise

            except Exception:
                current_app.logger.exception(
                    "Terjadi kesalahan pada SSE notifikasi."
                )

                # Jangan biarkan sesi database yang gagal
                # mengganggu pemeriksaan berikutnya.
                db.session.rollback()

            finally:
                db.session.remove()

            time.sleep(3)

    response = Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )

    return response



@app.cli.command("init-db")
def init_db():
    db.create_all()
    if not User.query.filter_by(role="admin").first():
        u = User(
            name="Administrator",
            email="admin@pasarremboken.local",
            role="admin",
            is_verified=True,
        )
        u.set_password("admin12345")
        db.session.add(u)
    for n, s in [
        ("Sembako", "sembako"),
        ("Makanan", "makanan"),
        ("Minuman", "minuman"),
        ("Kerajinan", "kerajinan"),
        ("Pertanian", "pertanian"),
    ]:
        if not Category.query.filter_by(slug=s).first():
            db.session.add(Category(name=n, slug=s))
    db.session.commit()
    print("Database siap. Admin: admin@pasarremboken.local / admin12345")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
