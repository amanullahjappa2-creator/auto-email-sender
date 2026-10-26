"""Focused security and application smoke tests."""

import os
import re
import smtplib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


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
from models import (
    AdminGrant,
    AdminVerification,
    Contact,
    EmailLog,
    ScheduledEmail,
    SiteVisitor,
    User,
    UserSuspension,
    db,
)
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
        application.config["ADMIN_EMAILS"] = frozenset()
        application.config["PRIMARY_ADMIN_EMAIL"] = ""
        with application.app_context():
            AdminVerification.query.delete()
            AdminGrant.query.delete()
            UserSuspension.query.delete()
            EmailLog.query.delete()
            ScheduledEmail.query.delete()
            Contact.query.delete()
            SiteVisitor.query.delete()
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

    def admin_csrf_token(self, client):
        page = client.get("/admin", base_url="https://localhost")
        token = re.search(
            rb'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"',
            page.data,
        )
        if not token:
            raise AssertionError("Admin page did not render a CSRF token.")
        return token.group(1).decode()

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
        for path in (
            "/",
            "/contacts",
            "/scheduled",
            "/compose",
            "/history",
            "/search",
            "/admin",
        ):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.headers["Location"])

    def test_anonymous_visits_count_once_per_browser_per_day(self):
        first_browser = application.test_client()
        first_browser.get("/login", base_url="https://localhost")
        first_browser.get("/register", base_url="https://localhost")
        with application.app_context():
            self.assertEqual(SiteVisitor.query.count(), 1)

        second_browser = application.test_client()
        second_browser.get("/login", base_url="https://localhost")
        with application.app_context():
            self.assertEqual(SiteVisitor.query.count(), 2)

    def test_admin_dashboard_is_allowlisted_and_only_shows_aggregates(self):
        admin_id = self.create_user("admin@example.test")
        user_id = self.create_user("private-user@example.test")
        application.config["ADMIN_EMAILS"] = frozenset({"admin@example.test"})

        ordinary_client = self.authenticated_client(user_id)
        self.assertEqual(ordinary_client.get("/admin").status_code, 404)
        admin_client = self.authenticated_client(admin_id)

        with application.app_context():
            SiteVisitor.query.delete()
            today = mailflow_app.local_now().date()
            db.session.add_all(
                [
                    SiteVisitor(visit_date=today, visitor_hash="a" * 64),
                    SiteVisitor(visit_date=today, visitor_hash="b" * 64),
                    EmailLog(
                        user_id=user_id,
                        recipient="recipient@example.test",
                        subject="Confidential subject",
                        status="sent",
                    ),
                    EmailLog(
                        user_id=user_id,
                        recipient="recipient@example.test",
                        subject="Failed confidential subject",
                        status="failed",
                    ),
                    Contact(
                        user_id=user_id,
                        name="Private contact",
                        email="private-contact@example.test",
                    ),
                    ScheduledEmail(
                        user_id=user_id,
                        recipient="recipient@example.test",
                        subject="Private scheduled subject",
                        body="Private body",
                        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
                    ),
                ]
            )
            db.session.commit()

        response = admin_client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Visitors today", response.data)
        self.assertIn(b"Registered accounts", response.data)
        self.assertIn(b"Daily visitor sessions", response.data)
        self.assertIn(b"Admin panel", response.data)
        self.assertIn(b"<dd class=\"stat-num\">2</dd>", response.data)
        self.assertIn(
            b"<dt>Registered accounts</dt>\n      <dd class=\"stat-num\">2</dd>",
            response.data,
        )
        self.assertIn(
            b"<dt>Emails sent</dt>\n      <dd class=\"stat-num\">1</dd>",
            response.data,
        )
        self.assertIn(
            b"<dt>Scheduled emails</dt>\n      <dd class=\"stat-num\">1</dd>",
            response.data,
        )
        self.assertIn(
            b"<dt>Saved contacts</dt>\n      <dd class=\"stat-num\">1</dd>",
            response.data,
        )
        self.assertIn(b"private-user@example.test", response.data)
        self.assertNotIn(b"Confidential subject", response.data)
        self.assertNotIn(b"Private contact", response.data)

    def test_admin_grant_requires_email_code_and_can_be_managed_in_ui(self):
        admin_id = self.create_user("admin@example.test")
        target_id = self.create_user("new-admin@example.test")
        application.config["ADMIN_EMAILS"] = frozenset({"admin@example.test"})
        application.config["PRIMARY_ADMIN_EMAIL"] = "admin@example.test"
        client = self.authenticated_client(admin_id)
        token = self.admin_csrf_token(client)

        with patch.object(mailflow_app, "send_admin_verification_code") as send_code:
            invite_response = client.post(
                "/admin/admins/invite",
                base_url="https://localhost",
                headers={"Referer": "https://localhost/admin"},
                data={"csrf_token": token, "email": "new-admin@example.test"},
            )
        self.assertEqual(invite_response.status_code, 302)
        send_code.assert_called_once()
        self.assertEqual(send_code.call_args.args[1], "admin@example.test")
        code = send_code.call_args.args[2]
        self.assertRegex(code, r"^\d{6}$")
        with application.app_context():
            challenge = AdminVerification.query.one()
            self.assertNotIn(code, challenge.code_digest)
            self.assertFalse(challenge.consumed)

        verification_response = client.post(
            "/admin/admins/verify",
            base_url="https://localhost",
            headers={"Referer": "https://localhost/admin"},
            data={
                "csrf_token": token,
                "email": "new-admin@example.test",
                "code": code,
            },
        )
        self.assertEqual(verification_response.status_code, 302)
        with application.app_context():
            self.assertEqual(AdminGrant.query.one().email, "new-admin@example.test")
            self.assertTrue(AdminVerification.query.one().consumed)

        new_admin_client = self.authenticated_client(target_id)
        self.assertEqual(new_admin_client.get("/admin").status_code, 200)
        with application.app_context():
            grant = AdminGrant.query.one()
            grant_id = grant.id
        revoke_response = client.post(
            f"/admin/admins/{grant_id}/revoke",
            base_url="https://localhost",
            headers={"Referer": "https://localhost/admin"},
            data={"csrf_token": token},
        )
        self.assertEqual(revoke_response.status_code, 302)
        self.assertEqual(new_admin_client.get("/admin").status_code, 404)

    def test_admin_can_suspend_and_reactivate_non_admin_accounts(self):
        admin_id = self.create_user("admin@example.test")
        target_id = self.create_user("user@example.test")
        application.config["ADMIN_EMAILS"] = frozenset({"admin@example.test"})
        admin_client = self.authenticated_client(admin_id)
        target_client = self.authenticated_client(target_id)
        token = self.admin_csrf_token(admin_client)

        suspended = admin_client.post(
            f"/admin/users/{target_id}/suspension",
            base_url="https://localhost",
            headers={"Referer": "https://localhost/admin"},
            data={"csrf_token": token, "action": "suspend"},
        )
        self.assertEqual(suspended.status_code, 302)
        self.assertEqual(target_client.get("/", base_url="https://localhost").status_code, 302)
        with application.app_context():
            with self.assertRaisesRegex(ValueError, "suspended"):
                mailflow_app.send_compose_emails(
                    target_id,
                    ["recipient@example.test"],
                    "Test",
                    "Body",
                )

        reactivated = admin_client.post(
            f"/admin/users/{target_id}/suspension",
            base_url="https://localhost",
            headers={"Referer": "https://localhost/admin"},
            data={"csrf_token": token, "action": "reactivate"},
        )
        self.assertEqual(reactivated.status_code, 302)
        self.assertEqual(target_client.get("/", base_url="https://localhost").status_code, 200)

    def test_admin_can_search_and_page_through_all_registered_accounts(self):
        admin_id = self.create_user("admin@example.test")
        application.config["ADMIN_EMAILS"] = frozenset({"admin@example.test"})
        with application.app_context():
            db.session.add_all(
                [
                    User(
                        full_name=f"Directory Member {index:03d}",
                        email=f"member-{index:03d}@example.test",
                        password_hash="test-only-unused-hash",
                    )
                    for index in range(51)
                ]
            )
            db.session.commit()

        client = self.authenticated_client(admin_id)
        first_page = client.get("/admin")
        self.assertEqual(first_page.status_code, 200)
        self.assertIn(b"52 registered account(s)", first_page.data)
        self.assertIn(b"Page 1 / 2", first_page.data)
        self.assertNotIn(b"member-000@example.test", first_page.data)

        second_page = client.get("/admin?page=2")
        self.assertEqual(second_page.status_code, 200)
        self.assertIn(b"member-000@example.test", second_page.data)

        search_result = client.get("/admin?q=member-050")
        self.assertEqual(search_result.status_code, 200)
        self.assertIn(b"1 matching account(s)", search_result.data)
        self.assertIn(b"member-050@example.test", search_result.data)
        self.assertNotIn(b"member-049@example.test", search_result.data)

    def test_admin_verification_code_locks_after_five_wrong_attempts(self):
        admin_id = self.create_user("admin@example.test")
        self.create_user("target@example.test")
        application.config["ADMIN_EMAILS"] = frozenset({"admin@example.test"})
        application.config["PRIMARY_ADMIN_EMAIL"] = "admin@example.test"
        client = self.authenticated_client(admin_id)
        token = self.admin_csrf_token(client)

        with patch.object(mailflow_app, "send_admin_verification_code"):
            sent = client.post(
                "/admin/admins/invite",
                base_url="https://localhost",
                headers={"Referer": "https://localhost/admin"},
                data={"csrf_token": token, "email": "target@example.test"},
            )
        self.assertEqual(sent.status_code, 302)

        for _ in range(mailflow_app.ADMIN_CODE_MAX_ATTEMPTS):
            response = client.post(
                "/admin/admins/verify",
                base_url="https://localhost",
                headers={"Referer": "https://localhost/admin"},
                data={
                    "csrf_token": token,
                    "email": "target@example.test",
                    "code": "000000",
                },
            )
            self.assertEqual(response.status_code, 302)

        with application.app_context():
            challenge = AdminVerification.query.one()
            self.assertTrue(challenge.consumed)
            self.assertEqual(challenge.attempts, mailflow_app.ADMIN_CODE_MAX_ATTEMPTS)
            self.assertEqual(AdminGrant.query.count(), 0)

    def test_favicon_and_dashboard_stat_icons_render(self):
        login_page = application.test_client().get("/login")
        self.assertIn(b'rel="icon"', login_page.data)

        favicon = application.test_client().get("/static/favicon.svg")
        self.assertEqual(favicon.status_code, 200)
        self.assertIn(b"<svg", favicon.data)
        favicon.close()

        user_id = self.create_user("dashboard@example.test")
        dashboard = self.authenticated_client(user_id).get("/")
        self.assertEqual(dashboard.status_code, 200)
        for icon in (b"i-send", b"i-clock", b"i-users", b"i-alert"):
            with self.subTest(icon=icon):
                self.assertIn(icon, dashboard.data)

    def test_dashboard_logout_button_logs_user_out(self):
        user_id = self.create_user("dashboard-logout@example.test")
        client = self.authenticated_client(user_id)
        dashboard = client.get("/", base_url="https://localhost")

        self.assertIn(b' action="/logout"', dashboard.data)
        self.assertIn(b"Log out", dashboard.data)
        token = re.search(
            rb'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"',
            dashboard.data,
        )
        self.assertIsNotNone(token)
        response = client.post(
            "/logout",
            base_url="https://localhost",
            headers={"Referer": "https://localhost/"},
            data={"csrf_token": token.group(1).decode()},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))
        self.assertEqual(client.get("/", base_url="https://localhost").status_code, 302)

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

    def test_search_is_scoped_and_contact_result_prefills_compose(self):
        first_id = self.create_user("search-first@example.test")
        second_id = self.create_user("search-second@example.test")
        with application.app_context():
            first_contact = Contact(
                user_id=first_id,
                name="Needle Contact",
                email="needle-contact@example.test",
            )
            db.session.add_all(
                [
                    first_contact,
                    Contact(
                        user_id=second_id,
                        name="Needle Private Contact",
                        email="private-needle@example.test",
                    ),
                    EmailLog(
                        user_id=first_id,
                        recipient="recipient@example.test",
                        subject="Needle project update",
                        status="sent",
                    ),
                    EmailLog(
                        user_id=second_id,
                        recipient="private@example.test",
                        subject="Needle private email",
                        status="sent",
                    ),
                    ScheduledEmail(
                        user_id=first_id,
                        recipient="scheduled@example.test",
                        subject="Needle scheduled message",
                        body="Private schedule body",
                        scheduled_for=datetime.now(timezone.utc),
                    ),
                    EmailTemplate(
                        user_id=first_id,
                        name="Needle template",
                        subject="Welcome",
                        body="A reusable message",
                    ),
                    EmailTemplate(
                        user_id=second_id,
                        name="Needle private template",
                        subject="Private",
                        body="Not for this user",
                    ),
                ]
            )
            db.session.commit()
            first_contact_id = first_contact.id

        client = self.authenticated_client(first_id)
        response = client.get("/search?q=needle", base_url="https://localhost")
        self.assertEqual(response.status_code, 200)
        for own_result in (
            b"Needle Contact",
            b"Needle project update",
            b"Needle scheduled message",
            b"Needle template",
        ):
            with self.subTest(result=own_result):
                self.assertIn(own_result, response.data)
        for private_result in (
            b"Needle Private Contact",
            b"Needle private email",
            b"Needle private template",
        ):
            with self.subTest(result=private_result):
                self.assertNotIn(private_result, response.data)

        literal_wildcard = client.get("/search?q=%25", base_url="https://localhost")
        self.assertIn(b"No matches found for", literal_wildcard.data)
        self.assertNotIn(b"Searchable Contact", literal_wildcard.data)

        compose_response = client.get(
            f"/compose?contact={first_contact_id}",
            base_url="https://localhost",
        )
        self.assertEqual(compose_response.status_code, 200)
        self.assertIn(b"needle-contact@example.test", compose_response.data)

        with application.app_context():
            private_contact_id = (
                Contact.query.filter_by(user_id=second_id).one().id
            )
        private_compose_response = client.get(
            f"/compose?contact={private_contact_id}",
            base_url="https://localhost",
        )
        self.assertNotIn(b"private-needle@example.test", private_compose_response.data)

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

    def test_smtp_falls_back_to_starttls_when_ssl_connect_fails(self):
        class FakeServer:
            def __init__(self):
                self.started_tls = False
                self.logged_in = False
                self.ehlo_calls = 0

            def ehlo(self):
                self.ehlo_calls += 1

            def has_extn(self, extension):
                return extension == "STARTTLS"

            def starttls(self, context=None):
                self.started_tls = True

            def login(self, username, password):
                self.logged_in = True

            def quit(self):
                pass

        starttls_server = FakeServer()

        with patch.object(
            mailflow_app.smtplib,
            "SMTP_SSL",
            side_effect=OSError("SSL unavailable"),
        ), patch.object(
            mailflow_app.smtplib,
            "SMTP",
            return_value=starttls_server,
        ) as smtp_factory:
            returned = mailflow_app.open_smtp_connection(
                "sender@example.test",
                "secret",
                "smtp.example.test",
                587,
            )

        self.assertIs(returned, starttls_server)
        self.assertTrue(starttls_server.started_tls)
        self.assertTrue(starttls_server.logged_in)
        smtp_factory.assert_called_once_with("smtp.example.test", 587, timeout=20)

    def test_smtp_does_not_send_credentials_without_starttls(self):
        class FakeServer:
            login_called = False
            quit_called = False

            def ehlo(self):
                pass

            def has_extn(self, extension):
                return False

            def login(self, username, password):
                self.login_called = True

            def quit(self):
                self.quit_called = True

        server = FakeServer()
        with patch.object(
            mailflow_app.smtplib,
            "SMTP_SSL",
            side_effect=OSError("SSL unavailable"),
        ), patch.object(mailflow_app.smtplib, "SMTP", return_value=server):
            with self.assertRaises(smtplib.SMTPNotSupportedError):
                mailflow_app.open_smtp_connection(
                    "sender@example.test",
                    "secret",
                    "smtp.example.test",
                    587,
                )

        self.assertFalse(server.login_called)
        self.assertTrue(server.quit_called)

    def test_sending_stops_after_smtp_connection_is_lost(self):
        class DisconnectedServer:
            send_calls = 0

            def send_message(self, message):
                self.send_calls += 1
                raise smtplib.SMTPServerDisconnected("connection lost")

            def quit(self):
                pass

        user_id = self.create_user("sender@example.test")
        server = DisconnectedServer()
        with application.app_context():
            user = db.session.get(User, user_id)
            user.mail_address = "sender@example.test"
            user.encrypted_app_password = "encrypted"
            user.smtp_host = "smtp.example.test"
            user.smtp_port = 465
            db.session.commit()

            with patch.object(mailflow_app, "decrypt_secret", return_value="secret"), patch.object(
                mailflow_app,
                "open_smtp_connection",
                return_value=server,
            ):
                results = mailflow_app.send_compose_emails(
                    user_id,
                    [
                        "first@example.test",
                        "second@example.test",
                        "third@example.test",
                    ],
                    "Subject",
                    "Body",
                )

            self.assertEqual(
                results,
                [
                    ("first@example.test", "failed"),
                    ("second@example.test", "failed"),
                    ("third@example.test", "failed"),
                ],
            )
            self.assertEqual(server.send_calls, 1)
            self.assertEqual(
                EmailLog.query.filter_by(user_id=user_id, status="failed").count(),
                3,
            )

    def test_scheduler_processes_due_email_and_leaves_future_email_queued(self):
        user_id = self.create_user("scheduled-sender@example.test")
        now = datetime.now(timezone.utc)
        with application.app_context():
            due_schedule = ScheduledEmail(
                user_id=user_id,
                recipient="due@example.test",
                subject="Due subject",
                body="Due message",
                scheduled_for=now - timedelta(minutes=1),
            )
            future_schedule = ScheduledEmail(
                user_id=user_id,
                recipient="future@example.test",
                subject="Future subject",
                body="Future message",
                scheduled_for=now + timedelta(minutes=1),
            )
            db.session.add_all([due_schedule, future_schedule])
            db.session.commit()
            due_id = due_schedule.id
            future_id = future_schedule.id

            with patch.object(
                mailflow_app,
                "send_compose_emails",
                return_value=[("due@example.test", "sent")],
            ) as send:
                processed = mailflow_app.process_due_schedules()

            self.assertEqual(processed, 1)
            send.assert_called_once_with(
                user_id,
                ["due@example.test"],
                "Due subject",
                "Due message",
            )
            self.assertEqual(
                db.session.get(ScheduledEmail, due_id).status,
                "sent",
            )
            self.assertEqual(
                db.session.get(ScheduledEmail, future_id).status,
                "scheduled",
            )

    def test_scheduler_marks_unexpected_delivery_error_failed_and_continues(self):
        user_id = self.create_user("scheduler-errors@example.test")
        now = datetime.now(timezone.utc)
        with application.app_context():
            failed_schedule = ScheduledEmail(
                user_id=user_id,
                recipient="first@example.test",
                subject="First subject",
                body="First message",
                scheduled_for=now - timedelta(minutes=2),
            )
            succeeding_schedule = ScheduledEmail(
                user_id=user_id,
                recipient="second@example.test",
                subject="Second subject",
                body="Second message",
                scheduled_for=now - timedelta(minutes=1),
            )
            db.session.add_all([failed_schedule, succeeding_schedule])
            db.session.commit()
            failed_id = failed_schedule.id
            succeeding_id = succeeding_schedule.id

            with patch.object(
                mailflow_app,
                "send_compose_emails",
                side_effect=[
                    RuntimeError("unexpected delivery failure"),
                    [("second@example.test", "sent")],
                ],
            ) as send:
                processed = mailflow_app.process_due_schedules()

            self.assertEqual(processed, 2)
            self.assertEqual(send.call_count, 2)
            failed = db.session.get(ScheduledEmail, failed_id)
            self.assertEqual(failed.status, "failed")
            self.assertIn("outcome could not be confirmed", failed.error_message)
            succeeding = db.session.get(ScheduledEmail, succeeding_id)
            self.assertEqual(succeeding.status, "sent")

    def test_one_shot_scheduler_processes_one_batch_and_returns_count(self):
        with patch.object(
            mailflow_app,
            "process_due_schedules",
            return_value=3,
        ) as process:
            with patch("builtins.print") as print_output:
                processed = mailflow_app.run_scheduler_once()

        self.assertEqual(processed, 3)
        process.assert_called_once_with()
        print_output.assert_called_once_with("Processed 3 scheduled email(s).")

    def test_compose_accepts_display_name_and_email_recipient_format(self):
        recipients, errors = mailflow_app.check_compose(
            {
                "recipient": "Test User <hello@example.test>, second@example.test",
                "subject": "Hello",
                "body": "Message body",
            }
        )
        self.assertEqual(recipients, ["hello@example.test", "second@example.test"])
        self.assertEqual(errors, [])

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
