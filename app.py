
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
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import BASE_DIR, DATABASE_PATH, INSTANCE_DIR, Config
from models import (
    AdminGrant,
    AdminVerification,
    Contact,
    EmailLog,
    ScheduledEmail,
    SiteVisitor,
    User,
    UserSuspension,
)
from extensions import csrf, db, limiter, login_manager, migrate
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

APP_VERSION = "1.2.0"

app = Flask(__name__)
app.config.from_object(Config)
app.config["APP_VERSION"] = APP_VERSION
app.config["APP_NAME"] = "MailFlow Studio"

# Total request size limit. The attachment rules themselves (file count,
# 10 MB total, allowed types) are enforced in compose_tools.py.
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
app.config["RATELIMIT_STORAGE_URI"] = os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://")
app.config["RATELIMIT_DEFAULT"] = []
try:
    trusted_proxy_hops = max(0, int(os.environ.get("TRUSTED_PROXY_HOPS", "0")))
except ValueError:
    trusted_proxy_hops = 0
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=trusted_proxy_hops,
    x_proto=trusted_proxy_hops,
    x_host=trusted_proxy_hops,
    x_port=trusted_proxy_hops,
    x_prefix=trusted_proxy_hops,
)
db.init_app(app)
csrf.init_app(app)
limiter.init_app(app)
migrate.init_app(app, db)

login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"
login_manager.session_protection = app.config["SESSION_PROTECTION"]
login_manager.init_app(app)

# Route modules consume these through ``current_app.extensions`` so they do
# not import the application module or create an app/module dependency cycle.

MAX_RECIPIENTS = 120
MAX_SUBJECT = 200
MAX_BODY = 20_000
MAX_RECIPIENT_FIELD = 5_000
MAX_TEMPLATES = 60
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
        or request.endpoint in {"static", "admin.admin_dashboard"}
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


@app.route("/healthz")
def health_check():
    """Fast health probe for monitor systems and deployment checks."""
    try:
        with app.app_context():
            db.session.execute(db.text("SELECT 1")).scalar()
        database_status = "ok"
        status_code = 200
    except Exception:
        app.logger.exception("Health check failed while reaching the database.")
        database_status = "error"
        status_code = 503

    return jsonify(
        {
            "status": "ok" if database_status == "ok" else "degraded",
            "app": "MailFlow Studio",
            "version": APP_VERSION,
            "database": database_status,
            "timezone": APP_TIMEZONE_NAME,
        }
    ), status_code


@app.errorhandler(413)
def request_too_large(_error):
    return "The uploaded request is too large.", 413


@app.errorhandler(404)
def not_found(_error):
    return "Page not found.", 404


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


def run_scheduler_once():
    """Process one batch of due emails and exit."""
    with app.app_context():
        processed = process_due_schedules()
    app.logger.info("One-shot scheduler processed %s scheduled email(s).", processed)
    print(f"Processed {processed} scheduled email(s).")
    return processed


# ---------------- Authentication ----------------

def clean_body(text):
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def ensure_sample_templates_for_user(user_id):
    """Ensure each account has the built-in starter templates."""
    from add_sample_templates import SAMPLE_TEMPLATES

    user = db.session.get(User, user_id)
    if user is None:
        return []

    existing_by_name = {
        template.name.casefold(): template
        for template in EmailTemplate.query.filter_by(user_id=user_id).all()
    }
    changed = False

    for template_data in SAMPLE_TEMPLATES:
        name = template_data["name"]
        existing = existing_by_name.get(name.casefold())
        if existing is None:
            db.session.add(
                EmailTemplate(
                    user_id=user_id,
                    name=name,
                    subject=template_data["subject"],
                    body=template_data["body"],
                )
            )
            changed = True
        elif (
            existing.subject == template_data["subject"]
            and existing.body == template_data["legacy_body"]
        ):
            existing.subject = template_data["subject"]
            existing.body = template_data["body"]
            changed = True

    if changed:
        db.session.commit()

    return sorted(
        EmailTemplate.query.filter_by(user_id=user_id).order_by(EmailTemplate.name).all(),
        key=lambda item: item.name.casefold(),
    )


def user_templates():
    """The logged-in user's templates. Always filtered by user id."""
    if current_user.is_authenticated:
        ensure_sample_templates_for_user(current_user.id)
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


app.extensions["mailflow_services"] = {
    # Resolve through module globals at call time so existing integrations and
    # tests can still patch the compatibility functions exported by app.py.
    "ensure_sample_templates_for_user": lambda *args, **kwargs: ensure_sample_templates_for_user(*args, **kwargs),
    "save_template": lambda *args, **kwargs: save_template(*args, **kwargs),
    "send_admin_verification_code": lambda *args, **kwargs: send_admin_verification_code(*args, **kwargs),
    "send_compose_emails": lambda *args, **kwargs: send_compose_emails(*args, **kwargs),
    "user_templates": lambda *args, **kwargs: user_templates(*args, **kwargs),
    "admin_code_digest": lambda *args, **kwargs: admin_code_digest(*args, **kwargs),
}


# ---------------- Compose ----------------


def register_routes():
    """Import and register blueprints after the app module is initialized."""
    # Route modules still import shared application helpers from app.py. Doing
    # this lazily avoids importing a half-initialized app during module import.
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.dashboard import dashboard_bp
    from routes.scheduled import scheduled_bp
    from routes.mail import mail_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(scheduled_bp)
    app.register_blueprint(mail_bp)

# When launched as `python app.py`, the main module is named `__main__` while
# the route modules import shared helpers from `app`. Point that import at the
# already-running module instead of executing app.py a second time.
sys.modules.setdefault("app", sys.modules[__name__])
register_routes()
if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--version" in argv:
        print(f"MailFlow Studio {APP_VERSION}")
        raise SystemExit(0)

    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", "5000"))

    for item in argv:
        if item.startswith("--host="):
            host = item.split("=", 1)[1]
        elif item.startswith("--port="):
            try:
                port = int(item.split("=", 1)[1])
            except ValueError:
                raise SystemExit("--port must be an integer.")

    if "--scheduler-once" in argv:
        run_scheduler_once()
    elif "--scheduler" in argv:
        run_scheduler()
    else:
        app.run(
            host=host,
            port=port,
            debug=os.environ.get("FLASK_DEBUG") == "1",
        )
