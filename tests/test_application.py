"""Focused security and application smoke tests."""

import os
import re
import tempfile
import unittest
from pathlib import Path


_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="mailflow-tests-")
_ENVIRONMENT = {
    name: os.environ.get(name)
    for name in (
        "DATABASE_URL",
        "FLASK_SECRET_KEY",
        "MAIL_SETTINGS_ENCRYPTION_KEY",
        "COOKIE_SECURE",
    )
}
_DATABASE_PATH = Path(_TEST_DIRECTORY.name) / "mailflow-test.db"

os.environ["DATABASE_URL"] = f"sqlite:///{_DATABASE_PATH.as_posix()}"
os.environ["FLASK_SECRET_KEY"] = "test-only-secret-key-at-least-32-characters"
os.environ["MAIL_SETTINGS_ENCRYPTION_KEY"] = (
    "0Gg7Q_1-qm5DYT6fhFBso7luj1BTsG6jYW7Tj4k1oQw="
)
os.environ["COOKIE_SECURE"] = "1"

import app as mailflow_app
from add_sample_templates import SAMPLE_TEMPLATES, add_sample_templates
from models import Contact, EmailLog, User, db
from template_models import EmailTemplate

application = mailflow_app.app
application.config.update(TESTING=True)


def setUpModule():
    with application.app_context():
        db.create_all()


def tearDownModule():
    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    _TEST_DIRECTORY.cleanup()
    for name, value in _ENVIRONMENT.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


class ApplicationSecurityTests(unittest.TestCase):
    def setUp(self):
        with application.app_context():
            EmailLog.query.delete()
            Contact.query.delete()
            EmailTemplate.query.delete()
            User.query.delete()
            db.session.commit()

    def create_user(self, email):
        with application.app_context():
            user = User(full_name="Test User", email=email)
            user.set_password("test-password")
            db.session.add(user)
            db.session.commit()
            return user.id

    def authenticated_client(self, user_id):
        client = application.test_client()
        with application.app_context():
            user = db.session.get(User, user_id)
            email = user.email
        page = client.get("/login", base_url="https://localhost")
        token = re.search(
            rb'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"',
            page.data,
        )
        response = client.post(
            "/login",
            base_url="https://localhost",
            headers={"Referer": "https://localhost/login"},
            data={
                "csrf_token": token.group(1).decode(),
                "email": email,
                "password": "test-password",
            },
        )
        if response.status_code != 302:
            raise AssertionError(f"Test user login failed: {response.status_code}")
        return client

    def test_private_and_source_files_are_not_served(self):
        client = application.test_client()
        protected_paths = (
            "/.env",
            "/.env.example",
            "/instance/mailflow.db",
            "/recipients.csv",
            "/config.py",
            "/models.py",
            "/security.py",
            "/.git/config",
        )
        for path in protected_paths:
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)

    def test_authenticated_pages_require_login(self):
        client = application.test_client()
        for path in ("/", "/contacts", "/scheduled", "/compose", "/history"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.headers["Location"])

    def test_login_rejects_posts_without_csrf_token(self):
        response = application.test_client().post(
            "/login",
            data={"email": "nobody@example.test", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 400)

    def test_security_headers_are_present(self):
        response = application.test_client().get("/login", base_url="https://localhost")
        for header in (
            "Content-Security-Policy",
            "Permissions-Policy",
            "Cross-Origin-Opener-Policy",
            "Cross-Origin-Resource-Policy",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Strict-Transport-Security",
        ):
            with self.subTest(header=header):
                self.assertTrue(response.headers.get(header))

    def test_contacts_and_history_are_scoped_to_signed_in_user(self):
        first_id = self.create_user("first@example.test")
        second_id = self.create_user("second@example.test")
        with application.app_context():
            db.session.add_all(
                [
                    Contact(user_id=first_id, name="First", email="first-contact@example.test"),
                    Contact(user_id=second_id, name="Second", email="second-contact@example.test"),
                    EmailLog(
                        user_id=first_id,
                        recipient="first-recipient@example.test",
                        subject="First user's email",
                        status="sent",
                    ),
                    EmailLog(
                        user_id=second_id,
                        recipient="second-recipient@example.test",
                        subject="Second user's email",
                        status="sent",
                    ),
                ]
            )
            db.session.commit()

        client = self.authenticated_client(first_id)
        contacts = client.get("/contacts", base_url="https://localhost")
        history = client.get("/history", base_url="https://localhost")
        self.assertEqual(contacts.status_code, 200, contacts.headers.get("Location"))
        self.assertEqual(history.status_code, 200, history.headers.get("Location"))
        self.assertIn(b"first-contact@example.test", contacts.data)
        self.assertNotIn(b"second-contact@example.test", contacts.data)
        self.assertIn(b"first-recipient@example.test", history.data)
        self.assertNotIn(b"second-recipient@example.test", history.data)

    def test_login_cookie_uses_secure_flags(self):
        user_id = self.create_user("login@example.test")
        client = application.test_client()
        page = client.get("/login", base_url="https://localhost")
        token = re.search(
            rb'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"',
            page.data,
        )
        self.assertIsNotNone(token)
        response = client.post(
            "/login",
            base_url="https://localhost",
            headers={"Referer": "https://localhost/login"},
            data={
                "csrf_token": token.group(1).decode(),
                "email": "login@example.test",
                "password": "test-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIsInstance(user_id, int)
        self.assertTrue(
            any(
                cookie.startswith("session=")
                and "Secure" in cookie
                and "HttpOnly" in cookie
                and "SameSite=Lax" in cookie
                for cookie in response.headers.getlist("Set-Cookie")
            )
        )

    def test_sample_templates_are_detailed_and_refresh_existing_samples(self):
        user_id = self.create_user("templates@example.test")
        self.assertEqual(len(SAMPLE_TEMPLATES), 10)
        for template in SAMPLE_TEMPLATES:
            with self.subTest(template=template["name"]):
                self.assertGreaterEqual(len(template["body"]), 300)

        with application.app_context():
            first_template = SAMPLE_TEMPLATES[0]
            db.session.add(
                EmailTemplate(
                    user_id=user_id,
                    name=first_template["name"],
                    subject=first_template["subject"],
                    body=first_template["legacy_body"],
                )
            )
            db.session.commit()

        add_sample_templates()

        with application.app_context():
            saved_templates = EmailTemplate.query.filter_by(user_id=user_id).all()
            self.assertEqual(len(saved_templates), 10)
            refreshed = EmailTemplate.query.filter_by(
                user_id=user_id,
                name=SAMPLE_TEMPLATES[0]["name"],
            ).one()
            self.assertEqual(refreshed.subject, SAMPLE_TEMPLATES[0]["subject"])
            self.assertEqual(refreshed.body, SAMPLE_TEMPLATES[0]["body"])

        with application.app_context():
            refreshed = EmailTemplate.query.filter_by(
                user_id=user_id,
                name=SAMPLE_TEMPLATES[0]["name"],
            ).one()
            refreshed.body = "A user-edited version that must be preserved."
            db.session.commit()

        add_sample_templates()

        with application.app_context():
            self.assertEqual(EmailTemplate.query.filter_by(user_id=user_id).count(), 10)
            self.assertEqual(
                EmailTemplate.query.filter_by(
                    user_id=user_id,
                    name=SAMPLE_TEMPLATES[0]["name"],
                ).one().body,
                "A user-edited version that must be preserved.",
            )


if __name__ == "__main__":
    unittest.main()
