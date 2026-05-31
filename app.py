import os

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
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-development-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///hopebridge.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to view your dashboard."


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


campaigns = [
    {
        "id": 1,
        "title": "Help Sarah Fight Breast Cancer",
        "category": "Breast Cancer",
        "patient": "Sarah",
        "organizer": "Sarah's Family",
        "location": "New York, USA",
        "raised": 3250,
        "goal": 5000,
        "image": "https://images.unsplash.com/photo-1544717305-2782549b5136?auto=format&fit=crop&w=900&q=80",
        "summary": "Sarah needs support for her chemotherapy treatment and recovery care.",
        "story": "Sarah is a bright 12-year-old girl diagnosed with stage 2 breast cancer. Her family needs help to continue chemotherapy and surgery.",
    },
    {
        "id": 2,
        "title": "Support David's Treatment",
        "category": "Lung Cancer",
        "patient": "David",
        "organizer": "Hope Friends",
        "location": "Chicago, USA",
        "raised": 6500,
        "goal": 10000,
        "image": "https://images.unsplash.com/photo-1582750433449-648ed127bb54?auto=format&fit=crop&w=900&q=80",
        "summary": "David is battling lung cancer and needs urgent surgery.",
        "story": "David needs support for surgery, medicine, scans, and recovery care.",
    },
    {
        "id": 3,
        "title": "Help Maria's Recovery",
        "category": "Ovarian Cancer",
        "patient": "Maria",
        "organizer": "Maria's Sister",
        "location": "Austin, USA",
        "raised": 2100,
        "goal": 4500,
        "image": "https://images.unsplash.com/photo-1550831107-1553da8c8464?auto=format&fit=crop&w=900&q=80",
        "summary": "Maria needs help for ovarian cancer treatment and recovery support.",
        "story": "Maria needs help with medication, transport, and specialist visits.",
    },
]


def format_money(value):
    return "${:,.0f}".format(value)


app.jinja_env.filters["money"] = format_money


@app.route("/")
def home():
    return render_template("index.html", campaigns=campaigns)


@app.route("/campaigns")
def campaign_list():
    return render_template("campaigns.html", campaigns=campaigns)


@app.route("/campaign/<int:campaign_id>", methods=["GET", "POST"])
def campaign_detail(campaign_id):
    campaign = next((item for item in campaigns if item["id"] == campaign_id), None)

    if campaign is None:
        return redirect(url_for("campaign_list"))

    if request.method == "POST":
        flash("Donation payments will be activated in a later step.", "success")
        return redirect(url_for("campaign_detail", campaign_id=campaign_id))

    return render_template("campaign_detail.html", campaign=campaign, donations=[])


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm", "")

        if not full_name or not email or not password:
            flash("Please complete every field.", "danger")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Your passwords do not match.", "danger")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "danger")
            return redirect(url_for("register"))

        user = User(full_name=full_name, email=email)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        remember = request.form.get("remember") == "on"
        login_user(user, remember=remember)
        flash("Your account has been created.", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user is None or not user.check_password(password):
            flash("Incorrect email or password.", "danger")
            return redirect(url_for("login"))

        login_user(user)
        flash("Welcome back to HopeBridge.", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have logged out.", "success")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    metrics = {
        "total_donations": 0,
        "campaigns_supported": 0,
        "total_raised": 0,
        "donations_received": 0,
    }

    return render_template(
        "dashboard.html",
        user=current_user,
        metrics=metrics,
        donations=[],
        campaigns=[],
    )


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)
