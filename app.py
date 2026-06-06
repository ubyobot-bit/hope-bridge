import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, inspect, text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-development-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///hopebridge.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER", str(Path(app.root_path) / "static" / "uploads"))
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config["SQLALCHEMY_DATABASE_URI"].replace("postgres://", "postgresql://", 1)

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(40), unique=True, nullable=True)
    city = db.Column(db.String(80), nullable=True)
    country = db.Column(db.String(80), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    auth_provider = db.Column(db.String(30), nullable=False, default="email")
    password_hash = db.Column(db.String(255), nullable=True)
    reset_token = db.Column(db.String(120), unique=True, nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    campaigns = db.relationship("Campaign", backref="owner", lazy=True)
    donations = db.relationship("Donation", backref="donor", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


class SocialAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(30), nullable=False)
    provider_subject = db.Column(db.String(180), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref="social_accounts")
    __table_args__ = (db.UniqueConstraint("provider", "provider_subject", name="uq_provider_subject"),)


class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    patient = db.Column(db.String(120), nullable=False)
    organizer = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(160), nullable=False)
    goal = db.Column(db.Integer, nullable=False)
    image = db.Column(db.String(500), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    story = db.Column(db.Text, nullable=False)
    verified = db.Column(db.Boolean, default=False)
    completed = db.Column(db.Boolean, default=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    donations = db.relationship("Donation", backref="campaign", lazy=True)

    @property
    def raised(self):
        total = sum(donation.amount for donation in self.donations if donation.status in ("pending", "confirmed"))
        return int(total or 0)

    @property
    def progress(self):
        if not self.goal:
            return 0
        return min(100, int((self.raised / self.goal) * 100))

    @property
    def name(self):
        return self.title


class Donation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaign.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(30), nullable=False)
    payment_asset = db.Column(db.String(30), nullable=True)
    payment_network = db.Column(db.String(40), nullable=True)
    payment_address = db.Column(db.String(255), nullable=True)
    giftcard_type = db.Column(db.String(80), nullable=True)
    giftcard_code = db.Column(db.String(180), nullable=True)
    proof_filename = db.Column(db.String(255), nullable=True)
    bank_name = db.Column(db.String(120), nullable=True)
    bank_account_name = db.Column(db.String(120), nullable=True)
    bank_account_number = db.Column(db.String(80), nullable=True)
    reference = db.Column(db.String(80), unique=True, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


CRYPTO_ADDRESS_BOOK = {
    "BTC": {"BTC": ["bc1qhopebtc01sample", "bc1qhopebtc02sample", "bc1qhopebtc03sample"]},
    "ETH": {"ERC20": ["0xHopeEthAddress01", "0xHopeEthAddress02", "0xHopeEthAddress03"]},
    "USDC": {
        "ERC20": ["0xHopeUsdcErc01", "0xHopeUsdcErc02", "0xHopeUsdcErc03"],
        "BEP20": ["0xHopeUsdcBep01", "0xHopeUsdcBep02", "0xHopeUsdcBep03"],
        "TRC20": ["THopeUsdcTrc01", "THopeUsdcTrc02", "THopeUsdcTrc03"],
        "POLYGON": ["0xHopeUsdcPoly01", "0xHopeUsdcPoly02", "0xHopeUsdcPoly03"],
    },
    "USDT": {
        "ERC20": ["0xHopeUsdtErc01", "0xHopeUsdtErc02", "0xHopeUsdtErc03"],
        "BEP20": ["0xHopeUsdtBep01", "0xHopeUsdtBep02", "0xHopeUsdtBep03"],
        "TRC20": ["THopeUsdtTrc01", "THopeUsdtTrc02", "THopeUsdtTrc03"],
        "POLYGON": ["0xHopeUsdtPoly01", "0xHopeUsdtPoly02", "0xHopeUsdtPoly03"],
    },
}

GIFT_CARD_TYPES = ["Amazon Gift Card", "Apple Gift Card", "Steam Gift Card"]
BANK_ACCOUNT = {
    "bank_name": "HopeBridge Standard Bank",
    "account_name": "HopeBridge Donations",
    "account_number": "0123456789",
}

SEED_CAMPAIGNS = [
    {
        "title": "Help Sarah Fight Breast Cancer",
        "category": "Breast Cancer",
        "patient": "Sarah",
        "organizer": "Sarah's Family",
        "location": "New York, USA",
        "goal": 5000,
        "image": "https://images.unsplash.com/photo-1544717305-2782549b5136?auto=format&fit=crop&w=900&q=80",
        "summary": "Sarah needs support for her chemotherapy treatment and recovery care.",
        "story": "Sarah is a bright 12-year-old girl diagnosed with stage 2 breast cancer. Her family needs help to continue chemotherapy and surgery.",
        "verified": True,
    },
    {
        "title": "Support David's Treatment",
        "category": "Lung Cancer",
        "patient": "David",
        "organizer": "Hope Friends",
        "location": "Chicago, USA",
        "goal": 10000,
        "image": "https://images.unsplash.com/photo-1582750433449-648ed127bb54?auto=format&fit=crop&w=900&q=80",
        "summary": "David is battling lung cancer and needs urgent surgery.",
        "story": "David needs support for surgery, medicine, scans, and recovery care.",
        "verified": True,
    },
    {
        "title": "Help Maria's Recovery",
        "category": "Ovarian Cancer",
        "patient": "Maria",
        "organizer": "Maria's Sister",
        "location": "Austin, USA",
        "goal": 4500,
        "image": "https://images.unsplash.com/photo-1550831107-1553da8c8464?auto=format&fit=crop&w=900&q=80",
        "summary": "Maria needs help for ovarian cancer treatment and recovery support.",
        "story": "Maria needs help with medication, transport, and specialist visits.",
        "verified": True,
    },
]

COMPLETED_PROJECTS = [
    {
        "title": "Children's Oncology Ward",
        "amount": "$42,000",
        "summary": "Treatment beds, monitors, and nutrition support delivered.",
        "image": "https://images.unsplash.com/photo-1586773860418-d37222d8fce3?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Sarah's Surgery Fund",
        "amount": "$18,500",
        "summary": "Surgery and post-care support fully covered.",
        "image": "https://images.unsplash.com/photo-1579684385127-1ef15d508118?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Mobile Screening Drive",
        "amount": "$27,300",
        "summary": "Free cancer screening reached 900+ residents.",
        "image": "https://images.unsplash.com/photo-1584515933487-779824d29309?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Recovery Transport Aid",
        "amount": "$9,800",
        "summary": "Hospital transport covered for 64 families.",
        "image": "https://images.unsplash.com/photo-1538108149393-fbbd81895907?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Medication Relief Pool",
        "amount": "$31,200",
        "summary": "Critical medicine support completed for verified patients.",
        "image": "https://images.unsplash.com/photo-1587854692152-cbe660dbde88?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Family Care Grants",
        "amount": "$15,700",
        "summary": "Living expense grants delivered to caregivers.",
        "image": "https://images.unsplash.com/photo-1511895426328-dc8714191300?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Rural Chemotherapy Access",
        "amount": "$36,900",
        "summary": "Partner clinics received support for low-cost chemotherapy sessions.",
        "image": "https://images.unsplash.com/photo-1576091160550-2173dba999ef?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Nutrition Packs For Patients",
        "amount": "$12,400",
        "summary": "High-protein nutrition packs delivered during treatment cycles.",
        "image": "https://images.unsplash.com/photo-1498837167922-ddd27525d352?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Diagnostics Subsidy Fund",
        "amount": "$22,600",
        "summary": "MRI, CT scan, and biopsy costs subsidized for verified patients.",
        "image": "https://images.unsplash.com/photo-1516549655169-df83a0774514?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Caregiver Housing Support",
        "amount": "$17,950",
        "summary": "Temporary housing provided for families traveling for specialist care.",
        "image": "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Childhood Cancer Education",
        "amount": "$8,750",
        "summary": "Awareness materials and early-warning education delivered to schools.",
        "image": "https://images.unsplash.com/photo-1497633762265-9d179a990aa6?auto=format&fit=crop&w=900&q=80",
    },
    {
        "title": "Emergency Treatment Bridge",
        "amount": "$29,100",
        "summary": "Urgent treatment deposits paid while families completed documentation.",
        "image": "https://images.unsplash.com/photo-1504439468489-c8920d796a29?auto=format&fit=crop&w=900&q=80",
    },
]

TESTIMONIALS = [
    {
        "name": "Amina Yusuf",
        "quote": "HopeBridge made it possible for my sister to continue treatment without delay.",
        "image": "https://images.unsplash.com/photo-1531123897727-8f129e1688ce?auto=format&fit=crop&w=600&q=80",
    },
    {
        "name": "Daniel Reed",
        "quote": "I could see where my donation went, and the updates made everything feel transparent.",
        "image": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=600&q=80",
    },
    {
        "name": "Maria Lopez",
        "quote": "The support helped my family breathe again during a very difficult season.",
        "image": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&w=600&q=80",
    },
]

PARTNERS = [
    {"name": "WHO", "logo": "WHO", "caption": "Global health guidance"},
    {"name": "USAID", "logo": "USAID", "caption": "Humanitarian development"},
    {"name": "UNICEF", "logo": "UNICEF", "caption": "Children and families"},
    {"name": "Doctors Without Borders", "logo": "MSF", "caption": "Emergency medical aid"},
    {"name": "International Medical Corps", "logo": "IMC", "caption": "Clinical response"},
    {"name": "GlobalGiving", "logo": "GG", "caption": "Trusted donor network"},
    {"name": "Red Cross", "logo": "RC", "caption": "Relief coordination"},
    {"name": "Clinton Health Access Initiative", "logo": "CHAI", "caption": "Health access programs"},
]

EXECUTIVES = [
    {
        "name": "Dr. Amara Okonkwo",
        "role": "Chief Executive Officer",
        "bio": "Public-health strategist focused on transparent patient funding and hospital partnership systems.",
        "image": "https://images.unsplash.com/photo-1559839734-2b71ea197ec2?auto=format&fit=crop&w=600&q=80",
    },
    {
        "name": "Michael Adeyemi",
        "role": "Chief Operations Officer",
        "bio": "Leads verification, campaign review, payment operations, and donor support workflows.",
        "image": "https://images.unsplash.com/photo-1560250097-0b93528c311a?auto=format&fit=crop&w=600&q=80",
    },
    {
        "name": "Nadia Williams",
        "role": "Director of Partnerships",
        "bio": "Builds collaborations with clinics, NGOs, care networks, and humanitarian organizations.",
        "image": "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?auto=format&fit=crop&w=600&q=80",
    },
    {
        "name": "Samuel Hart",
        "role": "Head of Trust & Safety",
        "bio": "Owns campaign due diligence, fraud prevention, donor documentation, and reporting standards.",
        "image": "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?auto=format&fit=crop&w=600&q=80",
    },
]

ABOUT_VALUES = [
    ("Verified Need", "Every campaign is reviewed for patient details, organizer information, and treatment relevance."),
    ("Transparent Giving", "Donation records, payment references, and campaign updates are designed to be traceable."),
    ("Patient Dignity", "We tell human stories with care, consent, and respect for families under pressure."),
    ("Fast Support", "Our payment options and partner workflows help urgent care move without unnecessary delay."),
]

PROJECT_IMAGE_POOL = [
    "https://images.unsplash.com/photo-1586773860418-d37222d8fce3?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1579684385127-1ef15d508118?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1584515933487-779824d29309?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1538108149393-fbbd81895907?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1587854692152-cbe660dbde88?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1511895426328-dc8714191300?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1576091160550-2173dba999ef?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1498837167922-ddd27525d352?auto=format&fit=crop&w=900&q=80",
]

PROJECT_THEMES = [
    "Radiology Access Fund", "Emergency Surgery Bridge", "Patient Nutrition Support", "Rural Screening Outreach",
    "Caregiver Housing Relief", "Medication Relief Pool", "Children's Treatment Fund", "Transport To Treatment",
    "Chemotherapy Subsidy Drive", "Diagnostic Test Sponsorship", "Family Care Grant", "Post-Surgery Recovery Aid",
]

TESTIMONIAL_NAMES = [
    "Amina Yusuf", "Daniel Reed", "Maria Lopez", "Chinedu Okafor", "Grace Miller", "Fatima Bello",
    "Samuel Carter", "Nora Williams", "Ibrahim Musa", "Elena Rossi", "Victor Chen", "Maya Johnson",
]

TESTIMONIAL_IMAGES = [
    "https://images.unsplash.com/photo-1531123897727-8f129e1688ce?auto=format&fit=crop&w=600&q=80",
    "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=600&q=80",
    "https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&w=600&q=80",
    "https://images.unsplash.com/photo-1508214751196-bcfd4ca60f91?auto=format&fit=crop&w=600&q=80",
    "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=600&q=80",
    "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=600&q=80",
]

while len(COMPLETED_PROJECTS) < 60:
    index = len(COMPLETED_PROJECTS)
    COMPLETED_PROJECTS.append(
        {
            "title": f"{PROJECT_THEMES[index % len(PROJECT_THEMES)]} {index + 1}",
            "amount": f"${(8400 + index * 1350):,}",
            "summary": "A verified medical support project completed with transparent donor funding and partner oversight.",
            "image": PROJECT_IMAGE_POOL[index % len(PROJECT_IMAGE_POOL)],
        }
    )

while len(TESTIMONIALS) < 60:
    index = len(TESTIMONIALS)
    TESTIMONIALS.append(
        {
            "name": TESTIMONIAL_NAMES[index % len(TESTIMONIAL_NAMES)],
            "quote": "HopeBridge made giving feel personal, secure, and meaningful. The updates helped me trust the impact.",
            "image": TESTIMONIAL_IMAGES[index % len(TESTIMONIAL_IMAGES)],
        }
    )


def format_money(value):
    return "${:,.0f}".format(value or 0)


app.jinja_env.filters["money"] = format_money


def normalize_email(email):
    return (email or "").strip().lower()


def clean_phone(phone):
    return (phone or "").strip() or None


def generate_reference(prefix="HB"):
    return f"{prefix}-{secrets.token_hex(5).upper()}"


def external_url_for(endpoint, **values):
    return url_for(endpoint, _external=True, **values)


def get_campaigns():
    return Campaign.query.order_by(Campaign.created_at.asc()).all()


def select_crypto_address(asset, network):
    addresses = CRYPTO_ADDRESS_BOOK.get(asset, {}).get(network, [])
    if not addresses:
        return None
    count = Donation.query.filter_by(payment_method="crypto", payment_asset=asset, payment_network=network).count()
    return addresses[count % len(addresses)]


def crypto_qr_url(donation):
    if donation.payment_method != "crypto" or not donation.payment_address:
        return None
    payload = f"{donation.payment_asset}:{donation.payment_address}?network={donation.payment_network}&amount={donation.amount}"
    return f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={quote_plus(payload)}"


def save_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    filename = secure_filename(file_storage.filename)
    unique_name = f"{secrets.token_hex(6)}-{filename}"
    file_storage.save(Path(app.config["UPLOAD_FOLDER"]) / unique_name)
    return unique_name


def create_reset_link(user):
    user.reset_token = secrets.token_urlsafe(32)
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
    db.session.commit()
    return external_url_for("reset_password", token=user.reset_token)


def social_login(provider, email, full_name):
    email = normalize_email(email)
    if not email:
        flash("A verified email is required for social sign in.", "danger")
        return redirect(url_for("login"))

    user = User.query.filter_by(email=email).first()
    if user is None:
        user = User(full_name=full_name or email.split("@")[0], email=email, auth_provider=provider)
        db.session.add(user)
        db.session.flush()
    elif user.auth_provider not in (provider, "email"):
        flash("This email is already bonded to another sign-in method.", "danger")
        return redirect(url_for("login"))

    account = SocialAccount.query.filter_by(provider=provider, provider_subject=email).first()
    if account is None:
        db.session.add(SocialAccount(provider=provider, provider_subject=email, user_id=user.id))
    db.session.commit()
    login_user(user)
    flash(f"Signed in with {provider.title()}.", "success")
    return redirect(url_for("dashboard"))


def seed_campaigns():
    for data in SEED_CAMPAIGNS:
        existing = Campaign.query.filter_by(title=data["title"]).first()
        if existing is None:
            db.session.add(Campaign(**data))
    db.session.commit()


def ensure_schema():
    db.create_all()
    inspector = inspect(db.engine)
    if "user" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("user")}
    additions = {
        "phone": "VARCHAR(40)",
        "city": "VARCHAR(80)",
        "country": "VARCHAR(80)",
        "bio": "TEXT",
        "auth_provider": "VARCHAR(30) DEFAULT 'email'",
        "reset_token": "VARCHAR(120)",
        "reset_token_expires": "TIMESTAMP",
        "created_at": "TIMESTAMP",
    }
    for name, definition in additions.items():
        if name not in columns:
            db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {name} {definition}'))
    db.session.commit()


@app.route("/")
def home():
    return render_template(
        "index.html",
        campaigns=get_campaigns()[:3],
        completed_projects=COMPLETED_PROJECTS[:6],
        testimonials=TESTIMONIALS[:6],
        partners=PARTNERS,
    )


@app.route("/about")
def about():
    return render_template(
        "about.html",
        executives=EXECUTIVES,
        values=ABOUT_VALUES,
        partners=PARTNERS,
    )


@app.route("/projects")
def completed_projects():
    return render_template("projects.html", projects=COMPLETED_PROJECTS)


@app.route("/testimonials")
def testimonials():
    return render_template("testimonials.html", testimonials=TESTIMONIALS)


@app.route("/campaigns")
def campaign_list():
    return render_template("campaigns.html", campaigns=get_campaigns())


@app.route("/campaign/new", methods=["GET", "POST"])
@login_required
def create_campaign():
    if request.method == "POST":
        goal = int(request.form.get("goal", "0") or 0)
        if goal <= 0:
            flash("Please enter a valid fundraising goal.", "danger")
            return redirect(url_for("create_campaign"))
        uploaded_image = save_upload(request.files.get("campaign_image"))
        image_url = (
            url_for("static", filename=f"uploads/{uploaded_image}")
            if uploaded_image
            else "https://images.unsplash.com/photo-1550831107-1553da8c8464?auto=format&fit=crop&w=900&q=80"
        )
        campaign = Campaign(
            title=request.form.get("title", "").strip(),
            patient=request.form.get("patient", "").strip(),
            category=request.form.get("category", "Medical").strip(),
            organizer=current_user.full_name,
            location=request.form.get("location", "").strip(),
            goal=goal,
            image=image_url,
            summary=request.form.get("summary", "").strip(),
            story=request.form.get("story", "").strip(),
            owner_id=current_user.id,
            verified=False,
        )
        if not campaign.title or not campaign.patient or not campaign.summary or not campaign.story:
            flash("Please complete all required campaign fields.", "danger")
            return redirect(url_for("create_campaign"))
        db.session.add(campaign)
        db.session.commit()
        flash("Campaign created. It will appear while awaiting verification.", "success")
        return redirect(url_for("dashboard"))
    return render_template("campaign_form.html")


@app.route("/campaign/<int:campaign_id>")
def campaign_detail(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if campaign is None:
        return redirect(url_for("campaign_list"))
    donations = Donation.query.filter_by(campaign_id=campaign.id).order_by(Donation.created_at.desc()).limit(6).all()
    return render_template("campaign_detail.html", campaign=campaign, donations=donations)


@app.route("/campaign/<int:campaign_id>/donate", methods=["GET", "POST"])
def donate(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if campaign is None:
        return redirect(url_for("campaign_list"))

    if request.method == "POST":
        amount = int(request.form.get("amount", "0") or 0)
        method = request.form.get("payment_method")
        if amount <= 0 or method not in ("crypto", "giftcard", "bank"):
            flash("Choose a valid amount and payment method.", "danger")
            return redirect(url_for("donate", campaign_id=campaign.id))

        donation = Donation(
            donor_id=current_user.id if current_user.is_authenticated else None,
            campaign_id=campaign.id,
            amount=amount,
            payment_method=method,
            reference=generate_reference(),
        )

        if method == "crypto":
            asset = request.form.get("asset")
            network = request.form.get("network")
            address = select_crypto_address(asset, network)
            if address is None:
                flash("Choose a supported crypto asset and network.", "danger")
                return redirect(url_for("donate", campaign_id=campaign.id))
            donation.payment_asset = asset
            donation.payment_network = network
            donation.payment_address = address
        elif method == "giftcard":
            giftcard_type = request.form.get("giftcard_type")
            if giftcard_type not in GIFT_CARD_TYPES:
                flash("Choose a supported gift card.", "danger")
                return redirect(url_for("donate", campaign_id=campaign.id))
            donation.giftcard_type = giftcard_type
            donation.giftcard_code = request.form.get("giftcard_code", "").strip()
            donation.proof_filename = save_upload(request.files.get("giftcard_proof"))
        elif method == "bank":
            donation.bank_name = BANK_ACCOUNT["bank_name"]
            donation.bank_account_name = BANK_ACCOUNT["account_name"]
            donation.bank_account_number = BANK_ACCOUNT["account_number"]
            donation.proof_filename = save_upload(request.files.get("bank_proof"))

        db.session.add(donation)
        db.session.commit()
        return redirect(url_for("donation_receipt", reference=donation.reference))

    return render_template(
        "donate.html",
        campaign=campaign,
        crypto_book=CRYPTO_ADDRESS_BOOK,
        giftcards=GIFT_CARD_TYPES,
        bank_account=BANK_ACCOUNT,
    )


@app.route("/donation/<reference>")
def donation_receipt(reference):
    donation = Donation.query.filter_by(reference=reference).first_or_404()
    return render_template(
        "donation_receipt.html",
        donation=donation,
        qr_url=crypto_qr_url(donation),
        estimated_confirmation="about 20 minutes",
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        full_name = request.form.get("name", "").strip()
        email = normalize_email(request.form.get("email"))
        phone = clean_phone(request.form.get("phone"))
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm", "")
        if not full_name or not email or not password:
            flash("Please complete every required field.", "danger")
            return redirect(url_for("register"))
        if password != confirm_password:
            flash("Your passwords do not match.", "danger")
            return redirect(url_for("register"))
        if User.query.filter(func.lower(User.email) == email).first():
            flash("One email can only be bonded to one account.", "danger")
            return redirect(url_for("register"))
        if phone and User.query.filter_by(phone=phone).first():
            flash("This phone number is already bonded to another account.", "danger")
            return redirect(url_for("register"))
        user = User(full_name=full_name, email=email, phone=phone, auth_provider="email")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Your account has been created.", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = normalize_email(request.form.get("email"))
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.email) == email).first()
        if user is None or not user.check_password(password):
            flash("Incorrect email or password.", "danger")
            return redirect(url_for("login"))
        login_user(user, remember=request.form.get("remember") == "on")
        flash("Welcome back to HopeBridge.", "success")
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/auth/<provider>", methods=["GET", "POST"])
def oauth_login(provider):
    if provider not in ("google", "facebook"):
        return redirect(url_for("login"))
    if request.method == "POST":
        return social_login(provider, request.form.get("email"), request.form.get("name"))
    configured = bool(os.environ.get(f"{provider.upper()}_CLIENT_ID") and os.environ.get(f"{provider.upper()}_CLIENT_SECRET"))
    return render_template("oauth_demo.html", provider=provider, configured=configured)


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = normalize_email(request.form.get("email"))
        user = User.query.filter(func.lower(User.email) == email).first()
        if user:
            reset_link = create_reset_link(user)
            flash(f"Password reset link created: {reset_link}", "success")
        else:
            flash("If that email exists, a password reset link will be created.", "success")
        return redirect(url_for("forgot_password"))
    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    if user is None or user.reset_token_expires is None or user.reset_token_expires < datetime.utcnow():
        flash("This password reset link is invalid or expired.", "danger")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if not password or password != confirm:
            flash("Passwords must match.", "danger")
            return redirect(url_for("reset_password", token=token))
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expires = None
        user.auth_provider = "email"
        db.session.commit()
        flash("Password updated. Please sign in.", "success")
        return redirect(url_for("login"))
    return render_template("reset_password.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have logged out.", "success")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    donations = Donation.query.filter_by(donor_id=current_user.id).order_by(Donation.created_at.desc()).limit(5).all()
    campaigns = Campaign.query.filter_by(owner_id=current_user.id).order_by(Campaign.created_at.desc()).all()
    total_donated = db.session.query(func.coalesce(func.sum(Donation.amount), 0)).filter(Donation.donor_id == current_user.id).scalar() or 0
    received = db.session.query(func.coalesce(func.sum(Donation.amount), 0)).join(Campaign).filter(Campaign.owner_id == current_user.id).scalar() or 0
    metrics = {
        "total_donations": int(total_donated),
        "campaigns_supported": Donation.query.filter_by(donor_id=current_user.id).count(),
        "total_raised": int(received),
        "donations_received": db.session.query(Donation).join(Campaign).filter(Campaign.owner_id == current_user.id).count(),
    }
    return render_template("dashboard.html", user=current_user, metrics=metrics, donations=donations, campaigns=campaigns)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        email = normalize_email(request.form.get("email"))
        phone = clean_phone(request.form.get("phone"))
        email_owner = User.query.filter(func.lower(User.email) == email, User.id != current_user.id).first()
        phone_owner = User.query.filter(User.phone == phone, User.id != current_user.id).first() if phone else None
        if email_owner:
            flash("That email is already bonded to another account.", "danger")
            return redirect(url_for("profile"))
        if phone_owner:
            flash("That phone number is already bonded to another account.", "danger")
            return redirect(url_for("profile"))
        current_user.full_name = request.form.get("name", "").strip() or current_user.full_name
        current_user.email = email or current_user.email
        current_user.phone = phone
        current_user.city = request.form.get("city", "").strip()
        current_user.country = request.form.get("country", "").strip()
        current_user.bio = request.form.get("bio", "").strip()
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html")


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if current_user.password_hash and not current_user.check_password(current_password):
            flash("Current password is incorrect.", "danger")
            return redirect(url_for("settings"))
        if not password or password != confirm:
            flash("New passwords must match.", "danger")
            return redirect(url_for("settings"))
        current_user.set_password(password)
        current_user.auth_provider = "email"
        db.session.commit()
        flash("Password changed.", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html")


with app.app_context():
    ensure_schema()
    seed_campaigns()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)
