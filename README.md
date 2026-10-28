# MailFlow Studio

[![CI](https://github.com/amanullahjappa2-creator/auto-email-sender/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/amanullahjappa2-creator/auto-email-sender/actions/workflows/ci.yml)

MailFlow Studio is a self-hosted Flask application for writing and sending
individual emails, managing contacts, reusing templates, and scheduling
messages. Each recipient receives a separate email; recipients are not shown
each other's addresses.

Built by **AmanUllah**.

## Features

- **Private accounts:** Register, sign in, and manage data scoped to your account.
- **Personal SMTP settings:** Configure the sending address, sender display
  name, SMTP host, port, and SMTP credential for your account. Gmail is the
  default provider and uses an App Password.
- **Encrypted credentials:** The saved SMTP App Password is encrypted with
  Fernet before it is stored in the database.
- **Compose and preview:** Review the subject, message, recipients, and
  attachments before confirming delivery.
- **Individual delivery:** Send to up to 120 validated recipients, one message
  per recipient.
- **Recipient lists:** Add addresses from a CSV or TXT file up to 200 KB;
  duplicate addresses are omitted and invalid addresses are skipped.
- **Attachments:** Attach up to five PDF, Office, text, CSV, JPG, or PNG files,
  with a combined size limit of 10 MB. Binary file signatures are checked,
  and files are held in private draft storage until sending.
- **Contacts:** Save and delete contacts, select saved contacts while
  composing or scheduling, and import UTF-8 CSV files. Imports accept up to
  500 rows and 1 MB per file; use an `email` or `address` column and an
  optional `name` or `full name` column.
- **Reusable templates:** Every account gets ten built-in starter templates.
  Create and manage up to 50 templates per account; loading one copies its
  subject and message into Compose for editing before sending.
- **Scheduled email:** Queue a message for a future time, review its status,
  and cancel it before delivery. A separate worker polls for due messages
  every 15 seconds and must be running for scheduled delivery.
- **Workspace search:** Search your own contacts, email history, scheduled
  messages, and templates from the top-bar search or with `Ctrl+K` (`Cmd+K` on
  macOS). Search results are account-scoped and capped at 25 per category.
- **Activity and insights:** View your dashboard, delivery statistics, recent
  activity, and up to 200 recent email-history records.
- **Admin panel:** Allowlisted administrators can view app-wide email totals
  and daily activity, account counts and basic account details, and suspend or
  reactivate non-admin accounts. Email content and SMTP credentials are not
  shown.
- **Light and dark themes:** Choose a theme in the interface; the preference is
  stored in your browser.
- **Security protections:** Password hashing, CSRF protection, secure session
  cookie options, security response headers, and per-account data access.

SMTP server acceptance is not a guarantee that a message reaches the
recipient's inbox. Delivery can be delayed, filtered, or rejected by the
recipient's provider.

## Project health and polish

This project is organized around safe defaults, real privacy protections, and
clear operational workflow for deployment and maintenance. It includes:

- a private `.env` setup for sensitive credentials
- a database-backed admin panel with admin verification and account
  suspension controls
- health monitoring via `/healthz`
- secure headers and request-size controls
- a quick health probe script in [scripts/check_app_health.py](scripts/check_app_health.py)
- contributor guidance in [CONTRIBUTING.md](CONTRIBUTING.md)
- a clear security reporting process in [SECURITY.md](SECURITY.md)

For roadmap and future milestones, see [docs/ROADMAP.md](docs/ROADMAP.md).

## Requirements

- Python 3.11, 3.12, or 3.13
- An SMTP account and credentials authorized for SMTP sending
- Git

The default development database is SQLite. Set `DATABASE_URL` to use another
SQLAlchemy-supported database; PostgreSQL's `psycopg` driver is included in
the requirements.

## Local development

### 1. Get the source and create an environment

```bash
git clone https://github.com/amanullahjappa2-creator/auto-email-sender.git
cd auto-email-sender
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bat
:: Windows Command Prompt
.venv\Scripts\activate.bat
```

```bash
# macOS / Linux
source .venv/bin/activate
```

### 2. Install dependencies and configure secrets

```bash
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and generate **your own** secrets locally:

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the first generated value in `FLASK_SECRET_KEY` and the second in
`MAIL_SETTINGS_ENCRYPTION_KEY` in your local `.env` file. Do not use the
example placeholder values as real secrets, share `.env`, or commit it.
`FLASK_SECRET_KEY` must be at least 32 characters. Keep the encryption key
stable and backed up securely: changing or losing it prevents the app from
decrypting SMTP credentials already saved in the database.

Available environment settings:

| Variable | Required | Default | Purpose |
|---|---:|---|---|
| `FLASK_SECRET_KEY` | Yes | — | Signs Flask sessions; provide at least 32 random characters. |
| `MAIL_SETTINGS_ENCRYPTION_KEY` | Yes | — | Fernet key used to encrypt saved SMTP credentials. |
| `COOKIE_SECURE` | No | `1` | Enables `Secure` session cookies. Keep enabled over HTTPS. For local HTTP development only, set `COOKIE_SECURE=0` in `.env`. |
| `APP_TIMEZONE` | No | `Asia/Karachi` | Time zone used to display dates and interpret scheduled send times. |
| `ADMIN_EMAILS` | No | — | Comma-separated bootstrap admin account emails; keep this to the primary owner account. |
| `PRIMARY_ADMIN_EMAIL` | No | — | Registered primary admin email that receives every admin-grant verification code. |
| `DATABASE_URL` | No | Local SQLite database | SQLAlchemy database connection URL. |
| `FLASK_DEBUG` | No | `0` | Set to `1` only for local development. Never enable debug mode in production. |

The `.env` file is loaded by the application and ignored by Git. VS Code
terminal auto-loading of `.env` is disabled in the repository settings.

Set both `ADMIN_EMAILS` and `PRIMARY_ADMIN_EMAIL` in your private `.env` file
to the already registered primary owner's account email, then restart the app.
Keep the bootstrap list limited to the owner; additional admins should be
granted from **Admin panel** instead of editing code or environment settings.
Only signed-in allowlisted admins can open `/admin`.

The panel shows account-wide usage totals and daily anonymous browser-session
counts. It also lets admins view basic account details and suspend/reactivate
non-admin accounts. It never displays SMTP credentials or email contents.
Suspension blocks sign-in and sending; reactivation restores access. To grant
another admin, enter the email of an existing MailFlow account. A six-digit
single-use code is sent to `PRIMARY_ADMIN_EMAIL` using that account's
configured SMTP settings. The code expires after 10 minutes, has a
five-attempt limit, and resends are rate-limited. Verified grants can be
revoked from the panel; the environment bootstrap admin cannot be revoked
there. Visitor counts are estimates of distinct browser sessions per day, not
people; IP addresses are not stored and anonymous daily records are retained
for 90 days.

### 3. Start the web app and scheduled-email worker

The app supports host/port overrides with environment variables or command-line
flags:

```bash
FLASK_HOST=0.0.0.0 FLASK_PORT=8000 python app.py
python app.py --host=0.0.0.0 --port=8000
python app.py --version
```

On Windows, start both required processes from PowerShell in the project
directory:

```powershell
.\start_mailflow.ps1
```

The script starts the web app and one scheduler worker as separate processes
preferring `.venv\Scripts\python.exe` when present, and verifies both remain
running during startup. It prints both process IDs. Keep both running while
using the app. Stop them when finished with the printed command, for example:

```powershell
Stop-Process -Id 1234, 5678
```

On macOS/Linux, or if you prefer to start processes manually, use two terminals
with the same virtual environment and project directory:

```bash
python app.py
```

```bash
python app.py --scheduler
```

To process a single batch of up to 20 due messages and then exit, run:

```bash
python app.py --scheduler-once
```

Open <http://127.0.0.1:5000>, create an account, then open **Email Settings**
to add your sending account. Gmail users should use an App Password, not their
normal Gmail password. The default SMTP server is `smtp.gmail.com` on SSL port
`465`; the account's SMTP host and port can be changed in settings.

The local server binds to `127.0.0.1` and is intended for development, not
direct public exposure.

The worker polls for due messages every 15 seconds. Keep exactly one worker
running for an application instance and keep it running for scheduled delivery.
Scheduled times use `APP_TIMEZONE`. If sending is interrupted and the outcome
is unknown, the application does not automatically retry the message; an
interrupted send is marked failed after two hours to avoid accidental duplicate
delivery.

## Using the application

1. **Create an account** and sign in.
2. **Configure Email Settings** with your SMTP sending account and App
   Password.
3. **Add contacts** manually or import them from CSV, if useful.
4. **Compose an email:** enter recipients, subject, and message; optionally
   attach files or start from a saved template.
5. **Preview and confirm** the message before it is sent. Multiple addresses
   receive separate messages.
6. **Schedule** a message from the Scheduled page when it should be delivered
   later; make sure the worker is running.
7. Review results in **History** and delivery summaries on the dashboard.

### Contact CSV example

Save a UTF-8 CSV with a header row:

```csv
name,email
Example Recipient,recipient@example.com
```

The address column may be named `email` or `address`; the optional name column
may be `name` or `full name`. Duplicate, invalid, and excess rows are skipped.

### Templates

Every account receives ten built-in starter templates at registration. Loading
a template copies its name, subject, and message body—not recipients or
attachments—into Compose. You can edit the content and preview it before
sending. Placeholders in a template are plain text for you to replace;
contact details are not automatically substituted. Accounts can hold up to
50 templates in total.

The seeding script is available to add missing starter templates across all
existing accounts in a database:

```bash
python add_sample_templates.py
```

It adds missing samples and refreshes only an unchanged legacy sample body;
user-edited sample content is preserved.

## Optional standalone CSV sender

`send_emails.py` is a separate command-line utility; it does not use the
MailFlow web app's per-account settings, database, or scheduled queue. It reads
`recipients.csv` and `template.txt` from the current directory by default and
uses `$column_name` placeholders from CSV headers in the subject and message.
It keeps a local `sent_log.csv` to skip recipients already logged as sent.

For example, first preview without sending:

```bash
python send_emails.py --dry-run
```

To send, configure these values in a private `.env` file:

| Variable | Required for sending | Default | Purpose |
|---|---:|---|---|
| `EMAIL_ADDRESS` | Yes | — | SMTP sender address. |
| `EMAIL_APP_PASSWORD` | Yes | — | SMTP account password or provider App Password. |
| `SMTP_HOST` | No | `smtp.gmail.com` | SMTP server hostname. |
| `SMTP_PORT` | No | `465` | SSL SMTP port. |
| `SENDER_NAME` | No | Empty | Optional display name. |

Then run `python send_emails.py`. Options include `--csv`, `--template`,
`--subject`, `--delay`, and `--attach`; see `python send_emails.py --help`.
The optional attachment is treated as a PDF. This utility sends real email
when run without `--dry-run`; use only with recipients you are authorized to
contact. Its `sent_log.csv` and recipient data are private local files—do not
commit them.

## Production deployment

Deploy on a supported server behind an HTTPS-terminating reverse proxy. For
example, on Linux, Gunicorn is included in `requirements.txt`:

```bash
gunicorn --bind 127.0.0.1:8000 app:app
```

Run `python app.py --scheduler` as a separate supervised process on the same
application release and database. Do not run multiple scheduler workers for
the same deployment.

Before exposing an instance:

- Set unique, strong `FLASK_SECRET_KEY` and
  `MAIL_SETTINGS_ENCRYPTION_KEY` values in the host's secret manager or
  protected environment—not in source control.
- Preserve the encryption key across restarts and backups. Restrict access to
  database files, backups, and the instance directory.
- Set `COOKIE_SECURE=1`, use HTTPS, and keep debug mode disabled.
- Configure a persistent `DATABASE_URL` and durable private storage for the
  database and attachment drafts. Local SQLite is suitable for development,
  not every multi-worker production deployment.
- Back up application data securely and test restore procedures. Use database
  migrations for production schema changes; the app's `create_all()` startup
  initialization is not a migration system.
- Follow your SMTP provider's sending limits and applicable privacy,
  consent, and anti-spam requirements.

The app provides security features but does not by itself guarantee a secure
deployment. Protect the host, secrets, database, backups, and SMTP account.

## Development and tests

Run the automated application and security regression tests:

```bash
python -m unittest discover --start-directory tests --verbose
```

GitHub Actions runs this test suite on Python 3.11, 3.12, and 3.13 for pushes
and pull requests targeting `main`.

## Project layout

```text
.
├── app.py                    # Flask routes, mail delivery, and scheduler worker
├── config.py                 # Environment-based application configuration
├── models.py                 # User, contact, history, and scheduled-email models
├── template_models.py        # Saved email-template model
├── security.py               # SMTP credential encryption
├── compose_tools.py          # Attachment and recipient-file handling
├── add_sample_templates.py   # Seed or refresh samples for all accounts
├── send_emails.py            # Standalone command-line email sender
├── templates/                # Jinja pages
├── static/                   # CSS, JavaScript, and theme assets
├── tests/                    # Application and security regression tests
└── .github/workflows/ci.yml  # GitHub Actions test workflow
```

## Security and responsible use

- Passwords are hashed; SMTP App Passwords are encrypted at rest using the
  configured Fernet key.
- Authenticated pages and database queries are scoped to the signed-in user.
- CSRF protection and security headers are enabled.
- Session cookies are `HttpOnly` and `SameSite=Lax`; `Secure` follows
  `COOKIE_SECURE`.
- On POSIX systems, the application restricts permissions on its instance
  directory, SQLite database, and attachment draft storage.
- `.env`, `instance/`, local databases, recipient files, logs, and private key
  files are excluded by `.gitignore`. Review staged files before every push.

Use this application only for messages you are authorized to send. Respect
recipient privacy, provider policies, and local laws. If credentials or
personal data are exposed, revoke or rotate affected credentials immediately;
removing a file in a later commit does not remove it from Git history, clones,
or caches.

## License

MailFlow Studio is licensed under the [MIT License](LICENSE).
