"""Auto Email Sender

Reads recipients from a CSV file, fills a text template with each row's
details, and sends the emails one by one with a delay between them.

Usage:
    python send_emails.py --dry-run          # preview only, nothing is sent
    python send_emails.py                    # send for real
    python send_emails.py --delay 60 --attach cv.pdf
"""

import argparse
import csv
import mimetypes
import os
import random
import smtplib
import ssl
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from string import Template

BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "sent_log.csv"
DEFAULT_DAILY_LIMIT = 450


def load_env(path: Path) -> None:
    """Minimal .env loader so no extra package is needed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_recipients(csv_path: Path) -> list[dict]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        return [
            {k.strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(f)
        ]


def already_sent() -> set[str]:
    if not LOG_FILE.exists():
        return set()
    with LOG_FILE.open(newline="", encoding="utf-8") as f:
        return {
            row["email"].strip().casefold()
            for row in csv.DictReader(f)
            if row.get("email") and row.get("status", "").casefold() == "sent"
        }


def sent_today(log_path: Path = LOG_FILE, today=None) -> int:
    """Count successful sends recorded by this utility for the current local day."""
    if not log_path.exists():
        return 0

    today = today or datetime.now().date()
    count = 0
    with log_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status", "").casefold() != "sent":
                continue
            try:
                sent_at = datetime.strptime(row.get("time", ""), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            count += sent_at.date() == today
    return count


def log_sent(email: str, status: str) -> None:
    new_file = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["email", "status", "time"])
        writer.writerow([email, status, time.strftime("%Y-%m-%d %H:%M:%S")])


def build_message(sender, name_from, to, subject, body, attach):
    msg = EmailMessage()
    msg["From"] = f"{name_from} <{sender}>" if name_from else sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attach:
        path = Path(attach)
        mime_type, _encoding = mimetypes.guess_type(path.name)
        # Windows commonly reports CSV as application/vnd.ms-excel. CSV is a
        # text attachment, so keep the portable and semantically correct type.
        if path.suffix.casefold() == ".csv":
            mime_type = "text/csv"
        maintype, separator, subtype = (mime_type or "application/octet-stream").partition("/")
        msg.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype if separator else "octet-stream",
            filename=path.name,
        )
    return msg


def render_message(subject_template, body_template, row):
    """Render one recipient's content or return a clear template problem."""
    try:
        return subject_template.substitute(row), body_template.substitute(row), None
    except KeyError as exc:
        return None, None, f"CSV column {exc.args[0]!r} is missing"
    except ValueError as exc:
        return None, None, f"invalid template placeholder: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Send personalized emails from a CSV.")
    parser.add_argument("--csv", default="recipients.csv")
    parser.add_argument("--template", default="template.txt")
    parser.add_argument("--subject", default="Inquiry about $program at $university")
    parser.add_argument("--attach", help="Optional file to attach; MIME type is inferred from its name")
    parser.add_argument("--delay", type=int, default=45, help="Base seconds between emails")
    parser.add_argument(
        "--daily-limit",
        type=int,
        default=DEFAULT_DAILY_LIMIT,
        help=(
            "Maximum successful sends per local day recorded by this utility "
            f"(default: {DEFAULT_DAILY_LIMIT}; set to your provider's limit)"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()

    if args.delay < 0:
        parser.error("--delay cannot be negative.")
    if args.daily_limit < 1:
        parser.error("--daily-limit must be at least 1.")

    load_env(BASE_DIR / ".env")
    sender = os.environ.get("EMAIL_ADDRESS")
    password = os.environ.get("EMAIL_APP_PASSWORD")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    name_from = os.environ.get("SENDER_NAME", "")

    if not args.dry_run and not (sender and password):
        print("Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD in the .env file first.")
        return 1

    template = Template(Path(args.template).read_text(encoding="utf-8"))
    subject_t = Template(args.subject)
    recipients = read_recipients(Path(args.csv))
    done = already_sent()

    todo = [
        row
        for row in recipients
        if row.get("email", "").strip().casefold() not in done
    ]
    print(f"{len(recipients)} in CSV, {len(recipients) - len(todo)} already sent, {len(todo)} to go.")
    successful_today = sent_today()
    if not args.dry_run and successful_today >= args.daily_limit:
        print(
            f"Daily send limit reached ({successful_today}/{args.daily_limit}). "
            "No messages were sent."
        )
        return 1

    server = None
    if not args.dry_run and todo:
        server = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context())
        server.login(sender, password)

    try:
        for i, row in enumerate(todo, 1):
            recipient = row.get("email", "").strip()
            if not recipient:
                print(f"[skip] CSV row {i}: email column is missing or empty")
                continue

            subject, body, problem = render_message(subject_t, template, row)
            if problem:
                print(f"[skip] {recipient}: {problem}")
                continue

            if args.dry_run:
                print(f"\n--- [{i}] To: {recipient} ---\nSubject: {subject}\n\n{body}")
                continue

            if successful_today >= args.daily_limit:
                print(
                    f"Daily send limit reached ({successful_today}/{args.daily_limit}); "
                    "remaining messages were not sent."
                )
                break

            msg = build_message(sender, name_from, recipient, subject, body, args.attach)
            try:
                server.send_message(msg)
                log_sent(recipient, "sent")
                successful_today += 1
                print(f"[{i}/{len(todo)}] sent -> {recipient}")
            except Exception as e:  # keep going if one address fails
                log_sent(recipient, f"failed: {e}")
                print(f"[{i}/{len(todo)}] FAILED -> {recipient}: {e}")

            if i < len(todo):
                time.sleep(args.delay + random.randint(0, 15))
    finally:
        if server:
            server.quit()

    return 0


if __name__ == "__main__":
    sys.exit(main())
