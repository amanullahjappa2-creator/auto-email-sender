
"""MailFlow Studio - multi-user Flask application."""

import csv
import hashlib
import hmac
import io
import os
import re
import secrets
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import BASE_DIR, DATABASE_PATH, INSTANCE_DIR, Config
from models import (
    AdminGrant,
    AdminVerification,
    Contact,
    db,
    EmailLog,
    ScheduledEmail,
    SiteVisitor,
    User,
    UserSuspension,
)
from security import encrypt_secret, decrypt_secret
from compose_tools import (
    ACCEPT_ATTRIBUTE,
    ALLOWED_LABEL,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    add_files,
    cleanup_old_drafts,
    delete_draft,
    delete_files,
    draft_dir,
    extract_addresses,
    format_size,
    is_valid_draft_id,
    list_files,
    new_draft_id,
    read_address_file,
    read_attachments,
)
from template_models import EmailTemplate


# Load local environment settings before initializing the application.
load_dotenv(BASE_DIR / ".env")
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
if os.name == "posix":
    INSTANCE_DIR.chmod(0o700)

app = Flask(__name__)
app.config.from_object(Config)

# Total request size limit. The attachment rules themselves (file count,
# 10 MB total, allowed types) are enforced in compose_tools.py.
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
db.init_app(app)
CSRFProtect(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"
login_manager.session_protection = app.config["SESSION_PROTECTION"]
login_manager.init_app(app)

MAX_RECIPIENTS = 120
MAX_SUBJECT = 200
MAX_BODY = 20_000
MAX_RECIPIENT_FIELD = 5_000
MAX_TEMPLATES = 50
MAX_TEMPLATE_NAME = 80
SITE_VISITOR_SESSION_KEY = "_site_visitor_id"
SITE_VISITOR_RETENTION_DAYS = 90
ADMIN_CODE_TTL_SECONDS = 10 * 60
ADMIN_CODE_RESEND_SECONDS = 60
ADMIN_CODE_MAX_ATTEMPTS = 5

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


@login_manager.user_loader
def load_user(user_id):
    """Load the authenticated user from the database."""
    try:
        user = db.session.get(User, int(user_id))
        if user and db.session.get(UserSuspension, user.id):
            return None
        return user
    except (TypeError, ValueError):
        return None


def admin_email_allowlist():
    """Combine environment bootstrap admins and verified database grants."""
    granted_emails = db.session.query(AdminGrant.email).all()
    return app.config["ADMIN_EMAILS"] | {
        email.casefold() for (email,) in granted_emails
    }


def is_admin_user():
    """Check whether the current account is explicitly allowlisted."""
    return (
        current_user.is_authenticated
        and current_user.email.casefold() in admin_email_allowlist()
    )


def require_admin():
    if not is_admin_user():
        abort(404)


def admin_code_digest(admin_user_id, target_email, code):
    payload = f"admin-invite:{admin_user_id}:{target_email}:{code}"
    return hmac.new(
        app.config["SECRET_KEY"].encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()


def open_smtp_connection(sender_address, password, smtp_host, smtp_port):
    """Open a mail server connection using SSL first and STARTTLS as fallback."""
    try:
        server = smtplib.SMTP_SSL(
            smtp_host,
            smtp_port,
            context=ssl.create_default_context(),
            timeout=20,
        )
    except (OSError, smtplib.SMTPException):
        server = None
    else:
        try:
            server.login(sender_address, password)
            return server
        except (OSError, smtplib.SMTPException):
            try:
                server.quit()
            except Exception:
                pass
            raise

    server = None
    try:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=20)
        server.ehlo()
        if not server.has_extn("STARTTLS"):
            raise smtplib.SMTPNotSupportedError(
                "The SMTP server does not support STARTTLS."
            )
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        server.login(sender_address, password)
        return server
    except (OSError, smtplib.SMTPException):
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass
        raise


def send_admin_verification_code(admin_user, recipient_email, code):
    """Send an admin-grant code to the configured primary admin."""
    if not admin_user.mail_address or not admin_user.encrypted_app_password:
        raise ValueError("Configure the primary admin's SMTP settings first.")
    if not validate_email_address(admin_user.mail_address):
        raise ValueError("The primary admin's configured sender address is invalid.")
    if (
        not admin_user.smtp_host
        or not isinstance(admin_user.smtp_port, int)
        or not 1 <= admin_user.smtp_port <= 65535
    ):
        raise ValueError("The primary admin's SMTP configuration is invalid.")

    password = decrypt_secret(admin_user.encrypted_app_password)
    message = EmailMessage()
    message["From"] = admin_user.mail_address
    message["To"] = recipient_email
    message["Subject"] = "MailFlow admin access verification"
    message.set_content(
        "A request was made to grant administrator access to a MailFlow account.\n\n"
        f"Your verification code is: {code}\n\n"
        "This code expires in 10 minutes and can only be used once. "
        "If you did not request this, ignore this email."
    )

    with open_smtp_connection(
        admin_user.mail_address,
        password,
        admin_user.smtp_host,
        admin_user.smtp_port,
    ) as server:
        refused = server.send_message(message)
    if recipient_email in refused:
        raise RuntimeError("SMTP server refused the admin verification email.")


@app.context_processor
def shared_template_context():
    """Provide information for the existing application layout."""
    name = (
        current_user.full_name
        if current_user.is_authenticated
        else "Guest"
    )
    return {
        "full_name": name,
        "initial": name[:1].upper(),
        "year": local_now().year,
        "is_admin": is_admin_user(),
    }


@app.after_request
def record_site_visit(response):
    """Count successful HTML page visits without storing IP or account data."""
    if (
        request.method != "GET"
        or request.endpoint in {"static", "admin_dashboard"}
        or not 200 <= response.status_code < 300
        or response.mimetype != "text/html"
    ):
        return response

    visitor_id = session.get(SITE_VISITOR_SESSION_KEY)
    if visitor_id is None:
        visitor_id = secrets.token_urlsafe(32)
        session[SITE_VISITOR_SESSION_KEY] = visitor_id

    visit_date = local_now().date()
    visitor_hash = hmac.new(
        app.config["SECRET_KEY"].encode(),
        f"{visit_date.isoformat()}:{visitor_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    try:
        existing_visit = SiteVisitor.query.filter_by(
            visit_date=visit_date,
            visitor_hash=visitor_hash,
        ).first()
        if existing_visit is None:
            db.session.add(
                SiteVisitor(
                    visit_date=visit_date,
                    visitor_hash=visitor_hash,
                )
            )
            db.session.query(SiteVisitor).filter(
                SiteVisitor.visit_date
                < visit_date - timedelta(days=SITE_VISITOR_RETENTION_DAYS)
            ).delete(synchronize_session=False)
            db.session.commit()
    except IntegrityError:
        db.session.rollback()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not record anonymous site visit.")

    return response


@app.after_request
def add_security_headers(response):
    """Add browser security headers."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.errorhandler(413)
def request_too_large(_error):
    return "The uploaded request is too large.", 413


# ---------------- Time zone ----------------
# Every date and time the app shows uses this one time zone, so the greeting,
# the postmark and the chart never depend on the computer's own clock settings.
# Change it in one place (or set APP_TIMEZONE in your environment).
APP_TIMEZONE_NAME = os.environ.get("APP_TIMEZONE", "Asia/Karachi")

# Set this to False ONLY if models.py saves EmailLog.sent_at with
# datetime.now (local time) instead of datetime.utcnow / UTC.
STORED_TIMES_ARE_UTC = True


def _load_timezone(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # Windows has no time zone database until `pip install tzdata`.
        # Pakistan has no daylight saving time, so a fixed +5 hours is exact.
        if name == "Asia/Karachi":
            return timezone(timedelta(hours=5), "PKT")
        return timezone.utc


APP_TZ = _load_timezone(APP_TIMEZONE_NAME)


def local_now():
    """The current time in the app's time zone."""
    return datetime.now(APP_TZ)


def to_local(moment):
    """Convert a time saved in the database to the app's time zone."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        source = timezone.utc if STORED_TIMES_ARE_UTC else APP_TZ
        moment = moment.replace(tzinfo=source)
    return moment.astimezone(APP_TZ)


@app.template_filter("local_time")
def local_time_filter(moment, pattern="%d %b %Y, %I:%M %p"):
    """Use in a template: {{ log.sent_at|local_time }}"""
    local = to_local(moment)
    return local.strftime(pattern) if local else ""


def greeting_for(now):
    if now.hour < 12:
        return "Good morning"
    if now.hour < 18:
        return "Good afternoon"
    return "Good evening"


def first_name_of(user):
    """Return the first word of the user's full name, or "" if there is none."""
    parts = (getattr(user, "full_name", "") or "").split()
    return parts[0] if parts else ""


def build_week(logs, now):
    """Count one user's emails per day for the last 7 days (today included).

    `logs` must already belong to a single user. The bar sizes are plain
    numbers because the Content-Security-Policy blocks inline CSS, so the
    dashboard draws the chart as SVG shapes with these numbers.
    """
    today = now.date()
    first_day = today - timedelta(days=6)

    days = []
    by_date = {}
    for offset in range(7):
        day = first_day + timedelta(days=offset)
        entry = {
            "label": day.strftime("%a"),
            "full": day.strftime("%a %d %b"),
            "is_today": day == today,
            "sent": 0,
            "failed": 0,
            "total": 0,
        }
        days.append(entry)
        by_date[day] = entry

    for log in logs:
        when = to_local(getattr(log, "sent_at", None))
        if when is None:
            continue
        entry = by_date.get(when.date())
        if entry is None:
            continue
        if log.status == "sent":
            entry["sent"] += 1
        elif log.status == "failed":
            entry["failed"] += 1

    for entry in days:
        entry["total"] = entry["sent"] + entry["failed"]

    peak = max((entry["total"] for entry in days), default=0)
    chart_height = 100.0
    unit = 90.0 / peak if peak else 0.0  # leaves room for the minimum bar heights
    min_bar = 4.0                        # so a single email is still visible

    for index, entry in enumerate(days):
        sent_h = max(entry["sent"] * unit, min_bar) if entry["sent"] else 0.0
        failed_h = max(entry["failed"] * unit, min_bar) if entry["failed"] else 0.0
        entry["x"] = index * 10 + 3.4
        entry["sent_h"] = round(sent_h, 1)
        entry["sent_y"] = round(chart_height - sent_h, 1)
        entry["failed_h"] = round(failed_h, 1)
        entry["failed_y"] = round(chart_height - sent_h - failed_h, 1)

    return {"days": days, "total": sum(entry["total"] for entry in days)}


def accepted_rate(sent, failed):
    """Percent of attempted emails that the mail server accepted, or None."""
    attempted = sent + failed
    if attempted == 0:
        return None
    return round(sent * 100 / attempted)


def clock_parts(now):
    """Date and time text for the dashboard header (no leading zeros)."""
    return {
        "date": f"{now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}",
        "time": now.strftime("%I:%M %p").lstrip("0"),
        "zone": now.tzname() or APP_TIMEZONE_NAME,
    }


def setup_status(user, total_emails):
    """Which getting-started steps this user has finished.

    Only yes/no answers are returned. The saved App Password itself is
    never read out or passed to a template.
    """
    return {
        "account_ready": bool(user.mail_address and user.encrypted_app_password),
        "mail_address": user.mail_address or "",
        "has_emails": total_emails > 0,
    }


def validate_email_address(address):
    address = address.strip()
    return (
        len(address) <= 254
        and EMAIL_RE.fullmatch(address) is not None
    )


def normalize_recipient(address):
    """Accept common "Name <email@example.com>" input and normalize whitespace."""
    candidate = (address or "").strip()
    if not candidate:
        return ""

    match = re.search(r"<([^<>]+)>", candidate)
    if match:
        candidate = match.group(1).strip()
    return candidate


def check_compose(form):
    """Validate the recipients, subject and message."""
    errors = []
    recipients = []

    raw = form["recipient"]

    if not raw:
        errors.append(("recipient", "Enter at least one email address."))
    elif len(raw) > MAX_RECIPIENT_FIELD:
        errors.append(("recipient", "The recipient list is too long."))
    else:
        seen = set()

        for item in re.split(r"[,;\n]+", raw):
            address = normalize_recipient(item)
            if not address:
                continue

            if not validate_email_address(address):
                errors.append(
                    ("recipient", f'"{address[:60]}" is not a valid email address.')
                )
                break

            key = address.casefold()
            if key not in seen:
                seen.add(key)
                recipients.append(address)

        if not errors and not recipients:
            errors.append(("recipient", "Enter at least one email address."))

        if not errors and len(recipients) > MAX_RECIPIENTS:
            errors.append(
                ("recipient", f"You can write to up to {MAX_RECIPIENTS} people at a time.")
            )

    subject = form["subject"]

    if not subject:
        errors.append(("subject", "Add a subject."))
    elif "\n" in subject or "\r" in subject:
        errors.append(("subject", "The subject must be a single line."))
    elif len(subject) > MAX_SUBJECT:
        errors.append(("subject", f"Keep the subject under {MAX_SUBJECT} characters."))

    body = form["body"]

    if not body.strip():
        errors.append(("body", "Write a message."))
    elif len(body) > MAX_BODY:
        errors.append(("body", f"The message is too long. Maximum: {MAX_BODY:,} characters."))

    return recipients, errors


def save_email_log(user_id, recipient, subject, status):
    """Save activity under the account that sent the message."""
    db.session.add(
        EmailLog(
            user_id=user_id,
            recipient=recipient,
            subject=subject,
            status=status,
        )
    )


def send_compose_emails(user_id, recipients, subject, body, attachments=()):
    """Send individual messages using the specified user's SMTP credentials."""
    user = db.session.get(User, user_id)

    if user and db.session.get(UserSuspension, user.id):
        raise ValueError("This account is suspended and cannot send email.")

    if not user or not user.mail_address or not user.encrypted_app_password:
        raise ValueError(
            "Your sending account is not configured. Open Settings and "
            "save your Gmail address and Gmail App Password first."
        )

    try:
        password = decrypt_secret(user.encrypted_app_password)
    except (RuntimeError, ValueError):
        app.logger.exception("Unable to decrypt a user's saved SMTP credential.")
        raise ValueError(
            "Your saved email credential could not be read. "
            "Please save your Gmail App Password again in Settings."
        ) from None

    if not validate_email_address(user.mail_address):
        raise ValueError("Your sending email address in Settings is invalid.")

    host = (user.smtp_host or "").strip()
    port = user.smtp_port

    if not host or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Check your SMTP host and port in Settings.")

    results = []
    server = None
    connection_lost = False

    try:
        server = open_smtp_connection(user.mail_address, password, host, port)

        for recipient in recipients:
            message = EmailMessage()
            sender_name = (user.sender_name or "").strip()

            if "\r" in sender_name or "\n" in sender_name:
                raise ValueError("Sender name must not contain line breaks.")

            if sender_name:
                message["From"] = f"{sender_name} <{user.mail_address}>"
            else:
                message["From"] = user.mail_address

            message["To"] = recipient
            message["Subject"] = subject
            message.set_content(body)

            for file_name, data, maintype, subtype in attachments:
                message.add_attachment(
                    data,
                    maintype=maintype,
                    subtype=subtype,
                    filename=file_name,
                )

            try:
                refused = server.send_message(message)
                status = "failed" if recipient in refused else "sent"
            except (smtplib.SMTPServerDisconnected, OSError):
                app.logger.exception("SMTP connection was lost during email delivery.")
                status = "failed"
                connection_lost = True
            except Exception:
                app.logger.exception("Email delivery attempt failed.")
                status = "failed"

            results.append((recipient, status))
            save_email_log(user_id, recipient, subject, status)
            db.session.commit()
            if connection_lost:
                break

        processed = {recipient for recipient, _status in results}
        for recipient in recipients:
            if recipient not in processed:
                results.append((recipient, "failed"))
                save_email_log(user_id, recipient, subject, "failed")
        db.session.commit()

    except ValueError:
        db.session.rollback()
        raise
    except Exception:
        app.logger.exception("SMTP connection or authentication failed.")

        # Log failures for recipients not processed yet.
        processed = {recipient for recipient, _status in results}
        for recipient in recipients:
            if recipient not in processed:
                results.append((recipient, "failed"))
                save_email_log(user_id, recipient, subject, "failed")

        db.session.commit()
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass

    return results


def process_due_schedules():
    """Claim and deliver due messages. Safe to call from one or more workers."""
    now = datetime.now(timezone.utc)
    ScheduledEmail.query.filter(
        ScheduledEmail.status == "sending",
        ScheduledEmail.started_at < now - timedelta(hours=2),
    ).update(
        {
            ScheduledEmail.status: "failed",
            ScheduledEmail.error_message: (
                "Delivery was interrupted; check email history before retrying."
            ),
        },
        synchronize_session=False,
    )
    db.session.commit()

    due_ids = [
        row.id
        for row in (
            ScheduledEmail.query.filter(
                ScheduledEmail.status == "scheduled",
                ScheduledEmail.scheduled_for <= now,
            )
            .order_by(ScheduledEmail.scheduled_for, ScheduledEmail.id)
            .limit(20)
            .with_entities(ScheduledEmail.id)
            .all()
        )
    ]
    processed = 0

    for schedule_id in due_ids:
        claimed = (
            ScheduledEmail.query.filter_by(id=schedule_id, status="scheduled")
            .filter(ScheduledEmail.scheduled_for <= now)
            .update(
                {
                    ScheduledEmail.status: "sending",
                    ScheduledEmail.started_at: now,
                },
                synchronize_session=False,
            )
        )
        db.session.commit()
        if not claimed:
            continue

        schedule = db.session.get(ScheduledEmail, schedule_id)
        if schedule is None:
            continue

        recipients = [
            item.strip()
            for item in re.split(r"[,;\n]+", schedule.recipient)
            if item.strip()
        ]
        try:
            results = send_compose_emails(
                schedule.user_id,
                recipients,
                schedule.subject,
                schedule.body,
            )
            schedule.status = (
                "sent"
                if results and all(status == "sent" for _, status in results)
                else "failed"
            )
            if schedule.status == "failed":
                schedule.error_message = "One or more messages could not be delivered. Check email history."
        except ValueError as exc:
            app.logger.warning(
                "Scheduled email %s could not be delivered: %s",
                schedule.id,
                exc,
            )
            for recipient in recipients:
                save_email_log(schedule.user_id, recipient, schedule.subject, "failed")
            schedule.status = "failed"
            schedule.error_message = str(exc)[:255]
        except Exception:
            app.logger.exception(
                "Unexpected error while delivering scheduled email %s.",
                schedule.id,
            )
            db.session.rollback()
            schedule = db.session.get(ScheduledEmail, schedule_id)
            if schedule is None:
                continue
            schedule.status = "failed"
            schedule.error_message = (
                "Delivery outcome could not be confirmed. Check email history "
                "before retrying."
            )

        db.session.commit()
        processed += 1

    return processed


def run_scheduler():
    """Run the dedicated polling process for scheduled email delivery."""
    app.logger.info("Scheduled email worker started.")
    while True:
        try:
            with app.app_context():
                process_due_schedules()
        except Exception:
            app.logger.exception("Scheduled email worker iteration failed.")
        time.sleep(15)


# ---------------- Authentication ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().casefold()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or len(name) > 120:
            flash("Enter your name (up to 120 characters).", "error")
        elif not validate_email_address(email):
            flash("Enter a valid email address.", "error")
        elif len(password) < 12 or len(password) > 128:
            flash("Your password must be between 12 and 128 characters.", "error")
        elif password != confirm_password:
            flash("The passwords do not match.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(full_name=name, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            login_user(user)
            flash("Your account has been created. Configure email settings to start sending.", "success")
            return redirect(url_for("settings"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().casefold()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if db.session.get(UserSuspension, user.id):
                flash("This account is suspended. Contact the site administrator.", "error")
                return render_template("login.html")
            login_user(user)
            destination = request.args.get("next", "")

            # Only allow local application paths as post-login destinations.
            if destination.startswith("/") and not destination.startswith("//"):
                return redirect(destination)

            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------- User email settings ----------------

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = db.session.get(User, current_user.id)

    if request.method == "POST":
        mail_address = request.form.get("mail_address", "").strip()
        app_password = request.form.get("app_password", "").strip()
        sender_name = request.form.get("sender_name", "").strip()
        smtp_host = request.form.get("smtp_host", "smtp.gmail.com").strip()
        smtp_port_raw = request.form.get("smtp_port", "465").strip()

        try:
            smtp_port = int(smtp_port_raw)
        except ValueError:
            smtp_port = 0

        if not validate_email_address(mail_address):
            flash("Enter a valid Gmail sending address.", "error")
        elif not smtp_host or len(smtp_host) > 255:
            flash("Enter a valid SMTP host.", "error")
        elif not 1 <= smtp_port <= 65535:
            flash("Enter a valid SMTP port.", "error")
        elif len(sender_name) > 120 or "\r" in sender_name or "\n" in sender_name:
            flash("Check your sender name.", "error")
        elif not app_password and not user.encrypted_app_password:
            flash("Enter your Gmail App Password to configure sending.", "error")
        else:
            user.mail_address = mail_address
            user.sender_name = sender_name
            user.smtp_host = smtp_host
            user.smtp_port = smtp_port

            if app_password:
                try:
                    user.encrypted_app_password = encrypt_secret(app_password)
                except (RuntimeError, ValueError):
                    app.logger.exception("Credential encryption failed.")
                    flash("Email settings could not be saved. Check server configuration.", "error")
                    return render_template("settings.html", user=user)

            db.session.commit()
            flash("Your email settings have been saved.", "success")
            return redirect(url_for("settings"))

    return render_template("settings.html", user=user)


# ---------------- Dashboard ----------------

@app.route("/admin")
@login_required
def admin_dashboard():
    if not is_admin_user():
        abort(404)

    today = local_now().date()
    first_day = today - timedelta(days=29)
    visitor_rows = (
        db.session.query(SiteVisitor.visit_date, func.count(SiteVisitor.id))
        .filter(SiteVisitor.visit_date >= first_day)
        .group_by(SiteVisitor.visit_date)
        .all()
    )
    visitor_counts = {
        visit_date: count for visit_date, count in visitor_rows
    }
    daily_visits = [
        {
            "date": first_day + timedelta(days=offset),
            "count": visitor_counts.get(first_day + timedelta(days=offset), 0),
        }
        for offset in range(30)
    ]
    recent_accounts_since = datetime.now(timezone.utc) - timedelta(days=30)

    stats = {
        "visitors_today": visitor_counts.get(today, 0),
        "visitors_30d": sum(visitor_counts.values()),
        "accounts": User.query.count(),
        "new_accounts_30d": User.query.filter(
            User.created_at >= recent_accounts_since
        ).count(),
        "emails_sent": EmailLog.query.filter_by(status="sent").count(),
        "emails_failed": EmailLog.query.filter_by(status="failed").count(),
        "scheduled": ScheduledEmail.query.filter(
            ScheduledEmail.status.in_(("scheduled", "sending"))
        ).count(),
        "contacts": Contact.query.count(),
    }
    account_query = User.query
    account_search = request.args.get("q", "").strip()[:120]
    if account_search:
        escaped_search = (
            account_search.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        account_query = account_query.filter(
            or_(
                User.email.ilike(f"%{escaped_search}%", escape="\\"),
                User.full_name.ilike(f"%{escaped_search}%", escape="\\"),
            )
        )
    accounts_per_page = 50
    account_count = account_query.count()
    total_account_pages = max(
        1,
        (account_count + accounts_per_page - 1) // accounts_per_page,
    )
    account_page = request.args.get("page", 1, type=int) or 1
    account_page = min(max(account_page, 1), total_account_pages)
    users = (
        account_query.order_by(User.created_at.desc(), User.id.desc())
        .offset((account_page - 1) * accounts_per_page)
        .limit(accounts_per_page)
        .all()
    )
    suspended_user_ids = {
        user_id for (user_id,) in db.session.query(UserSuspension.user_id).all()
    }
    admin_emails = admin_email_allowlist()
    admin_users = User.query.filter(User.email.in_(admin_emails)).all()
    current_epoch = int(time.time())
    pending_verification = (
        AdminVerification.query.filter_by(
            admin_user_id=current_user.id,
            consumed=False,
        )
        .filter(AdminVerification.expires_at > current_epoch)
        .order_by(AdminVerification.created_at.desc())
        .first()
    )

    return render_template(
        "admin.html",
        stats=stats,
        daily_visits=daily_visits,
        timezone_name=APP_TIMEZONE_NAME,
        users=users,
        account_search=account_search,
        account_page=account_page,
        total_account_pages=total_account_pages,
        account_count=account_count,
        suspended_user_ids=suspended_user_ids,
        admin_emails=admin_emails,
        admin_users=admin_users,
        bootstrap_admin_emails=app.config["ADMIN_EMAILS"],
        admin_grants=AdminGrant.query.order_by(AdminGrant.created_at.desc()).all(),
        pending_verification=pending_verification,
    )


@app.route("/admin/admins/invite", methods=["POST"])
@login_required
def admin_invite():
    require_admin()

    target_email = request.form.get("email", "").strip().casefold()
    target_user = User.query.filter_by(email=target_email).first()
    if not validate_email_address(target_email) or not target_user:
        flash("Enter the email of an existing MailFlow account.", "error")
        return redirect(url_for("admin_dashboard"))
    if target_email in admin_email_allowlist():
        flash("That account already has administrator access.", "error")
        return redirect(url_for("admin_dashboard"))

    now = int(time.time())
    recent_challenge = (
        AdminVerification.query.filter_by(admin_user_id=current_user.id)
        .filter(
            AdminVerification.created_at
            > now - ADMIN_CODE_RESEND_SECONDS
        )
        .first()
    )
    if recent_challenge:
        flash("Please wait before requesting another verification code.", "error")
        return redirect(url_for("admin_dashboard"))

    code = f"{secrets.randbelow(1_000_000):06d}"
    AdminVerification.query.filter(
        AdminVerification.admin_user_id == current_user.id,
        AdminVerification.consumed.is_(False),
    ).update({"consumed": True}, synchronize_session=False)
    db.session.query(AdminVerification).filter(
        AdminVerification.created_at < now - 24 * 60 * 60
    ).delete(synchronize_session=False)
    challenge = AdminVerification(
        admin_user_id=current_user.id,
        target_email=target_email,
        code_digest=admin_code_digest(current_user.id, target_email, code),
        expires_at=now + ADMIN_CODE_TTL_SECONDS,
        created_at=now,
    )
    db.session.add(challenge)
    db.session.commit()

    primary_email = app.config["PRIMARY_ADMIN_EMAIL"]
    primary_admin = User.query.filter_by(email=primary_email).first()
    if not primary_admin or primary_email not in app.config["ADMIN_EMAILS"]:
        challenge.consumed = True
        db.session.commit()
        flash("The primary admin email is not configured correctly.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        send_admin_verification_code(primary_admin, primary_email, code)
    except (RuntimeError, ValueError, OSError, smtplib.SMTPException):
        app.logger.exception("Admin verification email could not be sent.")
        challenge.consumed = True
        db.session.commit()
        flash(
            "The verification email could not be sent. Check the primary admin's SMTP settings.",
            "error",
        )
        return redirect(url_for("admin_dashboard"))
    flash("A verification code was sent to the primary admin email.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/admins/verify", methods=["POST"])
@login_required
def admin_verify_invite():
    require_admin()

    target_email = request.form.get("email", "").strip().casefold()
    code = request.form.get("code", "").strip()
    challenge = (
        AdminVerification.query.filter_by(
            admin_user_id=current_user.id,
            target_email=target_email,
            consumed=False,
        )
        .order_by(AdminVerification.created_at.desc())
        .first()
    )
    now = int(time.time())
    if (
        not challenge
        or challenge.expires_at <= now
        or challenge.attempts >= ADMIN_CODE_MAX_ATTEMPTS
    ):
        flash("The verification code expired or is no longer available.", "error")
        return redirect(url_for("admin_dashboard"))

    is_valid_code = bool(re.fullmatch(r"\d{6}", code))
    if is_valid_code:
        expected_digest = admin_code_digest(current_user.id, target_email, code)
        is_valid_code = hmac.compare_digest(challenge.code_digest, expected_digest)
    if not is_valid_code:
        challenge.attempts += 1
        if challenge.attempts >= ADMIN_CODE_MAX_ATTEMPTS:
            challenge.consumed = True
        db.session.commit()
        flash("The verification code is incorrect.", "error")
        return redirect(url_for("admin_dashboard"))

    target_user = User.query.filter_by(email=target_email).first()
    if not target_user:
        challenge.consumed = True
        db.session.commit()
        flash("That account no longer exists.", "error")
        return redirect(url_for("admin_dashboard"))
    if target_email in admin_email_allowlist():
        challenge.consumed = True
        db.session.commit()
        flash("That account already has administrator access.", "error")
        return redirect(url_for("admin_dashboard"))

    db.session.add(
        AdminGrant(
            email=target_email,
            granted_by_user_id=current_user.id,
        )
    )
    challenge.consumed = True
    db.session.commit()
    flash("Administrator access has been granted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/admins/<int:grant_id>/revoke", methods=["POST"])
@login_required
def admin_revoke(grant_id):
    require_admin()

    grant = db.session.get(AdminGrant, grant_id)
    if not grant:
        abort(404)
    if grant.email.casefold() == current_user.email.casefold():
        flash("You cannot revoke your own administrator access.", "error")
        return redirect(url_for("admin_dashboard"))

    db.session.delete(grant)
    db.session.commit()
    flash("Administrator access has been revoked.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/<int:user_id>/suspension", methods=["POST"])
@login_required
def admin_set_user_suspension(user_id):
    require_admin()

    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == current_user.id or user.email.casefold() in admin_email_allowlist():
        flash("Administrator accounts cannot be suspended from this panel.", "error")
        return redirect(url_for("admin_dashboard"))

    suspension = db.session.get(UserSuspension, user.id)
    action = request.form.get("action")
    if action == "suspend" and not suspension:
        db.session.add(
            UserSuspension(
                user_id=user.id,
                suspended_by_user_id=current_user.id,
            )
        )
        db.session.commit()
        flash("The account has been suspended.", "success")
    elif action == "reactivate" and suspension:
        db.session.delete(suspension)
        db.session.commit()
        flash("The account has been reactivated.", "success")
    else:
        abort(400)
    return redirect(url_for("admin_dashboard"))


@app.route("/")
@login_required
def dashboard():
    now = local_now()

    sent_count = EmailLog.query.filter_by(
        user_id=current_user.id,
        status="sent",
    ).count()

    failed_count = EmailLog.query.filter_by(
        user_id=current_user.id,
        status="failed",
    ).count()

    unique_contacts = Contact.query.filter_by(user_id=current_user.id).count()
    scheduled_count = ScheduledEmail.query.filter(
        ScheduledEmail.user_id == current_user.id,
        ScheduledEmail.status.in_(("scheduled", "sending")),
    ).count()

    # One query feeds the 7-day chart and the "last email" row.
    # It is always filtered by the logged-in user's ID.
    recent_logs = (
        EmailLog.query.filter_by(user_id=current_user.id)
        .order_by(EmailLog.id.desc())
        .limit(5000)
        .all()
    )

    week = build_week(recent_logs, now)
    last_time = to_local(recent_logs[0].sent_at) if recent_logs else None

    return render_template(
        "dashboard.html",
        greeting=greeting_for(now),
        clock=clock_parts(now),
        clock_tz=APP_TIMEZONE_NAME,
        today_sent=week["days"][-1]["sent"],
        rate=accepted_rate(sent_count, failed_count),
        last_time=last_time,
        first_name=first_name_of(current_user),
        post_day=now.day,
        post_month=now.strftime("%b"),
        post_year=now.year,
        stats={
            "sent": sent_count,
            "scheduled": scheduled_count,
            "contacts": unique_contacts,
            "failed": failed_count,
        },
        week=week,
        last_email=recent_logs[0] if recent_logs else None,
        setup=setup_status(current_user, sent_count + failed_count),
    )


@app.route("/contacts", methods=["GET", "POST"])
@login_required
def contacts():
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            if len(name) > 120 or "\n" in name or "\r" in name:
                flash("Keep the contact name to one line and under 120 characters.", "error")
            elif not validate_email_address(email):
                flash("Enter a valid email address.", "error")
            else:
                normalized_email = email.casefold()
                exists = Contact.query.filter_by(
                    user_id=current_user.id,
                    email=normalized_email,
                ).first()
                if exists:
                    flash("That email address is already in your contacts.", "info")
                else:
                    db.session.add(
                        Contact(
                            user_id=current_user.id,
                            name=name,
                            email=normalized_email,
                        )
                    )
                    db.session.commit()
                    flash("Contact saved.", "success")

        elif action == "import":
            upload = request.files.get("contact_file")
            if not upload or not upload.filename:
                flash("Choose a CSV file to import.", "error")
            else:
                content = upload.stream.read(1_000_001)
                if len(content) > 1_000_000:
                    flash("The CSV file must be smaller than 1 MB.", "error")
                else:
                    try:
                        reader = csv.DictReader(
                            io.StringIO(content.decode("utf-8-sig"), newline="")
                        )
                        headers = {
                            (header or "").strip().casefold(): header
                            for header in (reader.fieldnames or [])
                        }
                        email_key = headers.get("email") or headers.get("address")
                        name_key = headers.get("name") or headers.get("full name")
                        if not email_key:
                            flash("The CSV needs an 'email' or 'address' column.", "error")
                        else:
                            existing = {
                                email
                                for (email,) in db.session.query(Contact.email)
                                .filter_by(user_id=current_user.id)
                                .all()
                            }
                            added = skipped = 0
                            for row_number, row in enumerate(reader, start=2):
                                if row_number > 501:
                                    skipped += 1
                                    continue
                                email = (row.get(email_key) or "").strip().casefold()
                                name = (row.get(name_key) or "").strip() if name_key else ""
                                if (
                                    not validate_email_address(email)
                                    or len(name) > 120
                                    or "\n" in name
                                    or "\r" in name
                                    or email in existing
                                ):
                                    skipped += 1
                                    continue
                                db.session.add(
                                    Contact(
                                        user_id=current_user.id,
                                        name=name,
                                        email=email,
                                    )
                                )
                                existing.add(email)
                                added += 1
                            db.session.commit()
                            flash(
                                f"Imported {added} contact(s); skipped {skipped} invalid or duplicate row(s).",
                                "success" if added else "info",
                            )
                    except (UnicodeDecodeError, csv.Error):
                        db.session.rollback()
                        flash("The uploaded file is not a readable UTF-8 CSV.", "error")
        else:
            abort(400)

        return redirect(url_for("contacts"))

    saved_contacts = (
        Contact.query.filter_by(user_id=current_user.id)
        .order_by(Contact.name, Contact.email)
        .limit(5000)
        .all()
    )
    return render_template("contacts.html", contacts=saved_contacts)


@app.route("/contacts/<int:contact_id>/delete", methods=["POST"])
@login_required
def delete_contact(contact_id):
    contact = Contact.query.filter_by(
        id=contact_id,
        user_id=current_user.id,
    ).first_or_404()
    db.session.delete(contact)
    db.session.commit()
    flash("Contact deleted.", "success")
    return redirect(url_for("contacts"))


@app.route("/scheduled", methods=["GET", "POST"])
@login_required
def scheduled():
    errors = []
    form = {
        "recipient": "",
        "subject": "",
        "body": "",
        "scheduled_for": "",
    }

    if request.method == "POST":
        form["recipient"] = request.form.get("recipient", "").strip()
        form["subject"] = request.form.get("subject", "").strip()
        form["body"] = clean_body(request.form.get("body", ""))
        form["scheduled_for"] = request.form.get("scheduled_for", "").strip()

        if not current_user.mail_address or not current_user.encrypted_app_password:
            errors.append(("form", "Connect your sending account in Email Settings before scheduling."))

        recipients, compose_errors = check_compose(form)
        errors.extend(compose_errors)

        try:
            local_schedule = datetime.fromisoformat(form["scheduled_for"])
            if local_schedule.tzinfo is not None:
                raise ValueError
            local_schedule = local_schedule.replace(tzinfo=APP_TZ)
            scheduled_for = local_schedule.astimezone(timezone.utc)
            if local_schedule <= local_now():
                errors.append(("scheduled_for", "Choose a time in the future."))
        except ValueError:
            errors.append(("scheduled_for", "Enter a valid date and time."))

        if not errors:
            db.session.add(
                ScheduledEmail(
                    user_id=current_user.id,
                    recipient=", ".join(recipients),
                    subject=form["subject"],
                    body=form["body"],
                    scheduled_for=scheduled_for,
                )
            )
            db.session.commit()
            flash("Email scheduled. Keep the scheduler worker running to deliver it on time.", "success")
            return redirect(url_for("scheduled"))

    queued = (
        ScheduledEmail.query.filter_by(user_id=current_user.id)
        .order_by(ScheduledEmail.scheduled_for.desc())
        .limit(200)
        .all()
    )
    return render_template(
        "scheduled.html",
        schedules=queued,
        form=form,
        errors=errors,
        min_schedule=local_now().strftime("%Y-%m-%dT%H:%M"),
        clock=clock_parts(local_now()),
        contacts=(
            Contact.query.filter_by(user_id=current_user.id)
            .order_by(Contact.name, Contact.email)
            .limit(5000)
            .all()
        ),
    )


@app.route("/scheduled/<int:schedule_id>/cancel", methods=["POST"])
@login_required
def cancel_schedule(schedule_id):
    schedule = ScheduledEmail.query.filter_by(
        id=schedule_id,
        user_id=current_user.id,
        status="scheduled",
    ).first()
    if schedule is None:
        flash("That email is no longer waiting and cannot be cancelled.", "error")
    else:
        db.session.delete(schedule)
        db.session.commit()
        flash("Scheduled email cancelled.", "success")
    return redirect(url_for("scheduled"))


# ---------------- Saved templates ----------------

def clean_body(text):
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def user_templates():
    """The logged-in user's templates. Always filtered by user id."""
    return (
        EmailTemplate.query.filter_by(user_id=current_user.id)
        .order_by(EmailTemplate.name)
        .all()
    )


def check_template(name, subject, body):
    errors = []

    if not name:
        errors.append(("template_name", "Give the template a name."))
    elif "\n" in name or "\r" in name:
        errors.append(("template_name", "The name must be a single line."))
    elif len(name) > MAX_TEMPLATE_NAME:
        errors.append(
            ("template_name", f"Keep the name under {MAX_TEMPLATE_NAME} characters.")
        )

    if not subject:
        errors.append(("subject", "Add a subject."))
    elif "\n" in subject or "\r" in subject:
        errors.append(("subject", "The subject must be a single line."))
    elif len(subject) > MAX_SUBJECT:
        errors.append(("subject", f"Keep the subject under {MAX_SUBJECT} characters."))

    if not body:
        errors.append(("body", "Write a message."))
    elif len(body) > MAX_BODY:
        errors.append(("body", f"The message is too long. Maximum: {MAX_BODY:,} characters."))

    return errors


def save_template(name, subject, body):
    """Create a template, or update the one that already has this name.

    Returns (template, created).
    """
    templates = user_templates()

    for existing in templates:
        if existing.name.casefold() == name.casefold():
            existing.name = name
            existing.subject = subject
            existing.body = body
            db.session.commit()
            return existing, False

    if len(templates) >= MAX_TEMPLATES:
        raise ValueError(
            f"You can keep up to {MAX_TEMPLATES} templates. Delete one first."
        )

    template = EmailTemplate(
        user_id=current_user.id,
        name=name,
        subject=subject,
        body=body,
    )
    db.session.add(template)
    db.session.commit()
    return template, True


def merge_addresses(current_text, extra):
    """Add addresses to the To box without repeating any. Returns (text, added)."""
    existing = [a.strip() for a in re.split(r"[,;\n]+", current_text) if a.strip()]
    seen = {a.casefold() for a in existing}
    added = 0

    for address in extra:
        if address.casefold() not in seen:
            seen.add(address.casefold())
            existing.append(address)
            added += 1

    return ", ".join(existing), added


# ---------------- Compose ----------------

@app.route("/compose", methods=["GET", "POST"])
@login_required
def compose():
    form = {
        "recipient": "",
        "subject": "",
        "body": "",
        "confirmed": False,
        "template_name": "",
    }
    errors = []
    preview = None
    notice = None
    notice_type = "info"
    draft_id = ""

    # Abandoned attachment drafts (older than a day) are removed.
    cleanup_old_drafts(INSTANCE_DIR, current_user.id)

    if request.method == "GET":
        # No email is sent by a GET request.
        contact_id = request.args.get("contact", type=int)
        if contact_id:
            chosen_contact = Contact.query.filter_by(
                id=contact_id,
                user_id=current_user.id,
            ).first()
            if chosen_contact:
                form["recipient"] = chosen_contact.email
                notice = f'Contact "{chosen_contact.name or chosen_contact.email}" added to the recipient list.'
            else:
                notice = "That contact could not be found."

        template_id = request.args.get("template", type=int)
        if template_id:
            chosen = EmailTemplate.query.filter_by(
                id=template_id,
                user_id=current_user.id,
            ).first()
            if chosen:
                form["subject"] = chosen.subject
                form["body"] = chosen.body
                notice = f'Template "{chosen.name}" loaded. Add the recipients, then preview.'
            else:
                notice = "That template could not be found."

    if request.method == "POST":
        action = request.form.get("action", "")
        form["recipient"] = request.form.get("recipient", "").strip()
        form["subject"] = request.form.get("subject", "").strip()
        form["body"] = clean_body(request.form.get("body", ""))
        form["confirmed"] = request.form.get("confirmed") == "yes"
        form["template_name"] = request.form.get("template_name", "").strip()

        draft_id = request.form.get("draft_id", "")
        if not is_valid_draft_id(draft_id):
            draft_id = ""

        if action not in ("preview", "send", "save_template"):
            errors.append(("form", "Please use a valid form button."))

        elif action == "save_template":
            errors = check_template(
                form["template_name"], form["subject"], form["body"]
            )
            if not errors:
                try:
                    saved, created = save_template(
                        form["template_name"], form["subject"], form["body"]
                    )
                except ValueError as exc:
                    errors.append(("template_name", str(exc)))
                else:
                    flash(
                        f'Template "{saved.name}" '
                        f'{"saved" if created else "updated"}.',
                        "success",
                    )
                    return redirect(url_for("compose", template=saved.id))

        else:
            # True when attachments or addresses changed in this request.
            # Such changes must be previewed again before anything is sent.
            changed = False
            folder = draft_dir(INSTANCE_DIR, current_user.id, draft_id) if draft_id else None

            removals = request.form.getlist("remove_attachment")
            if removals and folder and delete_files(folder, removals):
                changed = True

            new_files = [f for f in request.files.getlist("attachments") if f and f.filename]
            if new_files:
                if not draft_id:
                    draft_id = new_draft_id()
                    folder = draft_dir(INSTANCE_DIR, current_user.id, draft_id)
                saved_count, problems = add_files(folder, new_files)
                changed = changed or saved_count > 0
                for problem in problems:
                    errors.append(("attachments", problem))

            address_file = request.files.get("recipient_file")
            if address_file and address_file.filename:
                text, problem = read_address_file(address_file)
                if problem:
                    errors.append(("recipient_file", problem))
                else:
                    found, skipped = extract_addresses(text, validate_email_address)
                    form["recipient"], added = merge_addresses(form["recipient"], found)
                    changed = changed or added > 0
                    notice = (
                        f"Added {added} address(es) from {address_file.filename[:60]}."
                        if added
                        else "No new email addresses were found in that file."
                    )
                    if skipped:
                        notice += f" {skipped} entry(ies) that did not look like addresses were skipped."

            recipients, more_errors = check_compose(form)
            errors.extend(more_errors)

            if action == "send" and not form["confirmed"]:
                errors.append(("confirmed", "Confirm that you checked the email."))

            if action == "send" and changed:
                errors.append(
                    (
                        "form",
                        "You changed the attachments or the address list. "
                        "Select Preview email again before sending.",
                    )
                )

            if not errors:
                files = list_files(folder) if folder else []
                preview = {
                    "recipients": recipients,
                    "count": len(recipients),
                    "subject": form["subject"],
                    "body": form["body"],
                    "words": len(form["body"].split()),
                    "attachments": files,
                }

                if action == "send":
                    try:
                        attachment_data = read_attachments(folder) if folder else []
                        results = send_compose_emails(
                            current_user.id,
                            recipients,
                            form["subject"],
                            form["body"],
                            attachment_data,
                        )
                        sent_count = sum(status == "sent" for _, status in results)
                        failed_count = sum(status == "failed" for _, status in results)

                        if sent_count and not failed_count:
                            flash(
                                f"The mail server accepted all {sent_count} message(s).",
                                "success",
                            )
                        elif sent_count:
                            flash(
                                f"{sent_count} accepted; {failed_count} failed. "
                                "Check your email history.",
                                "info",
                            )
                        else:
                            flash(
                                "No message was confirmed as sent. Check your settings.",
                                "error",
                            )

                        # The attachment copies are no longer needed.
                        if sent_count and folder:
                            delete_draft(folder)
                    except ValueError as exc:
                        db.session.rollback()
                        flash(str(exc), "error")

                    return redirect(url_for("compose"))

    field_errors = {}
    for field, message in errors:
        field_errors.setdefault(field, message)

    attachments = (
        list_files(draft_dir(INSTANCE_DIR, current_user.id, draft_id))
        if draft_id
        else []
    )

    return render_template(
        "compose.html",
        form=form,
        errors=errors,
        field_errors=field_errors,
        preview=preview,
        notice=notice,
        notice_type=notice_type,
        draft_id=draft_id,
        attachments=attachments,
        templates=user_templates(),
        contacts=(
            Contact.query.filter_by(user_id=current_user.id)
            .order_by(Contact.name, Contact.email)
            .limit(5000)
            .all()
        ),
        accept=ACCEPT_ATTRIBUTE,
        limits={
            "subject": MAX_SUBJECT,
            "body": MAX_BODY,
            "max_files": MAX_FILES,
            "max_total": format_size(MAX_TOTAL_BYTES),
            "allowed": ALLOWED_LABEL,
            "max_recipients": MAX_RECIPIENTS,
        },
    )


# ---------------- Templates page ----------------

@app.route("/templates", methods=["GET", "POST"])
@login_required
def templates_list():
    form = {"template_name": "", "subject": "", "body": ""}
    errors = []

    if request.method == "POST":
        form["template_name"] = request.form.get("template_name", "").strip()
        form["subject"] = request.form.get("subject", "").strip()
        form["body"] = clean_body(request.form.get("body", ""))

        errors = check_template(form["template_name"], form["subject"], form["body"])

        if not errors:
            try:
                saved, created = save_template(
                    form["template_name"], form["subject"], form["body"]
                )
            except ValueError as exc:
                errors.append(("template_name", str(exc)))
            else:
                flash(
                    f'Template "{saved.name}" {"saved" if created else "updated"}.',
                    "success",
                )
                return redirect(url_for("templates_list"))

    field_errors = {}
    for field, message in errors:
        field_errors.setdefault(field, message)

    return render_template(
        "email_templates.html",
        form=form,
        errors=errors,
        field_errors=field_errors,
        templates=user_templates(),
        limits={
            "name": MAX_TEMPLATE_NAME,
            "subject": MAX_SUBJECT,
            "body": MAX_BODY,
            "max_templates": MAX_TEMPLATES,
        },
    )


@app.route("/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def template_delete(template_id):
    template = EmailTemplate.query.filter_by(
        id=template_id,
        user_id=current_user.id,
    ).first()

    if template is None:
        flash("That template could not be found.", "error")
    else:
        name = template.name
        db.session.delete(template)
        db.session.commit()
        flash(f'Template "{name}" deleted.', "success")

    return redirect(url_for("templates_list"))


# ---------------- Email history ----------------

@app.route("/search")
@login_required
def search():
    query = request.args.get("q", "").strip()
    results = {
        "contacts": [],
        "emails": [],
        "scheduled": [],
        "templates": [],
    }
    error = None

    if len(query) > 120:
        error = "Search terms must be 120 characters or fewer."
    elif query:
        pattern = (
            "%"
            + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        results["contacts"] = (
            Contact.query.filter_by(user_id=current_user.id)
            .filter(
                or_(
                    Contact.name.ilike(pattern, escape="\\"),
                    Contact.email.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Contact.name, Contact.email)
            .limit(25)
            .all()
        )
        results["emails"] = (
            EmailLog.query.filter_by(user_id=current_user.id)
            .filter(
                or_(
                    EmailLog.recipient.ilike(pattern, escape="\\"),
                    EmailLog.subject.ilike(pattern, escape="\\"),
                    EmailLog.status.ilike(pattern, escape="\\"),
                )
            )
            .order_by(EmailLog.id.desc())
            .limit(25)
            .all()
        )
        results["scheduled"] = (
            ScheduledEmail.query.filter_by(user_id=current_user.id)
            .filter(
                or_(
                    ScheduledEmail.recipient.ilike(pattern, escape="\\"),
                    ScheduledEmail.subject.ilike(pattern, escape="\\"),
                    ScheduledEmail.status.ilike(pattern, escape="\\"),
                )
            )
            .order_by(ScheduledEmail.scheduled_for.desc())
            .limit(25)
            .all()
        )
        results["templates"] = (
            EmailTemplate.query.filter_by(user_id=current_user.id)
            .filter(
                or_(
                    EmailTemplate.name.ilike(pattern, escape="\\"),
                    EmailTemplate.subject.ilike(pattern, escape="\\"),
                    EmailTemplate.body.ilike(pattern, escape="\\"),
                )
            )
            .order_by(EmailTemplate.updated_at.desc(), EmailTemplate.name)
            .limit(25)
            .all()
        )

    return render_template(
        "search.html",
        query=query,
        results=results,
        error=error,
    )


@app.route("/history")
@login_required
def history():
    # Always filter by the authenticated user's ID.
    logs = (
        EmailLog.query.filter_by(user_id=current_user.id)
        .order_by(EmailLog.id.desc())
        .limit(200)
        .all()
    )
    return render_template("history.html", logs=logs)


# Create tables for a fresh local installation.
# For production schema changes, use database migrations.
with app.app_context():
    db.create_all()
    if os.name == "posix" and DATABASE_PATH.is_file():
        DATABASE_PATH.chmod(0o600)


if __name__ == "__main__":
    if "--scheduler" in sys.argv[1:]:
        run_scheduler()
    else:
        app.run(
            host="127.0.0.1",
            port=5000,
            debug=os.environ.get("FLASK_DEBUG") == "1",
        )
