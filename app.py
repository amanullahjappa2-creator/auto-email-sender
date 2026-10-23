
"""MailFlow Studio - multi-user Flask application."""

import os
import re
import smtplib
import ssl
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
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import func
from werkzeug.middleware.proxy_fix import ProxyFix
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import BASE_DIR, INSTANCE_DIR, Config
from models import db, User, EmailLog
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

app = Flask(__name__)
app.config.from_object(Config)
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Total request size limit. The attachment rules themselves (file count,
# 10 MB total, allowed types) are enforced in compose_tools.py.
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("COOKIE_SECURE", "0") == "1"
)

db.init_app(app)
CSRFProtect(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"
login_manager.init_app(app)

MAX_RECIPIENTS = 50
MAX_SUBJECT = 200
MAX_BODY = 20_000
MAX_RECIPIENT_FIELD = 5_000
MAX_TEMPLATES = 50
MAX_TEMPLATE_NAME = 80

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


@login_manager.user_loader
def load_user(user_id):
    """Load the authenticated user from the database."""
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


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
    }


@app.after_request
def add_security_headers(response):
    """Add browser security headers."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
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
            address = item.strip()
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


def save_email_log(recipient, subject, status):
    """Save activity under the currently authenticated user."""
    db.session.add(
        EmailLog(
            user_id=current_user.id,
            recipient=recipient,
            subject=subject,
            status=status,
        )
    )


def send_compose_emails(recipients, subject, body, attachments=()):
    """Send individual messages using this user's own SMTP credentials."""
    user = db.session.get(User, current_user.id)

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

    try:
        server = smtplib.SMTP_SSL(
            host,
            port,
            context=ssl.create_default_context(),
            timeout=20,
        )
        server.login(user.mail_address, password)

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
            except Exception:
                app.logger.exception("Email delivery attempt failed.")
                status = "failed"

            results.append((recipient, status))
            save_email_log(recipient, subject, status)
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
                save_email_log(recipient, subject, "failed")

        db.session.commit()
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass

    return results


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

    unique_contacts = (
        db.session.query(func.count(func.distinct(EmailLog.recipient)))
        .filter_by(user_id=current_user.id)
        .scalar()
        or 0
    )

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
            "scheduled": 0,
            "contacts": unique_contacts,
            "failed": failed_count,
        },
        week=week,
        last_email=recent_logs[0] if recent_logs else None,
        setup=setup_status(current_user, sent_count + failed_count),
    )


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


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
