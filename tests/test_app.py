import os
import re
import unittest
from io import BytesIO

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"

from app import (
    COMPLETED_PROJECTS,
    TESTIMONIALS,
    Campaign,
    CompletedProject,
    CRYPTO_ADDRESS_BOOK,
    Donation,
    Partner,
    SiteSetting,
    SupportMessage,
    Testimonial,
    User,
    app,
    db,
    seed_campaigns,
    seed_site_content,
)


class HopeBridgeTestCase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            seed_campaigns()
            seed_site_content()

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

        detail = self.client.get(f"/campaign/{campaign_id}")
        self.assertIn(b"Share this campaign", detail.data)
        self.assertIn(f"/campaign/{campaign_id}".encode(), detail.data)

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
        expected = [
            b"TAZFYj4hBdNEytNRSnVAqMxfKN3wnZdgLk",
            b"TPkmQio6DCQGRQL4PKt9gh9zsbnBH3q6hQ",
            b"TAZFYj4hBdNEytNRSnVAqMxfKN3wnZdgLk",
            b"TPkmQio6DCQGRQL4PKt9gh9zsbnBH3q6hQ",
        ]
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
            match = re.search(rb"(TAZFYj4hBdNEytNRSnVAqMxfKN3wnZdgLk|TPkmQio6DCQGRQL4PKt9gh9zsbnBH3q6hQ)", response.data)
            self.assertIsNotNone(match)
            self.assertIn(b"Processing / Confirming", response.data)
            self.assertIn(b"create-qr-code", response.data)
            self.assertNotIn(b"USDT%3A", response.data)
            self.assertNotIn(b"network%3DTRC20", response.data)
            self.assertNotIn(b"amount%3D25", response.data)
            self.assertIn(b"Copy", response.data)
            self.assertIn(b"Share", response.data)
            self.assertIn(b"Scan QR code", response.data)
            self.assertIn(b"Upload Payment Proof", response.data)
            self.assertIn(b"Submit", response.data)
            self.assertNotIn(b"Leave this page", response.data)
            self.assertNotIn(b"Deposit from exchange", response.data)
            addresses.append(match.group(0))
        self.assertEqual(addresses, expected)

    def test_crypto_payment_proof_upload_is_saved(self):
        with app.app_context():
            campaign_id = Campaign.query.first().id
        receipt = self.client.post(
            f"/campaign/{campaign_id}/donate",
            data={
                "amount": "40",
                "payment_method": "crypto",
                "asset": "USDC",
                "network": "SPL",
            },
            follow_redirects=True,
        )
        with app.app_context():
            donation = Donation.query.filter_by(payment_asset="USDC", payment_network="SPL").first()
            reference = donation.reference
            self.assertIsNone(donation.proof_filename)
        self.assertIn(b"Upload Payment Proof", receipt.data)

        submitted = self.client.post(
            f"/donation/{reference}",
            data={"payment_proof": (BytesIO(b"proof bytes"), "crypto-proof.jpg")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b"Payment proof submitted", submitted.data)
        with app.app_context():
            donation = Donation.query.filter_by(reference=reference).first()
            self.assertIsNotNone(donation.proof_filename)
            self.assertIn("crypto-proof.jpg", donation.proof_filename)

    def test_uploaded_wallet_batches_are_exact(self):
        self.assertEqual(CRYPTO_ADDRESS_BOOK["BTC"]["BTC"], [
            "bc1ql45pwem9fussyr9r32n6kuz7sx0aeemtlaqpjm",
            "bc1qkffjus22ewuunu24x37le9t389ljjytpuae45m",
        ])
        self.assertEqual(CRYPTO_ADDRESS_BOOK["USDT"]["TRC20"], [
            "TAZFYj4hBdNEytNRSnVAqMxfKN3wnZdgLk",
            "TPkmQio6DCQGRQL4PKt9gh9zsbnBH3q6hQ",
        ])
        self.assertEqual(CRYPTO_ADDRESS_BOOK["USDT"]["BEP20"], [
            "0x411266e5c271d4dcdeb92228dA9f37158f46A0F8",
            "0x8D7c83424a99C5617499E2F2aDbC71B1f9751FB0",
        ])
        self.assertEqual(CRYPTO_ADDRESS_BOOK["USDT"]["ERC20"], [
            "0x411266e5c271d4dcdeb92228dA9f37158f46A0F8",
            "0x8D7c83424a99C5617499E2F2aDbC71B1f9751FB0",
        ])
        self.assertEqual(CRYPTO_ADDRESS_BOOK["USDC"]["SPL"], [
            "J9gCsf2wzt1zqSpri379Nn7jhgzvnACQzEeEkfYNU8gy",
            "2MHUxNirXDvDWQ8hafUVkwTsMvfhLTGqNPhuRqDJMgNx",
        ])

    def test_home_and_projects_sections(self):
        home = self.client.get("/")
        self.assertIn(b"Completed Projects", home.data)
        self.assertNotIn(b"Our Impact So Far", home.data)
        self.assertIn(b"Patients Helped", home.data)
        self.assertIn(b"% Funded", home.data)
        self.assertIn(b"Testimonials", home.data)
        self.assertIn(b"WHO", home.data)
        self.assertIn(b"View All Testimonials", home.data)
        self.assertIn(b"support@hopebridge.org", home.data)
        self.assertIn(b"HopeBridge Support", home.data)
        self.assertIn(b" Send</button>", home.data)
        self.assertNotIn(b"wa.me/", home.data)
        projects = self.client.get("/projects")
        self.assertIn(b"Previous Completed Projects", projects.data)
        self.assertIn(b"NGO Registration", projects.data)
        self.assertIn(b"Completed:", projects.data)
        self.assertIn(b"1,250 Families Assisted", projects.data)
        self.assertNotIn(b"View Story", projects.data)
        self.assertNotIn(b"Donor Report", projects.data)
        self.assertNotIn(b"Before &amp; After Photos", projects.data)
        self.assertIn(b"Musa Emergency Surgery Bridge", projects.data)
        self.assertGreaterEqual(projects.data.count(b"project-card"), 60)
        campaign = self.client.get("/campaign/1")
        self.assertIn(b"Recent Update", campaign.data)
        self.assertIn(b"CAMPAIGN SUMMARY", campaign.data)
        self.assertIn(b"campaignShareMessage", campaign.data)
        testimonials = self.client.get("/testimonials")
        self.assertIn(b"Testimonials", testimonials.data)
        self.assertGreaterEqual(testimonials.data.count(b"testimonial-card"), 60)

    def test_user_messages_page_uses_threaded_chat(self):
        self.register()
        response = self.client.get("/messages")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"supportThreadHistory", response.data)
        self.assertIn(b"HopeBridge Support", response.data)
        self.assertIn(
            b"Hello, a HopeBridge customer representative can help with donations, campaign verification, or payment confirmation.",
            response.data,
        )
        self.assertIn(b"Type your message", response.data)
        self.assertIn(b" Send</button>", response.data)

    def test_project_and_testimonial_content_is_unique(self):
        self.assertEqual(len(COMPLETED_PROJECTS), 60)
        self.assertEqual(len(TESTIMONIALS), 60)
        self.assertEqual(len({project["title"] for project in COMPLETED_PROJECTS}), 60)
        self.assertEqual(len({project["summary"] for project in COMPLETED_PROJECTS}), 60)
        self.assertEqual(len({project["image"] for project in COMPLETED_PROJECTS}), 60)
        self.assertEqual(len({testimonial["name"] for testimonial in TESTIMONIALS}), 60)
        self.assertEqual(len({testimonial["quote"] for testimonial in TESTIMONIALS}), 60)
        self.assertEqual(len({testimonial["image"] for testimonial in TESTIMONIALS}), 60)
        with app.app_context():
            self.assertEqual(CompletedProject.query.count(), 60)
            self.assertEqual(Testimonial.query.count(), 60)
            self.assertGreaterEqual(Partner.query.count(), 8)
            self.assertFalse(any("loremflickr.com" in project.image for project in CompletedProject.query.all()))

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

    def test_admin_backend_permissions_and_actions(self):
        self.register()
        forbidden = self.client.get("/admin")
        self.assertEqual(forbidden.status_code, 403)

        with app.app_context():
            user = User.query.filter_by(email="user@example.com").first()
            user.is_admin = True
            campaign = Campaign.query.first()
            donation = Donation(
                donor_id=user.id,
                campaign_id=campaign.id,
                amount=250,
                payment_method="bank",
                reference="HB-ADMINTEST",
            )
            db.session.add(donation)
            db.session.commit()
            campaign_id = campaign.id
            donation_id = donation.id

        dashboard = self.client.get("/admin")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Admin Dashboard", dashboard.data)
        admin_donations = self.client.get("/admin/donations")
        self.assertIn(b"Confirm", admin_donations.data)

        verified = self.client.post(
            f"/admin/campaign/{campaign_id}/verify",
            data={"verified": "true"},
            follow_redirects=True,
        )
        self.assertIn(b"verification updated", verified.data)

        completed = self.client.post(
            f"/admin/campaign/{campaign_id}/complete",
            data={"completed": "true"},
            follow_redirects=True,
        )
        self.assertIn(b"completion status updated", completed.data)

        confirmed = self.client.post(
            f"/admin/donation/{donation_id}/status",
            data={"status": "confirmed"},
            follow_redirects=True,
        )
        self.assertIn(b"marked as confirmed", confirmed.data)

        with app.app_context():
            campaign = db.session.get(Campaign, campaign_id)
            campaign_payload = {
                "title": campaign.title,
                "patient": campaign.patient,
                "category": campaign.category,
                "organizer": campaign.organizer,
                "location": campaign.location,
                "goal": str(campaign.goal),
                "sort_order": "42",
                "image": campaign.image,
                "summary": campaign.summary,
                "story": campaign.story,
                "verified": "on",
                "completed": "on",
            }

        edited_campaign = self.client.post(
            f"/admin/campaign/{campaign_id}/edit",
            data=campaign_payload,
            follow_redirects=True,
        )
        self.assertIn(b"Campaign updated", edited_campaign.data)
        self.assertIn(b"42", edited_campaign.data)

        with app.app_context():
            campaign = db.session.get(Campaign, campaign_id)
            donation = db.session.get(Donation, donation_id)
            self.assertTrue(campaign.verified)
            self.assertTrue(campaign.completed)
            self.assertEqual(campaign.sort_order, 42)
            self.assertEqual(donation.status, "confirmed")

    def make_admin(self):
        self.register()
        with app.app_context():
            user = User.query.filter_by(email="user@example.com").first()
            user.is_admin = True
            db.session.commit()

    def test_admin_content_settings_messages_and_exports(self):
        self.make_admin()
        message = self.client.post(
            "/contact",
            data={
                "name": "Visitor One",
                "email": "visitor@example.com",
                "phone": "08090000000",
                "subject": "Donation help",
                "message": "Please help me confirm my donation.",
            },
            follow_redirects=True,
        )
        self.assertIn(b"message has been sent", message.data)

        with app.app_context():
            support_message = SupportMessage.query.filter_by(email="visitor@example.com").first()
            self.assertIsNotNone(support_message)
            message_id = support_message.id

        messages = self.client.get("/admin/messages")
        self.assertIn(b"Visitor One", messages.data)
        updated_message = self.client.post(
            f"/admin/message/{message_id}/status",
            data={"status": "replied"},
            follow_redirects=True,
        )
        self.assertIn(b"Support message updated", updated_message.data)

        settings = self.client.post(
            "/admin/settings",
            data={
                "support_phone": "+2348111111111",
                "support_email": "care@hopebridge.org",
                "support_facebook": "https://facebook.com/newhopebridge",
                "support_tiktok": "https://www.tiktok.com/@newhopebridge",
                "support_whatsapp": "2348111111111",
                "bank_name": "HopeBridge Test Bank",
                "bank_account_name": "HopeBridge Test Account",
                "bank_account_number": "9990001112",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Site settings updated", settings.data)
        home = self.client.get("/")
        self.assertIn(b"care@hopebridge.org", home.data)
        self.assertIn(b"+2348111111111", home.data)

        content = self.client.get("/admin/content")
        self.assertIn(b"Manage Site Content", content.data)
        self.assertIn(b"Impact &amp; Trust Settings", content.data)
        updated_impact = self.client.post(
            "/admin/content/impact",
            data={
                "impact_icon_0": "bi-heart-pulse",
                "impact_value_0": "9,999+",
                "impact_label_0": "Lives Renewed",
                "impact_icon_1": "bi-cash-stack",
                "impact_value_1": "$500,000+",
                "impact_label_1": "Audited Giving",
                "impact_icon_2": "bi-globe2",
                "impact_value_2": "21",
                "impact_label_2": "Countries Served",
                "impact_icon_3": "bi-hospital",
                "impact_value_3": "140+",
                "impact_label_3": "Medical Cases Closed",
                "impact_icon_4": "bi-people",
                "impact_value_4": "5,400+",
                "impact_label_4": "Donors And Partners",
                "trust_icon_0": "bi-patch-check",
                "trust_title_0": "Registered oversight",
                "trust_text_0": "NGO Registration: TEST-001",
                "trust_icon_1": "bi-geo-alt",
                "trust_title_1": "Operations desk",
                "trust_text_1": "Transparent support desk",
                "trust_icon_2": "bi-shield-lock",
                "trust_title_2": "Verification process",
                "trust_text_2": "Reviewed before publication",
                "trust_icon_3": "bi-file-earmark-text",
                "trust_title_3": "Donor reporting",
                "trust_text_3": "Reports are maintained",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Impact and trust content updated", updated_impact.data)
        projects_after_impact = self.client.get("/projects")
        self.assertIn(b"9,999+", projects_after_impact.data)
        self.assertIn(b"Lives Renewed", projects_after_impact.data)
        self.assertIn(b"NGO Registration: TEST-001", projects_after_impact.data)

        with app.app_context():
            project_id = CompletedProject.query.order_by(CompletedProject.id.asc()).first().id
        edited_project = self.client.post(
            f"/admin/project/{project_id}/edit",
            data={
                "title": "Gaza Family Clinic Relief",
                "country": "Ghana",
                "amount": "$64,850",
                "summary": "Partner medics supplied wound care, medicine, clean water, and safe transport for displaced families.",
                "metrics": "2,000 Families Assisted\n22 Water Points Installed\n7,500 Relief Packs Delivered",
                "image": "/static/images/hopebridge/displaced-family-tent.jpg?project=1",
                "sort_order": "0",
                "published": "on",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Completed project saved", edited_project.data)
        projects_after_project_edit = self.client.get("/projects")
        self.assertIn(b"Ghana", projects_after_project_edit.data)
        self.assertIn(b"2,000 Families Assisted", projects_after_project_edit.data)

        created_project = self.client.post(
            "/admin/project/new",
            data={
                "title": "Backend Test Project",
                "country": "Rwanda",
                "amount": "$5,000",
                "summary": "A test project created from the admin backend.",
                "metrics": "70 Families Assisted\n14 Care Kits Delivered",
                "image": "https://example.com/project.jpg",
                "sort_order": "99",
                "published": "on",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Completed project saved", created_project.data)

        created_testimonial = self.client.post(
            "/admin/testimonial/new",
            data={
                "name": "Backend Witness",
                "role": "Donor",
                "quote": "The admin backend created this testimonial.",
                "image": "https://example.com/person.jpg",
                "sort_order": "99",
                "published": "on",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Testimonial saved", created_testimonial.data)

        created_partner = self.client.post(
            "/admin/partner/new",
            data={
                "name": "Backend Partner",
                "logo": "BP",
                "caption": "Admin-created partner",
                "website": "https://example.com",
                "sort_order": "99",
                "published": "on",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Partner saved", created_partner.data)

        users_csv = self.client.get("/admin/export/users.csv")
        donations_csv = self.client.get("/admin/export/donations.csv")
        campaigns_csv = self.client.get("/admin/export/campaigns.csv")
        self.assertEqual(users_csv.status_code, 200)
        self.assertEqual(donations_csv.status_code, 200)
        self.assertEqual(campaigns_csv.status_code, 200)
        self.assertIn(b"full_name,email", users_csv.data)
        self.assertIn(b"reference,campaign", donations_csv.data)
        self.assertIn(b"title,patient", campaigns_csv.data)

        with app.app_context():
            self.assertEqual(db.session.get(SiteSetting, "bank_name").value, "HopeBridge Test Bank")
            project = CompletedProject.query.filter_by(title="Backend Test Project").first()
            testimonial = Testimonial.query.filter_by(name="Backend Witness").first()
            self.assertIsNotNone(project)
            self.assertEqual(project.country, "Rwanda")
            self.assertIn("70 Families Assisted", project.metrics)
            self.assertIsNotNone(testimonial)
            self.assertEqual(testimonial.sort_order, 99)
            self.assertIsNotNone(Partner.query.filter_by(name="Backend Partner").first())


if __name__ == "__main__":
    unittest.main()
