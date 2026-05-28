from flask import Flask, render_template, redirect, url_for, request, flash

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-key"


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
        "story": "Sarah is a bright 12-year-old girl diagnosed with stage 2 breast cancer. Her family has spent their savings on initial treatments, but they still need help to continue chemotherapy and surgery. Any contribution, big or small, will make a meaningful difference.",
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
        "story": "David is a father, teacher, and community volunteer. His doctors recommend immediate treatment, and donations will help cover surgery, medicine, scans, and recovery support.",
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
        "story": "Maria is receiving ongoing care after a difficult diagnosis. Funds will help pay for medication, transport, specialist visits, and living expenses while she heals.",
    },
]


recent_donations = [
    {"name": "John Doe", "campaign": "Sarah's Treatment", "amount": 100, "date": "May 10, 2026"},
    {"name": "Mary Smith", "campaign": "David's Surgery", "amount": 50, "date": "May 8, 2026"},
    {"name": "Anonymous", "campaign": "Maria's Recovery", "amount": 75, "date": "May 7, 2026"},
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
        amount = request.form.get("amount", "25")
        flash(f"Thank you for choosing to donate ${amount} to {campaign['patient']}.", "success")
        return redirect(url_for("campaign_detail", campaign_id=campaign_id))

    return render_template("campaign_detail.html", campaign=campaign, donations=recent_donations)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        flash("Welcome back to HopeBridge.", "success")
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        flash("Your account has been created.", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/dashboard")
def dashboard():
    supported = [
        {"name": "Help My Father's Treatment", "raised": 2300, "goal": 4000},
        {"name": "Support My Sister", "raised": 1200, "goal": 2500},
    ]
    return render_template("dashboard.html", donations=recent_donations, campaigns=supported)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
