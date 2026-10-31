"""Shared, framework-light application helpers.

Keeping validation, formatting, and chart shaping here makes the route modules
explicit about their dependencies and keeps app.py focused on composition.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

APP_TIMEZONE_NAME = os.environ.get("APP_TIMEZONE", "Asia/Karachi")
STORED_TIMES_ARE_UTC = True
MAX_RECIPIENTS = 120
MAX_SUBJECT = 200
MAX_BODY = 20_000
MAX_RECIPIENT_FIELD = 5_000
MAX_TEMPLATES = 60
MAX_TEMPLATE_NAME = 80
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


def _load_timezone(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Asia/Karachi":
            return timezone(timedelta(hours=5), "PKT")
        return timezone.utc


APP_TZ = _load_timezone(APP_TIMEZONE_NAME)


def local_now():
    return datetime.now(APP_TZ)


def to_local(moment):
    if moment is None:
        return None
    if moment.tzinfo is None:
        source = timezone.utc if STORED_TIMES_ARE_UTC else APP_TZ
        moment = moment.replace(tzinfo=source)
    return moment.astimezone(APP_TZ)


def greeting_for(now):
    if now.hour < 12:
        return "Good morning"
    if now.hour < 18:
        return "Good afternoon"
    return "Good evening"


def first_name_of(user):
    parts = (getattr(user, "full_name", "") or "").split()
    return parts[0] if parts else ""


def build_week(logs, now):
    today = now.date()
    first_day = today - timedelta(days=6)
    days, by_date = [], {}
    for offset in range(7):
        day = first_day + timedelta(days=offset)
        entry = {"label": day.strftime("%a"), "full": day.strftime("%a %d %b"), "is_today": day == today, "sent": 0, "failed": 0, "total": 0}
        days.append(entry)
        by_date[day] = entry
    for log in logs:
        when = to_local(getattr(log, "sent_at", None))
        entry = by_date.get(when.date()) if when else None
        if entry:
            if log.status == "sent":
                entry["sent"] += 1
            elif log.status == "failed":
                entry["failed"] += 1
    for entry in days:
        entry["total"] = entry["sent"] + entry["failed"]
    peak = max((entry["total"] for entry in days), default=0)
    unit = 90.0 / peak if peak else 0.0
    for index, entry in enumerate(days):
        sent_h = max(entry["sent"] * unit, 4.0) if entry["sent"] else 0.0
        failed_h = max(entry["failed"] * unit, 4.0) if entry["failed"] else 0.0
        entry.update(x=index * 10 + 3.4, sent_h=round(sent_h, 1), sent_y=round(100 - sent_h, 1), failed_h=round(failed_h, 1), failed_y=round(100 - sent_h - failed_h, 1))
    return {"days": days, "total": sum(entry["total"] for entry in days)}


def accepted_rate(sent, failed):
    attempted = sent + failed
    return None if attempted == 0 else round(sent * 100 / attempted)


def clock_parts(now):
    return {"date": f"{now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}", "time": now.strftime("%I:%M %p").lstrip("0"), "zone": now.tzname() or APP_TIMEZONE_NAME}


def setup_status(user, total_emails):
    return {"account_ready": bool(user.mail_address and user.encrypted_app_password), "mail_address": user.mail_address or "", "has_emails": total_emails > 0}


def validate_email_address(address):
    address = address.strip()
    return len(address) <= 254 and EMAIL_RE.fullmatch(address) is not None


def normalize_recipient(address):
    candidate = (address or "").strip()
    match = re.search(r"<([^<>]+)>", candidate) if candidate else None
    return match.group(1).strip() if match else candidate


def check_compose(form):
    errors, recipients = [], []
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
                errors.append(("recipient", f'"{address[:60]}" is not a valid email address.'))
                break
            if address.casefold() not in seen:
                seen.add(address.casefold())
                recipients.append(address)
        if not errors and not recipients:
            errors.append(("recipient", "Enter at least one email address."))
        if not errors and len(recipients) > MAX_RECIPIENTS:
            errors.append(("recipient", f"You can write to up to {MAX_RECIPIENTS} people at a time."))
    subject, body = form["subject"], form["body"]
    if not subject:
        errors.append(("subject", "Add a subject."))
    elif "\n" in subject or "\r" in subject:
        errors.append(("subject", "The subject must be a single line."))
    elif len(subject) > MAX_SUBJECT:
        errors.append(("subject", f"Keep the subject under {MAX_SUBJECT} characters."))
    if not body.strip():
        errors.append(("body", "Write a message."))
    elif len(body) > MAX_BODY:
        errors.append(("body", f"The message is too long. Maximum: {MAX_BODY:,} characters."))
    return recipients, errors


def clean_body(text):
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def check_template(name, subject, body):
    errors = []
    if not name:
        errors.append(("template_name", "Give the template a name."))
    elif "\n" in name or "\r" in name:
        errors.append(("template_name", "The name must be a single line."))
    elif len(name) > MAX_TEMPLATE_NAME:
        errors.append(("template_name", f"Keep the name under {MAX_TEMPLATE_NAME} characters."))
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


def merge_addresses(current_text, extra):
    existing = [a.strip() for a in re.split(r"[,;\n]+", current_text) if a.strip()]
    seen = {a.casefold() for a in existing}
    added = 0
    for address in extra:
        if address.casefold() not in seen:
            seen.add(address.casefold())
            existing.append(address)
            added += 1
    return ", ".join(existing), added
