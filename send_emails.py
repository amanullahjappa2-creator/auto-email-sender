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
import os
import random
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from pathlib import Path
from string import Template

BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "sent_log.csv"


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
        return {row["email"].lower() for row in csv.DictReader(f)}


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
        msg.add_attachment(
            path.read_bytes(),
            maintype="application",
            subtype="pdf",
            filename=path.name,
        )
    return msg


def main() -> int:
    parser = argparse.ArgumentParser(description="Send personalized emails from a CSV.")
    parser.add_argument("--csv", default="recipients.csv")
    parser.add_argument("--template", default="template.txt")
    parser.add_argument("--subject", default="Inquiry about $program at $university")
    parser.add_argument("--attach", help="Optional PDF to attach, e.g. cv.pdf")
    parser.add_argument("--delay", type=int, default=45, help="Base seconds between emails")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()

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

    todo = [r for r in recipients if r.get("email", "").lower() not in done]
    print(f"{len(recipients)} in CSV, {len(recipients) - len(todo)} already sent, {len(todo)} to go.")

    server = None
    if not args.dry_run and todo:
        server = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context())
        server.login(sender, password)

    try:
        for i, row in enumerate(todo, 1):
            try:
                body = template.substitute(row)
                subject = subject_t.substitute(row)
            except KeyError as e:
                print(f"[skip] {row.get('email')}: CSV column {e} missing")
                continue

            if args.dry_run:
                print(f"\n--- [{i}] To: {row['email']} ---\nSubject: {subject}\n\n{body}")
                continue

            msg = build_message(sender, name_from, row["email"], subject, body, args.attach)
            try:
                server.send_message(msg)
                log_sent(row["email"], "sent")
                print(f"[{i}/{len(todo)}] sent -> {row['email']}")
            except Exception as e:  # keep going if one address fails
                log_sent(row["email"], f"failed: {e}")
                print(f"[{i}/{len(todo)}] FAILED -> {row['email']}: {e}")

            if i < len(todo):
                time.sleep(args.delay + random.randint(0, 15))
    finally:
        if server:
            server.quit()

    return 0


if __name__ == "__main__":
    sys.exit(main())
