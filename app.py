import os
import csv
import secrets
import smtplib
from functools import wraps
from io import StringIO
from email.message import EmailMessage
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from flask import Flask, Response, abort, flash, redirect, render_template, request, send_from_directory, session, url_for
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


@app.after_request
def add_no_cache_headers(response):
    if response.content_type and response.content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


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
    is_admin = db.Column(db.Boolean, default=False)
    is_restricted = db.Column(db.Boolean, default=False)
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


class CompletedProject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    amount = db.Column(db.String(40), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(500), nullable=False)
    published = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Testimonial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(120), nullable=True)
    quote = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(500), nullable=False)
    published = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Partner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    logo = db.Column(db.String(80), nullable=False)
    caption = db.Column(db.String(180), nullable=False)
    website = db.Column(db.String(300), nullable=True)
    published = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SiteSetting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SupportMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    subject = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    conversation_id = db.Column(db.String(80), nullable=True, index=True)
    sender = db.Column(db.String(30), nullable=False, default="customer")
    reply = db.Column(db.Text, nullable=True)
    replied_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


CRYPTO_ADDRESS_BOOK = {
    "BTC": {
        "BTC": [
            "bc1ql45pwem9fussyr9r32n6kuz7sx0aeemtlaqpjm",
            "bc1qkffjus22ewuunu24x37le9t389ljjytpuae45m",
        ]
    },
    "ETH": {
        "ERC20": [
            "0x411266e5c271d4dcdeb92228dA9f37158f46A0F8",
            "0x8D7c83424a99C5617499E2F2aDbC71B1f9751FB0",
        ]
    },
    "USDC": {
        "ERC20": [
            "0x411266e5c271d4dcdeb92228dA9f37158f46A0F8",
            "0x8D7c83424a99C5617499E2F2aDbC71B1f9751FB0",
        ],
        "BEP20": [
            "0x411266e5c271d4dcdeb92228dA9f37158f46A0F8",
            "0x8D7c83424a99C5617499E2F2aDbC71B1f9751FB0",
        ],
        "TRC20": [
            "TAZFYj4hBdNEytNRSnVAqMxfKN3wnZdgLk",
            "TPkmQio6DCQGRQL4PKt9gh9zsbnBH3q6hQ",
        ],
        "SPL": [
            "J9gCsf2wzt1zqSpri379Nn7jhgzvnACQzEeEkfYNU8gy",
            "2MHUxNirXDvDWQ8hafUVkwTsMvfhLTGqNPhuRqDJMgNx",
        ],
    },
    "USDT": {
        "ERC20": [
            "0x411266e5c271d4dcdeb92228dA9f37158f46A0F8",
            "0x8D7c83424a99C5617499E2F2aDbC71B1f9751FB0",
        ],
        "BEP20": [
            "0x411266e5c271d4dcdeb92228dA9f37158f46A0F8",
            "0x8D7c83424a99C5617499E2F2aDbC71B1f9751FB0",
        ],
        "TRC20": [
            "TAZFYj4hBdNEytNRSnVAqMxfKN3wnZdgLk",
            "TPkmQio6DCQGRQL4PKt9gh9zsbnBH3q6hQ",
        ],
        "SPL": [
            "J9gCsf2wzt1zqSpri379Nn7jhgzvnACQzEeEkfYNU8gy",
            "2MHUxNirXDvDWQ8hafUVkwTsMvfhLTGqNPhuRqDJMgNx",
        ],
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
        "title": "Gaza Emergency Medical Aid",
        "category": "Gaza Aid",
        "patient": "Displaced Families",
        "organizer": "HopeBridge Relief Desk",
        "location": "Gaza",
        "goal": 85000,
        "image": "/static/images/hopebridge/gaza-family-shelter.jpg",
        "summary": "Emergency care, wound dressing, medicine, and clinic transport for families affected by conflict.",
        "story": "This verified emergency campaign supports families who need immediate medical supplies, clinic referrals, safe transport, and essential recovery items after displacement.",
        "verified": True,
    },
    {
        "title": "Cancer Treatment for Grace",
        "category": "Cancer Aid",
        "patient": "Grace",
        "organizer": "Grace's Care Team",
        "location": "Lagos, Nigeria",
        "goal": 42000,
        "image": "/static/images/hopebridge/child-cancer-care.jpg",
        "summary": "Chemotherapy, lab checks, medication, and nutrition support for a verified cancer patient.",
        "story": "Grace needs help completing treatment cycles, buying prescribed medication, and keeping follow-up appointments while her family manages daily care costs.",
        "verified": True,
    },
    {
        "title": "Urgent Surgery Support for Musa",
        "category": "Surgery Aid",
        "patient": "Musa",
        "organizer": "Musa's Family",
        "location": "Kano, Nigeria",
        "goal": 31500,
        "image": "/static/images/aid/surgery-operation.jpg",
        "summary": "Surgical deposit, theatre supplies, and post-operative medication for an urgent procedure.",
        "story": "Musa has been cleared for surgery but needs support for the hospital deposit, recovery medication, dressings, and transport for follow-up visits.",
        "verified": True,
    },
    {
        "title": "Kidney Transplant Bridge for Daniel",
        "category": "Kidney Transplant",
        "patient": "Daniel",
        "organizer": "Daniel's Siblings",
        "location": "Abuja, Nigeria",
        "goal": 120000,
        "image": "/static/images/hopebridge/hospital-iv-patient.jpg",
        "summary": "Pre-transplant tests, dialysis support, theatre deposit, and early recovery care.",
        "story": "Daniel's transplant process is ready to move forward after matching, but the family needs help covering diagnostic tests, dialysis sessions, admission fees, and recovery essentials.",
        "verified": True,
    },
    {
        "title": "Safe Housing for Displaced Children",
        "category": "Housing Aid",
        "patient": "Three Displaced Families",
        "organizer": "HopeBridge Shelter Partners",
        "location": "Northern Nigeria",
        "goal": 38000,
        "image": "/static/images/hopebridge/relief-camp-tents.jpg",
        "summary": "Temporary shelter, bedding, hygiene supplies, and safe sleeping space for displaced children.",
        "story": "This campaign helps families move from unsafe makeshift shelter into temporary accommodation while social workers coordinate longer-term support.",
        "verified": True,
    },
    {
        "title": "Transport to Treatment Fund",
        "category": "Transportation Aid",
        "patient": "Rural Patients",
        "organizer": "HopeBridge Transport Desk",
        "location": "Oyo, Nigeria",
        "goal": 18500,
        "image": "/static/images/aid/ambulance-rescue.jpg",
        "summary": "Ambulance and clinic transport for patients who cannot afford repeated hospital trips.",
        "story": "Verified patients are missing care because transport costs are too high. Donations fund scheduled rides, ambulance transfers, and appointment reminders.",
        "verified": True,
    },
    {
        "title": "Disaster Relief Medical Kits",
        "category": "Disaster Aid",
        "patient": "Flood-Affected Communities",
        "organizer": "HopeBridge Emergency Partners",
        "location": "Bayelsa, Nigeria",
        "goal": 56000,
        "image": "/static/images/hopebridge/humanitarian-aid-trucks.jpg",
        "summary": "First-aid kits, water purification tablets, mosquito nets, and basic clinic supplies after flooding.",
        "story": "Families affected by flooding need basic health supplies and rapid clinic support to prevent avoidable illness while homes and roads are being restored.",
        "verified": True,
    },
    {
        "title": "Feeding Aid for Recovery Families",
        "category": "Feeding Aid",
        "patient": "Caregiver Households",
        "organizer": "HopeBridge Nutrition Team",
        "location": "Ibadan, Nigeria",
        "goal": 24000,
        "image": "/static/images/hopebridge/food-queue-pots.jpg",
        "summary": "Nutritious food baskets for families caring for patients after surgery or cancer treatment.",
        "story": "Caregivers often lose income while supporting loved ones. This campaign provides nutritious food baskets and recovery meals during treatment weeks.",
        "verified": True,
    },
    {
        "title": "Dental Surgery for Little Samuel",
        "category": "Dental Aid",
        "patient": "Samuel",
        "organizer": "Samuel's Mother",
        "location": "Accra, Ghana",
        "goal": 9700,
        "image": "/static/images/aid/dental-child.jpg",
        "summary": "Specialist dental surgery, X-rays, medication, and follow-up care for a child in pain.",
        "story": "Samuel needs urgent dental treatment to stop recurring infection and pain. Donations cover scans, specialist care, medication, and transport.",
        "verified": True,
    },
    {
        "title": "Mobility Support for Aisha",
        "category": "Disability Aid",
        "patient": "Aisha",
        "organizer": "Community Care Circle",
        "location": "Kaduna, Nigeria",
        "goal": 16000,
        "image": "/static/images/aid/disability-support.jpg",
        "summary": "Wheelchair, physiotherapy sessions, home adjustments, and caregiver training.",
        "story": "Aisha needs mobility equipment and therapy support to regain independence after an accident. Funds are paid toward verified equipment and care sessions.",
        "verified": True,
    },
    {
        "title": "Child Vaccination Outreach",
        "category": "Children's Health",
        "patient": "Underserved Children",
        "organizer": "HopeBridge Clinic Partners",
        "location": "Kwara, Nigeria",
        "goal": 20500,
        "image": "/static/images/aid/child-injection.jpg",
        "summary": "Vaccination transport, clinic supplies, and follow-up for children in underserved communities.",
        "story": "This campaign helps clinic partners reach children whose families cannot afford transport or clinic-related costs for essential preventive care.",
        "verified": True,
    },
    {
        "title": "Emergency Ambulance Rescue Fund",
        "category": "Emergency Aid",
        "patient": "Critical Patients",
        "organizer": "HopeBridge Emergency Desk",
        "location": "Port Harcourt, Nigeria",
        "goal": 47000,
        "image": "/static/images/hopebridge/crisis-street-smoke.jpg",
        "summary": "Emergency ambulance response, oxygen support, and hospital transfer deposits.",
        "story": "When minutes matter, many families cannot pay ambulance or intake fees quickly. This fund helps verified cases move to care without avoidable delay.",
        "verified": True,
    },
    {
        "title": "Gaza Child Nutrition Relief",
        "category": "Gaza Aid",
        "patient": "Children in Shelter",
        "organizer": "HopeBridge Relief Desk",
        "location": "Gaza",
        "goal": 68000,
        "image": "/static/images/hopebridge/crying-child-cup.jpg",
        "summary": "Food packs, clean water, pediatric checkups, and caregiver support for children in shelter.",
        "story": "Children in temporary shelter need stable meals, hydration, and basic health checks. Donations support partner-led distribution and documentation.",
        "verified": True,
    },
    {
        "title": "Dialysis Access for Chinedu",
        "category": "Kidney Aid",
        "patient": "Chinedu",
        "organizer": "Chinedu's Friends",
        "location": "Enugu, Nigeria",
        "goal": 28500,
        "image": "/static/images/aid/hospital-bed.jpg",
        "summary": "Dialysis sessions, lab monitoring, medication, and transport while transplant options are reviewed.",
        "story": "Chinedu needs steady dialysis to stay stable. Funds support verified hospital sessions, medication, and travel for treatment appointments.",
        "verified": True,
    },
    {
        "title": "Maternal Surgery Aid for Esther",
        "category": "Maternal Health",
        "patient": "Esther",
        "organizer": "Esther's Care Group",
        "location": "Benin City, Nigeria",
        "goal": 22000,
        "image": "/static/images/aid/clinical-surgery.jpg",
        "summary": "Surgery deposit, blood work, recovery medication, and newborn support items.",
        "story": "Esther needs a safe surgical intervention and post-care support. Donations help her family meet verified hospital costs without delay.",
        "verified": True,
    },
    {
        "title": "Hospital Bed Recovery Support",
        "category": "Recovery Aid",
        "patient": "Post-Surgery Patients",
        "organizer": "HopeBridge Ward Partners",
        "location": "Uyo, Nigeria",
        "goal": 26000,
        "image": "/static/images/hopebridge/nurse-hand-care.jpg",
        "summary": "Recovery beds, wound-care materials, hygiene kits, and short-term home support.",
        "story": "Patients discharged after surgery still need safe recovery tools. This campaign provides beds, dressings, hygiene supplies, and follow-up support.",
        "verified": True,
    },
    {
        "title": "War-Affected Elder Care",
        "category": "Humanitarian Aid",
        "patient": "Older Adults",
        "organizer": "HopeBridge Relief Desk",
        "location": "Gaza",
        "goal": 33000,
        "image": "/static/images/aid/gaza-elder.jpg",
        "summary": "Medication, mobility help, food support, and clinic referrals for older displaced people.",
        "story": "Older adults in displacement often need medication continuity and mobility assistance. Donations help partners provide basic support and referrals.",
        "verified": True,
    },
    {
        "title": "Pediatric Surgery for Mariam",
        "category": "Children's Surgery",
        "patient": "Mariam",
        "organizer": "Mariam's Uncle",
        "location": "Kumasi, Ghana",
        "goal": 34500,
        "image": "/static/images/aid/operating-room.jpg",
        "summary": "Pediatric surgical care, admission fees, medication, and family lodging.",
        "story": "Mariam's family has been referred to a specialist center. Donations support admission, surgery supplies, recovery care, and nearby lodging.",
        "verified": True,
    },
    {
        "title": "Clinic Supplies for Disaster Response",
        "category": "Disaster Aid",
        "patient": "Partner Clinics",
        "organizer": "HopeBridge Supply Desk",
        "location": "Cross River, Nigeria",
        "goal": 51000,
        "image": "/static/images/hopebridge/rubble-search-frame.jpg",
        "summary": "Gloves, disinfectant, wound care, oral rehydration supplies, and triage materials.",
        "story": "Local clinics need reliable supplies after emergencies. This campaign helps them treat verified cases and document distribution transparently.",
        "verified": True,
    },
    {
        "title": "Safe Transport for Cancer Patients",
        "category": "Transportation Aid",
        "patient": "Cancer Patients",
        "organizer": "HopeBridge Transport Desk",
        "location": "Abuja, Nigeria",
        "goal": 19500,
        "image": "/static/images/hopebridge/patient-portrait-hope.jpg",
        "summary": "Scheduled rides for chemotherapy, radiotherapy, scans, and post-treatment reviews.",
        "story": "Transport costs can interrupt treatment. This fund supports recurring verified trips so patients can keep critical appointments on time.",
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

DEFAULT_SETTINGS = {
    "support_phone": "+2348000000000",
    "support_email": "support@hopebridge.org",
    "support_facebook": "https://facebook.com/hopebridge",
    "support_tiktok": "https://www.tiktok.com/@hopebridge",
    "support_whatsapp": "2348000000000",
    "bank_name": BANK_ACCOUNT["bank_name"],
    "bank_account_name": BANK_ACCOUNT["account_name"],
    "bank_account_number": BANK_ACCOUNT["account_number"],
}

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

PROJECT_COMPLETION_DETAILS = [
    ("Gaza Family Clinic Relief", "$64,850", "Partner medics supplied wound care, medicine, clean water, and safe transport for displaced families."),
    ("Grace Cancer Care Completion", "$42,000", "Chemotherapy cycles, nutrition support, and pharmacy bills were funded through verified donor records."),
    ("Musa Emergency Surgery Bridge", "$31,500", "The theatre deposit, surgical supplies, and post-operative medication were covered before discharge."),
    ("Daniel Kidney Care Reserve", "$58,420", "Dialysis sessions, transplant tests, and admission fees were paid directly to care providers."),
    ("Safe Shelter for Children", "$38,200", "Temporary rooms, bedding, hygiene packs, and care coordination supported displaced children."),
    ("Rural Treatment Transport", "$18,450", "Reliable hospital rides helped patients attend scans, chemotherapy, and follow-up appointments."),
    ("Flood Response Medical Kits", "$27,900", "Emergency kits, clean-water tablets, nets, and clinic consumables reached flood-affected families."),
    ("Recovery Food Basket Drive", "$24,600", "Caregiver households received high-nutrition food baskets during treatment and recovery weeks."),
    ("Samuel Pediatric Dental Fund", "$9,700", "Dental imaging, specialist treatment, medication, and follow-up transport were fully covered."),
    ("Aisha Mobility Equipment", "$16,000", "A wheelchair, physiotherapy sessions, and home-access support restored safer mobility."),
    ("Child Vaccination Outreach", "$20,500", "Clinic partners reached underserved children with transport support and essential preventive care."),
    ("Emergency Ambulance Response", "$47,000", "Ambulance transfers, oxygen support, and hospital intake deposits moved critical patients faster."),
    ("Gaza Child Nutrition Relief", "$68,000", "Food packs, pediatric checkups, and caregiver support were delivered through relief partners."),
    ("Chinedu Dialysis Access", "$28,500", "Dialysis, monitoring labs, medication, and treatment transport kept care on schedule."),
    ("Esther Maternal Surgery Aid", "$22,000", "Surgery fees, blood work, medication, and newborn essentials were paid for a safe recovery."),
    ("Hospital Bed Recovery Support", "$26,000", "Recovery beds, wound-care materials, hygiene kits, and home checks were completed."),
    ("War-Affected Elder Care", "$33,000", "Medication continuity, mobility support, and food assistance reached older displaced residents."),
    ("Mariam Pediatric Surgery", "$34,500", "Admission, surgery supplies, recovery medicine, and family lodging were funded."),
    ("Clinic Supplies for Disaster Response", "$51,000", "Gloves, disinfectant, triage materials, and wound-care supplies were stocked for partner clinics."),
    ("Safe Transport for Cancer Patients", "$19,500", "Scheduled rides reduced missed appointments for radiotherapy, chemotherapy, and medical reviews."),
    ("Lagos Screening Weekend", "$20,340", "Weekend screening booths reached workers who could not attend weekday hospital clinics."),
    ("Abuja Caregiver Shuttle", "$9,420", "A shared transport schedule reduced missed appointments for families outside Abuja."),
    ("Port Harcourt Lab Aid", "$17,880", "Lab fees were cleared for patients awaiting treatment-plan confirmation."),
    ("Kano Pediatric Support", "$28,650", "Children received nutrition support, blood tests, and family counselling services."),
    ("Ibadan Recovery Meals", "$12,240", "Dietitian-approved meals were supplied to patients with appetite loss during care."),
    ("Enugu Oncology Fund", "$30,150", "Verified hospital bills were settled directly with the treating facility."),
    ("Benin Patient Transport", "$10,780", "Long-distance travel grants helped patients keep specialist appointments."),
    ("Calabar Medicine Bank", "$22,930", "Essential medicines were purchased in bulk and distributed through clinic partners."),
    ("Jos Early Detection Day", "$15,870", "Community health workers screened residents and documented urgent referrals."),
    ("Uyo Family Support", "$14,990", "Rent, groceries, and school support stabilized families during intensive treatment."),
    ("Akure Diagnostic Bridge", "$19,410", "Diagnostic bottlenecks were cleared for patients awaiting final oncology review."),
    ("Owerri Treatment Grants", "$25,560", "Small treatment grants helped families complete cycles already underway."),
    ("Ilorin Care Kits", "$9,680", "Comfort kits, hygiene supplies, and post-care instructions reached recovering patients."),
    ("Asaba Pharmacy Fund", "$16,740", "Prescription gaps were closed for patients beginning second-line medication."),
    ("Makurdi Screening Bus", "$27,820", "A mobile team brought screening, education, and referrals to underserved communities."),
    ("Sokoto Patient Lodging", "$13,310", "Families traveling for care received clean lodging near partner hospitals."),
    ("Warri Follow-Up Fund", "$18,960", "Post-treatment review costs were funded so patients could complete clinical monitoring."),
    ("Gombe Ward Supplies", "$32,480", "Partner wards received gloves, disinfectant, bedding, and patient comfort items."),
    ("Abeokuta Survivorship Circle", "$11,540", "Survivors received counselling, nutrition coaching, and peer-support sessions."),
    ("Maiduguri Relief Grants", "$24,690", "Treatment and family support grants reached patients affected by displacement."),
    ("Minna Imaging Support", "$20,810", "MRI and CT scan appointments were funded for patients awaiting diagnosis."),
    ("Nnewi Surgical Aid", "$37,430", "Operating-room deposits and post-operative medications were covered for urgent cases."),
    ("Kaduna Family Bridge", "$15,620", "Families received emergency food, transport, and communication support during admissions."),
    ("Ado-Ekiti Medicine Drive", "$18,520", "Pharmacy vouchers helped patients continue prescribed medication without interruption."),
    ("Yenagoa Screening Desk", "$12,870", "Local volunteers registered residents for screening and follow-up calls."),
    ("Osogbo Chemotherapy Aid", "$29,780", "Treatment-cycle costs were paid directly to the hospital for verified patients."),
    ("Birnin Kebbi Care Travel", "$10,240", "Rural patients received travel stipends and appointment reminders."),
    ("Jalingo Patient Relief", "$17,360", "Emergency support covered consultation fees, tests, and immediate prescriptions."),
    ("Dutse Recovery Fund", "$21,940", "Patients leaving surgery received home supplies and post-care check-in support."),
    ("Awka Oncology Access", "$26,180", "Donor funds cleared treatment deposits and specialist review fees."),
    ("Bauchi Nutrition Basket", "$13,870", "Monthly nutrition baskets supported patients struggling with treatment-related weakness."),
    ("Lafia Diagnostics Fund", "$19,980", "Imaging and pathology invoices were settled for low-income families."),
    ("Lokoja Transport Circle", "$9,990", "Coordinated rides helped patients attend radiotherapy and follow-up appointments."),
    ("Umuaia Pharmacy Support", "$16,220", "Medication top-ups kept patients on schedule through treatment milestones."),
    ("Damaturu Care Grant", "$23,470", "Emergency grants helped families manage care costs during referral transfers."),
    ("Oshogbo Home Recovery", "$12,650", "Wound-care materials and home visits were funded after discharge."),
    ("Zaria Pediatric Relief", "$35,210", "Children received laboratory tests, nutritional support, and caregiver travel help."),
    ("Ikorodu Screening Clinic", "$18,780", "Pop-up screening served waterfront communities and escalated urgent cases."),
    ("Surulere Patient Desk", "$20,560", "Navigation support helped patients move from diagnosis to confirmed treatment plans."),
    ("Wuse Oncology Relief", "$27,140", "Verified families received final support needed to complete active treatment."),
]

TESTIMONIAL_DETAILS = [
    ("Amina Yusuf", "After the Gaza clinic relief project, my cousins received medicine and safe transport without being asked to repeat their story everywhere."),
    ("Grace Miller", "My chemotherapy support was handled with dignity, and every donor update matched the hospital payment record."),
    ("Ibrahim Musa", "The emergency surgery bridge helped my brother enter theatre on time instead of waiting for another family loan."),
    ("Daniel Reed", "The kidney-care reserve was clear, verified, and practical; dialysis appointments no longer depended on last-minute borrowing."),
    ("Mariam Bello", "The shelter support gave the children clean bedding and a calmer place to sleep while we rebuilt our plans."),
    ("Haruna Bello", "Transport support meant patients from our village stopped missing appointments because of fare increases."),
    ("Rachel Morgan", "The flood response kits arrived quickly and included the simple health supplies families were asking for."),
    ("Nora Williams", "Food baskets may sound small, but during recovery they helped my mother eat properly and take medication safely."),
    ("Samuel Carter", "My son's dental pain was taken seriously, and the fund covered X-rays, treatment, and the follow-up visit."),
    ("Aisha Umar", "The mobility equipment gave me back independence at home and made clinic visits less frightening."),
    ("Omar Hassan", "The vaccination outreach made preventive care possible for children whose parents could not afford the trip."),
    ("Fatima Bello", "When the ambulance came, HopeBridge had already helped with the transfer deposit and hospital intake."),
    ("Zainab Ali", "The nutrition relief for children was carefully organized, and caregivers received clear support notes."),
    ("Chinedu Okafor", "Dialysis support kept my treatment schedule stable while our family worked on the next medical step."),
    ("Esther Collins", "The maternal surgery aid covered the urgent costs and let me focus on recovery and my baby."),
    ("Emily Brooks", "The recovery bed and wound-care materials made home care safer after discharge."),
    ("Abdul Kareem", "Older relatives in displacement were not forgotten; medication and mobility help reached them with respect."),
    ("Maya Johnson", "Mariam's pediatric surgery update showed exactly what was paid and how her recovery was followed."),
    ("Victor Chen", "The disaster-response clinic supplies were concrete, trackable, and exactly the kind of support I wanted to fund."),
    ("Tunde Adebayo", "Safe transport gave cancer patients a dependable path to treatment instead of missed appointments."),
    ("Sophia Clark", "Every email was clear, and the reset-password flow saved me when I changed phones."),
    ("David Mensah", "I could start a campaign, upload my own image, and track support from one dashboard."),
    ("Lina Petrova", "The stories are handled with care, and the payment records are easy to follow."),
    ("Kelechi Nwosu", "A donor covered my aunt's medication, and the receipt showed the exact reference."),
    ("Isabella Grant", "The partner section gave our company confidence to support a verified medical fund."),
    ("Haruna Sani", "We received transport support for three appointments that would otherwise have been missed."),
    ("Camila Torres", "The site worked smoothly on my phone, especially the donation and receipt pages."),
    ("Noah Bennett", "I liked seeing completed projects because it proved the platform was not just promises."),
    ("Aisha Lawal", "The representative helped me choose the correct network before sending USDT."),
    ("Benjamin Scott", "The campaign cards were easy to compare, and the donation process was quick."),
    ("Priya Nair", "HopeBridge helped my colleague's family pay a treatment deposit at the right moment."),
    ("Musa Abdullahi", "The support team checked our documents and kept us updated until approval."),
    ("Hannah Evans", "I was able to give privately and still see the impact of my donation."),
    ("Kwame Boateng", "The process respected both the donor and the patient, which matters a lot."),
    ("Olivia Martin", "The testimonial and project pages helped me understand the community behind the platform."),
    ("Sade Thompson", "My family uploaded proof once, and the status page made the next step obvious."),
    ("George Miller", "I returned to donate again because the first experience was transparent and simple."),
    ("Amara Collins", "The platform helped our church group support a verified patient without messy spreadsheets."),
    ("Yusuf Ibrahim", "HopeBridge reduced the stress of explaining our needs repeatedly to different people."),
    ("Clara Hughes", "The profile tools made it easy to keep my account details correct."),
    ("Peter Okoye", "The bank-transfer instructions were direct, and the receipt kept the account details visible."),
    ("Nadia Karim", "I trusted the campaign more because the patient story and goal were clearly presented."),
    ("Ethan Price", "The representative chat gave me fast answers before I completed a larger donation."),
    ("Blessing Uche", "Our campaign received support from people we had never met, and everything was tracked."),
    ("Miriam Stein", "The site looks polished, but what mattered most was the clarity after donation."),
    ("Adeola Martins", "We used the dashboard to see new donations and prepare updates for supporters."),
    ("Lucas White", "HopeBridge showed that medical giving can be both personal and organized."),
    ("Theresa King", "I donated with USDC and appreciated the visible confirmation guidance."),
    ("Josephine Park", "The completed-project captions made each outcome feel concrete and believable."),
    ("Bashir Bello", "The team helped us correct our campaign details before publishing."),
    ("Catherine Young", "I shared a campaign link with friends because the page answered their questions quickly."),
    ("Malik Thompson", "The payment page did not disappear after submission, which made me feel calmer."),
    ("Ngozi Nnamdi", "Our family used the funds for medicine and transport exactly as described."),
    ("Dylan Cooper", "The platform made a difficult donation decision feel secure and well documented."),
    ("Ruth Adeyemi", "HopeBridge kept our story human while still checking the details carefully."),
    ("Marcus Green", "The administrator updates will make this even better for larger charity teams."),
    ("Halima Usman", "I could tell the system was built around patients, not just payment collection."),
    ("Sarah Blake", "The support response was warm, practical, and clear from the first message."),
    ("Collins Obi", "The verified campaign badge helped donors trust that our need was genuine."),
    ("Mei Lin", "I appreciate seeing many completed projects with different outcomes and real captions."),
]

PROJECT_PHOTOS = [
    "/static/images/hopebridge/displaced-family-tent.jpg",
    "/static/images/hopebridge/displaced-family-roadside.jpg",
    "/static/images/hopebridge/displaced-camp-cleanup.jpg",
    "/static/images/hopebridge/displaced-families-rubble.jpg",
    "/static/images/hopebridge/gaza-smoke-skyline.jpg",
    "/static/images/hopebridge/war-cloud-children.jpg",
    "/static/images/hopebridge/boy-smoke-road.jpg",
    "/static/images/hopebridge/child-war-bread.jpg",
    "/static/images/hopebridge/mother-baby-shelter.jpg",
    "/static/images/hopebridge/child-rubble-reflection.jpg",
    "/static/images/hopebridge/smiling-child-flowers.jpg",
    "/static/images/hopebridge/child-seated-poverty.jpg",
    "/static/images/hopebridge/praying-child-alley.jpg",
    "/static/images/hopebridge/child-grapes.jpg",
    "/static/images/hopebridge/water-aid-child.jpg",
    "/static/images/hopebridge/two-children-camp.jpg",
    "/static/images/hopebridge/child-carrying-sacks.jpg",
    "/static/images/hopebridge/children-sharing-meal.jpg",
    "/static/images/hopebridge/home-rebuild-donation.webp",
    "/static/images/aid/gaza-children-2.jpg",
    "/static/images/aid/gaza-portrait.jpg",
    "/static/images/aid/gaza-war-1.jpg",
    "/static/images/aid/gaza-smoke.jpg",
    "/static/images/aid/gaza-shelter.jpg",
    "/static/images/aid/gaza-family.jpg",
    "/static/images/aid/gaza-food.jpg",
    "/static/images/aid/gaza-boy.jpg",
    "/static/images/aid/gaza-children-1.jpg",
    "/static/images/aid/surgery-emergency-1.jpg",
    "/static/images/aid/surgery-emergency-2.jpg",
    "/static/images/aid/clinical-surgery.jpg?project-photo=31",
    "/static/images/aid/dental-care.jpg",
    "/static/images/aid/dental-xray.jpg",
    "https://images.unsplash.com/photo-1576091160550-2173dba999ef?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1584515933487-779824d29309?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1504439468489-c8920d796a29?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1587854692152-cbe660dbde88?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1516549655169-df83a0774514?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1538108149393-fbbd81895907?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1586773860418-d37222d8fce3?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1579684385127-1ef15d508118?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1584516150909-c43483ee7932?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1469571486292-b53601020a1f?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1554734867-bf3c00a49371?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1498837167922-ddd27525d352?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1511895426328-dc8714191300?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1497633762265-9d179a990aa6?auto=format&fit=crop&w=900&q=80",
    "https://source.unsplash.com/900x650/?medical-aid,clinic&sig=48",
    "https://source.unsplash.com/900x650/?humanitarian-aid,relief&sig=49",
    "https://source.unsplash.com/900x650/?hospital-patient,recovery&sig=50",
    "https://source.unsplash.com/900x650/?ambulance,healthcare&sig=51",
    "https://source.unsplash.com/900x650/?food-aid,community&sig=52",
    "https://source.unsplash.com/900x650/?shelter,relief&sig=53",
    "https://source.unsplash.com/900x650/?doctor,patient&sig=54",
    "https://source.unsplash.com/900x650/?children,aid&sig=55",
    "https://source.unsplash.com/900x650/?clean-water,relief&sig=56",
    "https://source.unsplash.com/900x650/?disaster-relief,medical&sig=57",
    "https://source.unsplash.com/900x650/?nurse,care&sig=58",
    "https://source.unsplash.com/900x650/?community-health,aid&sig=59",
    "https://source.unsplash.com/900x650/?clinic-supplies,health&sig=60",
]

COMPLETED_PROJECTS = [
    {
        "title": title,
        "amount": amount,
        "summary": summary,
        "image": (
            f"{PROJECT_PHOTOS[index % len(PROJECT_PHOTOS)]}"
            f"{'&' if '?' in PROJECT_PHOTOS[index % len(PROJECT_PHOTOS)] else '?'}project={index + 1}"
        ),
    }
    for index, (title, amount, summary) in enumerate(PROJECT_COMPLETION_DETAILS)
]

TESTIMONIAL_PHOTOS = [
    "https://i.pravatar.cc/180?img=1",
    "https://i.pravatar.cc/180?img=2",
    "https://i.pravatar.cc/180?img=3",
    "https://i.pravatar.cc/180?img=4",
    "https://i.pravatar.cc/180?img=5",
    "https://i.pravatar.cc/180?img=6",
    "https://i.pravatar.cc/180?img=7",
    "https://i.pravatar.cc/180?img=8",
    "https://i.pravatar.cc/180?img=9",
    "https://i.pravatar.cc/180?img=10",
    "https://i.pravatar.cc/180?img=11",
    "https://i.pravatar.cc/180?img=12",
    "https://i.pravatar.cc/180?img=13",
    "https://i.pravatar.cc/180?img=14",
    "https://i.pravatar.cc/180?img=15",
    "https://i.pravatar.cc/180?img=16",
    "https://i.pravatar.cc/180?img=17",
    "https://i.pravatar.cc/180?img=18",
    "https://i.pravatar.cc/180?img=19",
    "https://i.pravatar.cc/180?img=20",
    "https://i.pravatar.cc/180?img=21",
    "https://i.pravatar.cc/180?img=22",
    "https://i.pravatar.cc/180?img=23",
    "https://i.pravatar.cc/180?img=24",
    "https://i.pravatar.cc/180?img=25",
    "https://i.pravatar.cc/180?img=26",
    "https://i.pravatar.cc/180?img=27",
    "https://i.pravatar.cc/180?img=28",
    "https://i.pravatar.cc/180?img=29",
    "https://i.pravatar.cc/180?img=30",
    "https://i.pravatar.cc/180?img=31",
    "https://i.pravatar.cc/180?img=32",
    "https://i.pravatar.cc/180?img=33",
    "https://i.pravatar.cc/180?img=34",
    "https://i.pravatar.cc/180?img=35",
    "https://i.pravatar.cc/180?img=36",
    "https://i.pravatar.cc/180?img=37",
    "https://i.pravatar.cc/180?img=38",
    "https://i.pravatar.cc/180?img=39",
    "https://i.pravatar.cc/180?img=40",
    "https://i.pravatar.cc/180?img=41",
    "https://i.pravatar.cc/180?img=42",
    "https://i.pravatar.cc/180?img=43",
    "https://i.pravatar.cc/180?img=44",
    "https://i.pravatar.cc/180?img=45",
    "https://i.pravatar.cc/180?img=46",
    "https://i.pravatar.cc/180?img=47",
    "https://i.pravatar.cc/180?img=48",
    "https://i.pravatar.cc/180?img=49",
    "https://i.pravatar.cc/180?img=50",
    "https://i.pravatar.cc/180?img=51",
    "https://i.pravatar.cc/180?img=52",
    "https://i.pravatar.cc/180?img=53",
    "https://i.pravatar.cc/180?img=54",
    "https://i.pravatar.cc/180?img=55",
    "https://i.pravatar.cc/180?img=56",
    "https://i.pravatar.cc/180?img=57",
    "https://i.pravatar.cc/180?img=58",
    "https://i.pravatar.cc/180?img=59",
    "https://i.pravatar.cc/180?img=60",
]

TESTIMONIALS = [
    {
        "name": name,
        "quote": quote,
        "image": TESTIMONIAL_PHOTOS[index],
    }
    for index, (name, quote) in enumerate(TESTIMONIAL_DETAILS)
]


def format_money(value):
    return "${:,.0f}".format(value or 0)


app.jinja_env.filters["money"] = format_money


def normalize_email(email):
    return (email or "").strip().lower()


def clean_phone(phone):
    return (phone or "").strip() or None


def admin_emails():
    configured = os.environ.get("ADMIN_EMAILS", "")
    return {normalize_email(email) for email in configured.split(",") if normalize_email(email)}


def is_admin_user(user=None):
    user = user or current_user
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_admin", False) or normalize_email(user.email) in admin_emails())


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not is_admin_user():
            abort(403)
        return view_func(*args, **kwargs)
    return wrapped


def get_support_conversation_id(create=False):
    if current_user.is_authenticated:
        return f"user-{current_user.id}"
    if create and "support_conversation_id" not in session:
        session["support_conversation_id"] = f"guest-{secrets.token_hex(8)}"
    return session.get("support_conversation_id")


def get_support_chat_history(limit=20):
    conversation_id = get_support_conversation_id(create=False)
    if not conversation_id:
        return []
    return (
        SupportMessage.query.filter_by(conversation_id=conversation_id)
        .order_by(SupportMessage.created_at.asc(), SupportMessage.id.asc())
        .limit(limit)
        .all()
    )


def get_support_conversations():
    messages = SupportMessage.query.order_by(SupportMessage.created_at.desc(), SupportMessage.id.desc()).all()
    conversations = {}
    for message in messages:
        key = message.conversation_id or f"legacy-{message.id}"
        if key not in conversations:
            conversations[key] = {"id": key, "latest": message, "root": message, "messages": [], "status": message.status}
        conversations[key]["messages"].append(message)
        if message.sender != "admin":
            conversations[key]["root"] = message
        if message.status == "open":
            conversations[key]["status"] = "open"
        elif conversations[key]["status"] != "open" and message.status == "replied":
            conversations[key]["status"] = "replied"
    for conversation in conversations.values():
        conversation["messages"].sort(key=lambda item: (item.created_at or datetime.min, item.id or 0))
    return list(conversations.values())



IMPACT_SUMMARY = [
    {"icon": "bi-heart-pulse", "value": "2,500+", "label": "Lives Supported"},
    {"icon": "bi-cash-stack", "value": "$245,000+", "label": "Raised Transparently"},
    {"icon": "bi-globe2", "value": "18", "label": "Countries Reached"},
    {"icon": "bi-hospital", "value": "120+", "label": "Medical Cases Completed"},
    {"icon": "bi-people", "value": "4,800+", "label": "Donors And Partners"},
]

TRUST_SUMMARY = [
    {"icon": "bi-patch-check", "title": "Registered oversight", "text": "NGO Registration: HB-NGO-2026-014"},
    {"icon": "bi-geo-alt", "title": "Operations desk", "text": "Lagos, Nigeria with international relief coordination"},
    {"icon": "bi-shield-lock", "title": "Verification process", "text": "Campaigns are reviewed before publication and funding release"},
    {"icon": "bi-file-earmark-text", "title": "Donor reporting", "text": "Project records, receipts, and completion summaries are maintained"},
]

PROJECT_BADGES = [
    ("Fully Funded", "bi-check2-circle", "badge-funded"),
    ("Treatment Completed", "bi-heart-pulse", "badge-treatment"),
    ("Emergency Relief Delivered", "bi-globe2", "badge-relief"),
    ("Life Saved", "bi-heart-fill", "badge-life"),
]

PROJECT_COUNTRIES = [
    "Gaza", "Nigeria", "Lebanon", "Sudan", "Kenya", "Ghana", "Sierra Leone", "Uganda", "Somalia", "Rwanda",
    "Pakistan", "Bangladesh", "Haiti", "Nepal", "Ethiopia", "Yemen", "Cameroon", "Liberia", "South Africa", "Malawi",
]

PROJECT_DATES = [
    "May 2026", "Apr 2026", "Mar 2026", "Feb 2026", "Jan 2026", "Dec 2025", "Nov 2025", "Oct 2025", "Sep 2025", "Aug 2025",
    "Jul 2025", "Jun 2025", "May 2025", "Apr 2025", "Mar 2025", "Feb 2025", "Jan 2025", "Dec 2024", "Nov 2024", "Oct 2024",
]

PROJECT_METRIC_SETS = [
    [("bi-people", "1,250 Families Assisted"), ("bi-droplet", "18 Water Points Installed"), ("bi-box-seam", "4,600 Relief Packs Delivered")],
    [("bi-hospital", "320 Patients Treated"), ("bi-capsule", "2,800 Medicines Supplied"), ("bi-person-check", "46 Follow-up Visits Covered")],
    [("bi-house-heart", "140 Shelter Kits Delivered"), ("bi-truck", "22 Transport Runs Funded"), ("bi-people", "980 People Reached")],
    [("bi-heart-pulse", "28 Surgeries Completed"), ("bi-clipboard2-pulse", "91 Clinical Tests Covered"), ("bi-shield-check", "100% Case Reviews Closed")],
    [("bi-egg-fried", "12,400 Meals Served"), ("bi-backpack", "740 Children Supported"), ("bi-calendar-check", "30 Days Emergency Feeding")],
    [("bi-bus-front", "86 Medical Trips Covered"), ("bi-hospital", "19 Referral Cases Completed"), ("bi-person-wheelchair", "34 Mobility Supports Provided")],
]


def campaign_days_remaining(campaign):
    created_at = getattr(campaign, "created_at", None) or datetime.utcnow()
    elapsed = max(0, (datetime.utcnow() - created_at).days)
    return max(1, 30 - (elapsed % 30))


def project_impact(index):
    badge, icon, badge_class = PROJECT_BADGES[index % len(PROJECT_BADGES)]
    return {
        "badge": badge,
        "icon": icon,
        "badge_class": badge_class,
        "country": PROJECT_COUNTRIES[index % len(PROJECT_COUNTRIES)],
        "date": PROJECT_DATES[index % len(PROJECT_DATES)],
        "metrics": PROJECT_METRIC_SETS[index % len(PROJECT_METRIC_SETS)],
    }


def generate_reference(prefix="HB"):
    return f"{prefix}-{secrets.token_hex(5).upper()}"


def external_url_for(endpoint, **values):
    return url_for(endpoint, _external=True, **values)


@app.context_processor
def inject_template_globals():
    return {
        "is_admin_context": is_admin_user(),
        "site_settings": get_settings(),
        "support_chat_history": get_support_chat_history(),
        "impact_summary": IMPACT_SUMMARY,
        "trust_summary": TRUST_SUMMARY,
        "project_impact": project_impact,
        "campaign_days_remaining": campaign_days_remaining,
    }


def get_campaigns():
    return Campaign.query.order_by(Campaign.created_at.asc()).all()


def get_completed_projects(limit=None):
    query = CompletedProject.query.filter_by(published=True).order_by(CompletedProject.sort_order.asc(), CompletedProject.id.asc())
    return query.limit(limit).all() if limit else query.all()


def get_testimonials(limit=None):
    query = Testimonial.query.filter_by(published=True).order_by(Testimonial.sort_order.asc(), Testimonial.id.asc())
    return query.limit(limit).all() if limit else query.all()


def get_partners():
    return Partner.query.filter_by(published=True).order_by(Partner.sort_order.asc(), Partner.id.asc()).all()


def get_setting(key, default=None):
    setting = db.session.get(SiteSetting, key)
    if setting is None or setting.value in (None, ""):
        return default
    return setting.value


def get_settings():
    values = dict(DEFAULT_SETTINGS)
    if db.engine is None:
        return values
    try:
        for setting in SiteSetting.query.all():
            values[setting.key] = setting.value
    except Exception:
        return values
    return values


def set_setting(key, value):
    setting = db.session.get(SiteSetting, key)
    if setting is None:
        db.session.add(SiteSetting(key=key, value=value))
    else:
        setting.value = value


def csv_response(filename, rows, headers):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def select_crypto_address(asset, network):
    addresses = CRYPTO_ADDRESS_BOOK.get(asset, {}).get(network, [])
    if not addresses:
        return None
    count = Donation.query.filter_by(payment_method="crypto", payment_asset=asset, payment_network=network).count()
    return addresses[count % len(addresses)]


def crypto_qr_url(donation):
    if donation.payment_method != "crypto" or not donation.payment_address:
        return None
    return f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={quote_plus(donation.payment_address)}"


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


def send_reset_email(user, reset_link):
    host = os.environ.get("SMTP_HOST")
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("SMTP_FROM", username or get_setting("support_email", DEFAULT_SETTINGS["support_email"]))
    if not host or not username or not password:
        return False
    message = EmailMessage()
    message["Subject"] = "Reset your HopeBridge password"
    message["From"] = sender
    message["To"] = user.email
    message.set_content(
        f"Hello {user.full_name},\n\nUse this secure link to reset your HopeBridge password:\n{reset_link}\n\nThis link expires in 1 hour."
    )
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)
    return True


def send_support_reply(message, reply_text):
    host = os.environ.get("SMTP_HOST")
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("SMTP_FROM", username or get_setting("support_email", DEFAULT_SETTINGS["support_email"]))
    if not host or not username or not password:
        return False
    email = EmailMessage()
    email["Subject"] = f"HopeBridge Support: {message.subject}"
    email["From"] = sender
    email["To"] = message.email
    email.set_content(
        f"Hello {message.full_name},\n\n{reply_text}\n\nRegards,\nHopeBridge Support"
    )
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(email)
    return True


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
    if user.is_restricted:
        flash("This account has been restricted. Please contact HopeBridge support.", "danger")
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
        else:
            for field in ("category", "patient", "organizer", "location", "goal", "image", "summary", "story", "verified"):
                setattr(existing, field, data[field])
    db.session.commit()


def seed_site_content():
    existing_projects = CompletedProject.query.order_by(CompletedProject.sort_order.asc(), CompletedProject.id.asc()).all()
    if not existing_projects:
        for index, data in enumerate(COMPLETED_PROJECTS):
            db.session.add(
                CompletedProject(
                    title=data["title"],
                    amount=data["amount"],
                    summary=data["summary"],
                    image=data["image"],
                    sort_order=index,
                )
            )
    else:
        for index, data in enumerate(COMPLETED_PROJECTS):
            if index < len(existing_projects):
                project = existing_projects[index]
                project.title = data["title"]
                project.amount = data["amount"]
                project.summary = data["summary"]
                project.image = data["image"]
                project.sort_order = index
            else:
                db.session.add(
                    CompletedProject(
                        title=data["title"],
                        amount=data["amount"],
                        summary=data["summary"],
                        image=data["image"],
                        sort_order=index,
                    )
                )
    existing_testimonials = Testimonial.query.order_by(Testimonial.sort_order.asc(), Testimonial.id.asc()).all()
    if not existing_testimonials:
        for index, data in enumerate(TESTIMONIALS):
            db.session.add(
                Testimonial(
                    name=data["name"],
                    quote=data["quote"],
                    role="HopeBridge community member",
                    image=data["image"],
                    sort_order=index,
                )
            )
    else:
        for index, data in enumerate(TESTIMONIALS):
            if index < len(existing_testimonials):
                testimonial = existing_testimonials[index]
                testimonial.name = data["name"]
                testimonial.quote = data["quote"]
                testimonial.role = "HopeBridge community member"
                testimonial.image = data["image"]
                testimonial.sort_order = index
            else:
                db.session.add(
                    Testimonial(
                        name=data["name"],
                        quote=data["quote"],
                        role="HopeBridge community member",
                        image=data["image"],
                        sort_order=index,
                    )
                )
    if Partner.query.count() == 0:
        for index, data in enumerate(PARTNERS):
            db.session.add(
                Partner(
                    name=data["name"],
                    logo=data["logo"],
                    caption=data["caption"],
                    website="",
                    sort_order=index,
                )
            )
    for key, value in DEFAULT_SETTINGS.items():
        if db.session.get(SiteSetting, key) is None:
            db.session.add(SiteSetting(key=key, value=value))
    db.session.commit()


def ensure_schema():
    db.create_all()
    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()
    if "user" not in table_names:
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
        "is_admin": "BOOLEAN DEFAULT FALSE",
        "is_restricted": "BOOLEAN DEFAULT FALSE",
        "created_at": "TIMESTAMP",
    }
    for name, definition in additions.items():
        if name not in columns:
            db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {name} {definition}'))
    if "support_message" in table_names:
        message_columns = {column["name"] for column in inspector.get_columns("support_message")}
        message_additions = {
            "conversation_id": "VARCHAR(80)",
            "sender": "VARCHAR(30) DEFAULT 'customer'",
            "reply": "TEXT",
            "replied_at": "TIMESTAMP",
        }
        for name, definition in message_additions.items():
            if name not in message_columns:
                db.session.execute(text(f'ALTER TABLE support_message ADD COLUMN {name} {definition}'))
    db.session.commit()


@app.route("/")
def home():
    return render_template(
        "index.html",
        campaigns=get_campaigns()[:3],
        completed_projects=get_completed_projects(6),
        testimonials=get_testimonials(6),
        partners=get_partners(),
    )


@app.route("/about")
def about():
    return render_template(
        "about.html",
        executives=EXECUTIVES,
        values=ABOUT_VALUES,
        partners=get_partners(),
    )


@app.route("/projects")
def completed_projects():
    return render_template("projects.html", projects=get_completed_projects())


@app.route("/testimonials")
def testimonials():
    return render_template("testimonials.html", testimonials=get_testimonials())


@app.route("/contact", methods=["POST"])
def contact():
    return_to = request.referrer or url_for("home")
    is_chat_widget = request.form.get("subject") == "Chat with representative"
    fallback_name = current_user.full_name if current_user.is_authenticated else "Website Visitor"
    fallback_email = current_user.email if current_user.is_authenticated else get_setting("support_email", DEFAULT_SETTINGS["support_email"])
    conversation_id = get_support_conversation_id(create=is_chat_widget)
    message = SupportMessage(
        full_name=request.form.get("name", "").strip() or fallback_name,
        email=normalize_email(request.form.get("email")) or fallback_email,
        phone=clean_phone(request.form.get("phone")),
        subject=request.form.get("subject", "Support request").strip(),
        message=request.form.get("message", "").strip(),
        conversation_id=conversation_id,
        sender="customer",
    )
    if not message.full_name or not message.email or not message.message:
        flash("Please complete your name, email, and message.", "danger")
        return redirect(return_to)
    db.session.add(message)
    db.session.commit()
    flash(
        "Your chat message has been sent to HopeBridge support. A representative will review it from the admin desk."
        if is_chat_widget
        else "Your message has been sent to HopeBridge support. A representative will review it from the admin dashboard.",
        "success",
    )
    return redirect(return_to)


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
    return render_template("campaign_detail.html", campaign=campaign, donations=donations, share_url=external_url_for("campaign_detail", campaign_id=campaign.id))


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
            settings = get_settings()
            donation.bank_name = settings["bank_name"]
            donation.bank_account_name = settings["bank_account_name"]
            donation.bank_account_number = settings["bank_account_number"]
            donation.proof_filename = save_upload(request.files.get("bank_proof"))

        db.session.add(donation)
        db.session.commit()
        return redirect(url_for("donation_receipt", reference=donation.reference))

    return render_template(
        "donate.html",
        campaign=campaign,
        crypto_book=CRYPTO_ADDRESS_BOOK,
        giftcards=GIFT_CARD_TYPES,
        bank_account={
            "bank_name": get_setting("bank_name", BANK_ACCOUNT["bank_name"]),
            "account_name": get_setting("bank_account_name", BANK_ACCOUNT["account_name"]),
            "account_number": get_setting("bank_account_number", BANK_ACCOUNT["account_number"]),
        },
    )


@app.route("/donation/<reference>", methods=["GET", "POST"])
def donation_receipt(reference):
    donation = Donation.query.filter_by(reference=reference).first_or_404()
    if request.method == "POST":
        uploaded_proof = save_upload(request.files.get("payment_proof"))
        if uploaded_proof:
            donation.proof_filename = uploaded_proof
            db.session.commit()
            flash("Payment proof submitted. HopeBridge support will review and confirm your payment.", "success")
        else:
            flash("Payment record submitted. You can still contact support if you need help uploading proof.", "success")
        return redirect(url_for("dashboard") if current_user.is_authenticated else url_for("home"))
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
        flash(
            "Welcome to HopeBridge. Your account is ready. From your dashboard you can start a campaign, track donations, upload payment proof, and manage your profile. If you need help at any point, use the support chat button or contact HopeBridge support from the footer.",
            "success",
        )
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
        if user.is_restricted:
            flash("This account has been restricted. Please contact HopeBridge support.", "danger")
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
            try:
                sent = send_reset_email(user, reset_link)
            except Exception:
                sent = False
            if sent:
                flash("Password reset instructions have been sent to your email.", "success")
            else:
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


@app.route("/messages")
@login_required
def messages():
    return render_template("messages.html", messages=get_support_chat_history(limit=100), user=current_user)


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


@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    metrics = {
        "users": User.query.count(),
        "campaigns": Campaign.query.count(),
        "pending_campaigns": Campaign.query.filter_by(verified=False).count(),
        "donations": Donation.query.count(),
        "pending_donations": Donation.query.filter_by(status="pending").count(),
        "confirmed_total": db.session.query(func.coalesce(func.sum(Donation.amount), 0)).filter(Donation.status == "confirmed").scalar() or 0,
        "messages": SupportMessage.query.filter_by(status="open").count(),
        "content_items": CompletedProject.query.count() + Testimonial.query.count() + Partner.query.count(),
    }
    recent_campaigns = Campaign.query.order_by(Campaign.created_at.desc()).limit(5).all()
    recent_donations = Donation.query.order_by(Donation.created_at.desc()).limit(5).all()
    return render_template(
        "admin_dashboard.html",
        metrics=metrics,
        campaigns=recent_campaigns,
        donations=recent_donations,
    )


@app.route("/admin/campaigns")
@login_required
@admin_required
def admin_campaigns():
    campaigns = Campaign.query.order_by(Campaign.created_at.desc()).all()
    return render_template("admin_campaigns.html", campaigns=campaigns)


@app.route("/admin/campaign/<int:campaign_id>/verify", methods=["POST"])
@login_required
@admin_required
def admin_verify_campaign(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if campaign is None:
        abort(404)
    campaign.verified = request.form.get("verified") == "true"
    db.session.commit()
    flash(f"{campaign.title} verification updated.", "success")
    return redirect(request.referrer or url_for("admin_campaigns"))


@app.route("/admin/campaign/<int:campaign_id>/complete", methods=["POST"])
@login_required
@admin_required
def admin_complete_campaign(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if campaign is None:
        abort(404)
    campaign.completed = request.form.get("completed") == "true"
    db.session.commit()
    flash(f"{campaign.title} completion status updated.", "success")
    return redirect(request.referrer or url_for("admin_campaigns"))


@app.route("/admin/donations")
@login_required
@admin_required
def admin_donations():
    donations = Donation.query.order_by(Donation.created_at.desc()).all()
    return render_template("admin_donations.html", donations=donations)


@app.route("/admin/donation/<int:donation_id>/status", methods=["POST"])
@login_required
@admin_required
def admin_update_donation_status(donation_id):
    donation = db.session.get(Donation, donation_id)
    if donation is None:
        abort(404)
    status = request.form.get("status")
    if status not in ("pending", "confirmed", "rejected"):
        flash("Choose a valid donation status.", "danger")
        return redirect(request.referrer or url_for("admin_donations"))
    donation.status = status
    db.session.commit()
    flash(f"Donation {donation.reference} marked as {status}.", "success")
    return redirect(request.referrer or url_for("admin_donations"))


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=users)


@app.route("/admin/user/new", methods=["POST"])
@login_required
@admin_required
def admin_create_user():
    full_name = request.form.get("full_name", "").strip()
    email = normalize_email(request.form.get("email"))
    phone = clean_phone(request.form.get("phone"))
    password = request.form.get("password", "").strip() or "HopeBridgeUser123"
    if not full_name or not email:
        flash("Full name and email are required to add a user.", "danger")
        return redirect(url_for("admin_users"))
    if User.query.filter(func.lower(User.email) == email).first():
        flash("A user with that email already exists.", "danger")
        return redirect(url_for("admin_users"))
    user = User(
        full_name=full_name,
        email=email,
        phone=phone,
        auth_provider="email",
        is_admin=request.form.get("is_admin") == "on",
        is_restricted=request.form.get("is_restricted") == "on",
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f"{user.full_name} was added. Temporary password: {password}", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/toggle-admin", methods=["POST"])
@login_required
@admin_required
def admin_toggle_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot remove admin access from your own account here.", "danger")
        return redirect(url_for("admin_users"))
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"{user.full_name}'s admin access was updated.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/toggle-restriction", methods=["POST"])
@login_required
@admin_required
def admin_toggle_user_restriction(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot restrict your own active admin account.", "danger")
        return redirect(url_for("admin_users"))
    user.is_restricted = not user.is_restricted
    db.session.commit()
    flash(f"{user.full_name}'s account restriction was updated.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot delete your own active admin account.", "danger")
        return redirect(url_for("admin_users"))
    name = user.full_name
    Donation.query.filter_by(donor_id=user.id).update({"donor_id": None})
    Campaign.query.filter_by(owner_id=user.id).update({"owner_id": None})
    SocialAccount.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f"{name} was removed from HopeBridge.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/campaign/<int:campaign_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_edit_campaign(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if campaign is None:
        abort(404)
    if request.method == "POST":
        goal = int(request.form.get("goal", campaign.goal) or campaign.goal)
        uploaded_image = save_upload(request.files.get("campaign_image"))
        campaign.title = request.form.get("title", "").strip() or campaign.title
        campaign.patient = request.form.get("patient", "").strip() or campaign.patient
        campaign.category = request.form.get("category", "").strip() or campaign.category
        campaign.organizer = request.form.get("organizer", "").strip() or campaign.organizer
        campaign.location = request.form.get("location", "").strip() or campaign.location
        campaign.goal = goal
        campaign.summary = request.form.get("summary", "").strip() or campaign.summary
        campaign.story = request.form.get("story", "").strip() or campaign.story
        campaign.image = url_for("static", filename=f"uploads/{uploaded_image}") if uploaded_image else request.form.get("image", "").strip() or campaign.image
        campaign.verified = request.form.get("verified") == "on"
        campaign.completed = request.form.get("completed") == "on"
        db.session.commit()
        flash("Campaign updated.", "success")
        return redirect(url_for("admin_campaigns"))
    return render_template("admin_campaign_form.html", campaign=campaign)


@app.route("/admin/campaign/<int:campaign_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_campaign(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if campaign is None:
        abort(404)
    if campaign.donations:
        flash("This campaign has donations, so it was archived instead of deleted.", "warning")
        campaign.verified = False
        campaign.completed = True
    else:
        db.session.delete(campaign)
    db.session.commit()
    return redirect(url_for("admin_campaigns"))


@app.route("/admin/content")
@login_required
@admin_required
def admin_content():
    return render_template(
        "admin_content.html",
        projects=CompletedProject.query.order_by(CompletedProject.sort_order.asc(), CompletedProject.id.asc()).all(),
        testimonials=Testimonial.query.order_by(Testimonial.sort_order.asc(), Testimonial.id.asc()).all(),
        partners=Partner.query.order_by(Partner.sort_order.asc(), Partner.id.asc()).all(),
    )


@app.route("/admin/project/new", methods=["GET", "POST"])
@app.route("/admin/project/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_project_form(project_id=None):
    project = db.session.get(CompletedProject, project_id) if project_id else CompletedProject()
    if project_id and project is None:
        abort(404)
    if request.method == "POST":
        uploaded_image = save_upload(request.files.get("image_file"))
        project.title = request.form.get("title", "").strip()
        project.amount = request.form.get("amount", "").strip()
        project.summary = request.form.get("summary", "").strip()
        project.image = url_for("static", filename=f"uploads/{uploaded_image}") if uploaded_image else request.form.get("image", "").strip() or project.image
        project.published = request.form.get("published") == "on"
        project.sort_order = int(request.form.get("sort_order", "0") or 0)
        if not project.title or not project.amount or not project.summary or not project.image:
            flash("Please complete every project field.", "danger")
            return redirect(request.url)
        db.session.add(project)
        db.session.commit()
        flash("Completed project saved.", "success")
        return redirect(url_for("admin_content"))
    return render_template("admin_project_form.html", project=project)


@app.route("/admin/project/<int:project_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_project(project_id):
    project = db.session.get(CompletedProject, project_id)
    if project is None:
        abort(404)
    db.session.delete(project)
    db.session.commit()
    flash("Completed project deleted.", "success")
    return redirect(url_for("admin_content"))


@app.route("/admin/testimonial/new", methods=["GET", "POST"])
@app.route("/admin/testimonial/<int:testimonial_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_testimonial_form(testimonial_id=None):
    testimonial = db.session.get(Testimonial, testimonial_id) if testimonial_id else Testimonial()
    if testimonial_id and testimonial is None:
        abort(404)
    if request.method == "POST":
        uploaded_image = save_upload(request.files.get("image_file"))
        testimonial.name = request.form.get("name", "").strip()
        testimonial.role = request.form.get("role", "").strip()
        testimonial.quote = request.form.get("quote", "").strip()
        testimonial.image = url_for("static", filename=f"uploads/{uploaded_image}") if uploaded_image else request.form.get("image", "").strip() or testimonial.image
        testimonial.published = request.form.get("published") == "on"
        testimonial.sort_order = int(request.form.get("sort_order", "0") or 0)
        if not testimonial.name or not testimonial.quote or not testimonial.image:
            flash("Please complete every testimonial field.", "danger")
            return redirect(request.url)
        db.session.add(testimonial)
        db.session.commit()
        flash("Testimonial saved.", "success")
        return redirect(url_for("admin_content"))
    return render_template("admin_testimonial_form.html", testimonial=testimonial)


@app.route("/admin/testimonial/<int:testimonial_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_testimonial(testimonial_id):
    testimonial = db.session.get(Testimonial, testimonial_id)
    if testimonial is None:
        abort(404)
    db.session.delete(testimonial)
    db.session.commit()
    flash("Testimonial deleted.", "success")
    return redirect(url_for("admin_content"))


@app.route("/admin/partner/new", methods=["GET", "POST"])
@app.route("/admin/partner/<int:partner_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_partner_form(partner_id=None):
    partner = db.session.get(Partner, partner_id) if partner_id else Partner()
    if partner_id and partner is None:
        abort(404)
    if request.method == "POST":
        partner.name = request.form.get("name", "").strip()
        partner.logo = request.form.get("logo", "").strip()
        partner.caption = request.form.get("caption", "").strip()
        partner.website = request.form.get("website", "").strip()
        partner.published = request.form.get("published") == "on"
        partner.sort_order = int(request.form.get("sort_order", "0") or 0)
        if not partner.name or not partner.logo or not partner.caption:
            flash("Please complete every partner field.", "danger")
            return redirect(request.url)
        db.session.add(partner)
        db.session.commit()
        flash("Partner saved.", "success")
        return redirect(url_for("admin_content"))
    return render_template("admin_partner_form.html", partner=partner)


@app.route("/admin/partner/<int:partner_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_partner(partner_id):
    partner = db.session.get(Partner, partner_id)
    if partner is None:
        abort(404)
    db.session.delete(partner)
    db.session.commit()
    flash("Partner deleted.", "success")
    return redirect(url_for("admin_content"))


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
@admin_required
def admin_settings():
    if request.method == "POST":
        for key in DEFAULT_SETTINGS:
            set_setting(key, request.form.get(key, "").strip())
        db.session.commit()
        flash("Site settings updated.", "success")
        return redirect(url_for("admin_settings"))
    return render_template("admin_settings.html", settings=get_settings())


@app.route("/admin/messages")
@login_required
@admin_required
def admin_messages():
    conversations = get_support_conversations()
    return render_template("admin_messages.html", conversations=conversations)


@app.route("/admin/message/<int:message_id>/status", methods=["POST"])
@login_required
@admin_required
def admin_message_status(message_id):
    message = db.session.get(SupportMessage, message_id)
    if message is None:
        abort(404)
    status = request.form.get("status")
    reply = request.form.get("reply", "").strip()
    if status not in ("open", "replied", "closed"):
        flash("Choose a valid message status.", "danger")
        return redirect(url_for("admin_messages"))
    if reply:
        message.reply = reply
        message.replied_at = datetime.utcnow()
        conversation_id = message.conversation_id or f"legacy-{message.id}"
        if not message.conversation_id:
            message.conversation_id = conversation_id
        admin_entry = SupportMessage(
            full_name="HopeBridge Support",
            email=get_setting("support_email", DEFAULT_SETTINGS["support_email"]),
            phone=None,
            subject=message.subject,
            message=reply,
            conversation_id=conversation_id,
            sender="admin",
            status="replied",
        )
        db.session.add(admin_entry)
        status = "replied"
        try:
            sent = send_support_reply(message, reply)
        except Exception:
            sent = False
        flash(
            "Your reply has been saved and emailed to the client."
            if sent
            else "Your reply has been saved in the client record. Email delivery is not active yet, so please contact the client directly if an immediate response is required.",
            "success",
        )
    else:
        flash("Support message updated.", "success")
    message.status = status
    db.session.commit()
    return redirect(url_for("admin_messages"))


@app.route("/admin/proof/<filename>")
@login_required
@admin_required
def admin_view_proof(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/admin/export/users.csv")
@login_required
@admin_required
def admin_export_users():
    rows = [
        [user.id, user.full_name, user.email, user.phone or "", user.city or "", user.country or "", user.auth_provider, user.is_admin, user.created_at]
        for user in User.query.order_by(User.created_at.desc()).all()
    ]
    return csv_response("hopebridge-users.csv", rows, ["id", "full_name", "email", "phone", "city", "country", "provider", "is_admin", "created_at"])


@app.route("/admin/export/donations.csv")
@login_required
@admin_required
def admin_export_donations():
    rows = [
        [
            donation.id,
            donation.reference,
            donation.campaign.title,
            donation.donor.email if donation.donor else "",
            donation.amount,
            donation.payment_method,
            donation.payment_asset or "",
            donation.payment_network or "",
            donation.status,
            donation.created_at,
        ]
        for donation in Donation.query.order_by(Donation.created_at.desc()).all()
    ]
    return csv_response("hopebridge-donations.csv", rows, ["id", "reference", "campaign", "donor_email", "amount", "method", "asset", "network", "status", "created_at"])


@app.route("/admin/export/campaigns.csv")
@login_required
@admin_required
def admin_export_campaigns():
    rows = [
        [campaign.id, campaign.title, campaign.patient, campaign.category, campaign.organizer, campaign.location, campaign.goal, campaign.raised, campaign.verified, campaign.completed, campaign.created_at]
        for campaign in Campaign.query.order_by(Campaign.created_at.desc()).all()
    ]
    return csv_response("hopebridge-campaigns.csv", rows, ["id", "title", "patient", "category", "organizer", "location", "goal", "raised", "verified", "completed", "created_at"])


with app.app_context():
    ensure_schema()
    seed_campaigns()
    seed_site_content()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)
