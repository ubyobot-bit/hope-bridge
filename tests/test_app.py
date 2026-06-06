import os
import re
import unittest
from io import BytesIO

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"

from app import Campaign, User, app, db, seed_campaigns


class HopeBridgeTestCase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            seed_campaigns()

    def register(self, email="user@example.com", phone="08010000000"):
        return self.client.post(
            "/register",
            data={
                "name": "Test User",
                "email": email,
                "phone": phone,
                "password": "Password123!",
                "confirm": "Password123!",
            },
            follow_redirects=True,
        )

    def login(self, email="user@example.com", password="Password123!"):
        return self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=True,
        )

    def test_registration_login_and_duplicate_email(self):
        response = self.register()
        self.assertIn(b"Welcome, Test User", response.data)
        self.client.get("/logout")

        duplicate = self.register(email="USER@example.com", phone="08020000000")
        self.assertIn(b"One email can only be bonded to one account", duplicate.data)

        login = self.login()
        self.assertIn(b"Welcome, Test User", login.data)

    def test_profile_update_and_unique_phone(self):
        self.register()
        self.client.get("/logout")
        self.register(email="second@example.com", phone="08020000000")
        taken = self.client.post(
            "/profile",
            data={
                "name": "Second User",
                "email": "second@example.com",
                "phone": "08010000000",
                "city": "Lagos",
                "country": "Nigeria",
                "bio": "Donor",
            },
            follow_redirects=True,
        )
        self.assertIn(b"phone number is already bonded", taken.data)

        ok = self.client.post(
            "/profile",
            data={
                "name": "Second User",
                "email": "second@example.com",
                "phone": "08030000000",
                "city": "Lagos",
                "country": "Nigeria",
                "bio": "Donor",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Profile updated", ok.data)

    def test_forgot_password_reset_flow(self):
        self.register()
        self.client.get("/logout")
        forgot = self.client.post(
            "/forgot-password",
            data={"email": "user@example.com"},
            follow_redirects=True,
        )
        self.assertIn(b"Password reset link created", forgot.data)
        with app.app_context():
            token = User.query.filter_by(email="user@example.com").first().reset_token
        reset = self.client.post(
            f"/reset-password/{token}",
            data={"password": "NewPassword123!", "confirm": "NewPassword123!"},
            follow_redirects=True,
        )
        self.assertIn(b"Password updated", reset.data)
        login = self.login(password="NewPassword123!")
        self.assertIn(b"Welcome, Test User", login.data)

    def test_campaign_creation_and_bank_donation(self):
        self.register()
        created = self.client.post(
            "/campaign/new",
            data={
                "title": "New Treatment Fund",
                "patient": "Jane",
                "category": "Medical",
                "location": "Abuja",
                "goal": "3000",
                "summary": "Treatment support",
                "story": "Jane needs treatment support.",
                "campaign_image": (BytesIO(b"fake image bytes"), "campaign.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b"Campaign created", created.data)

        with app.app_context():
            campaign = Campaign.query.filter_by(title="New Treatment Fund").first()
            campaign_id = campaign.id
            self.assertIn("/static/uploads/", campaign.image)

        receipt = self.client.post(
            f"/campaign/{campaign_id}/donate",
            data={"amount": "125", "payment_method": "bank"},
            follow_redirects=True,
        )
        self.assertIn(b"Processing payment", receipt.data)
        self.assertIn(b"Processing / Confirming", receipt.data)
        self.assertIn(b"HopeBridge Standard Bank", receipt.data)

    def test_crypto_address_rotation(self):
        with app.app_context():
            campaign_id = Campaign.query.first().id
        addresses = []
        for _ in range(4):
            response = self.client.post(
                f"/campaign/{campaign_id}/donate",
                data={
                    "amount": "25",
                    "payment_method": "crypto",
                    "asset": "USDT",
                    "network": "TRC20",
                },
                follow_redirects=True,
            )
            match = re.search(rb"THopeUsdtTrc\d+", response.data)
            self.assertIsNotNone(match)
            self.assertIn(b"Processing / Confirming", response.data)
            self.assertIn(b"create-qr-code", response.data)
            addresses.append(match.group(0))
        self.assertEqual(addresses[0], addresses[3])
        self.assertEqual(len(set(addresses[:3])), 3)

    def test_home_and_projects_sections(self):
        home = self.client.get("/")
        self.assertIn(b"Completed Projects", home.data)
        self.assertIn(b"Testimonials", home.data)
        self.assertIn(b"WHO", home.data)
        self.assertIn(b"View All Testimonials", home.data)
        self.assertIn(b"support@hopebridge.org", home.data)
        self.assertIn(b"HopeBridge Support", home.data)
        projects = self.client.get("/projects")
        self.assertIn(b"Previous Completed Projects", projects.data)
        self.assertIn(b"Emergency Treatment Bridge", projects.data)
        self.assertGreaterEqual(projects.data.count(b"project-card"), 60)
        testimonials = self.client.get("/testimonials")
        self.assertIn(b"Testimonials", testimonials.data)
        self.assertGreaterEqual(testimonials.data.count(b"testimonial-card"), 60)

    def test_about_page(self):
        response = self.client.get("/about")
        self.assertIn(b"About HopeBridge", response.data)
        self.assertIn(b"Executive Team", response.data)
        self.assertIn(b"Dr. Amara Okonkwo", response.data)
        self.assertIn(b"Trusted Partners", response.data)

    def test_social_email_bonding_fallback(self):
        response = self.client.post(
            "/auth/google",
            data={"name": "Social User", "email": "social@example.com"},
            follow_redirects=True,
        )
        self.assertIn(b"Signed in with Google", response.data)
        self.client.get("/logout")
        duplicate = self.client.post(
            "/register",
            data={
                "name": "Other User",
                "email": "social@example.com",
                "password": "Password123!",
                "confirm": "Password123!",
            },
            follow_redirects=True,
        )
        self.assertIn(b"One email can only be bonded", duplicate.data)


if __name__ == "__main__":
    unittest.main()
