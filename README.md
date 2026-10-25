# MailFlow

[![CI](https://github.com/amanullahjappa2-creator/auto-email-sender/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/amanullahjappa2-creator/auto-email-sender/actions/workflows/ci.yml)

**A Web-Based Email Automation Platform Built with Python and Flask**

MailFlow is a web-based email automation application designed to simplify email composition, recipient management, and email delivery through SMTP.

The project aims to make repetitive email tasks easier with a user-friendly interface, secure credential management, reusable email templates, and efficient recipient handling.

## Overview

MailFlow is being developed as a practical email automation tool for students, developers, and individuals who regularly send emails for professional, academic, and personal purposes.

The application includes user authentication, email account configuration, message composition, individual recipient delivery, an activity dashboard, and email history.

The app also supports saved contacts, CSV contact imports, reusable templates, and scheduled email delivery.

## Features

### Implemented

- **User Authentication:** Account registration, login, and logout.
- **Email Settings:** Configure an SMTP server and personal sending account.
- **Credential Encryption:** Encrypt saved email app passwords using Fernet.
- **Email Composition:** Create messages with a subject and body.
- **Recipient Validation:** Validate addresses, remove duplicates, and support multiple recipients.
- **Individual Delivery:** Send separate messages to recipients without exposing the complete recipient list.
- **Email Preview:** Review recipients and message content before sending.
- **Email History:** View recorded successful and failed sending attempts.
- **Activity Dashboard:** View email statistics, recent activity, and sending status.
- **Contact Management:** Save and remove contacts, or import up to 500 contacts from a CSV file.
- **Scheduled Email Delivery:** Queue text emails for a future time and cancel them before delivery.
- **Security Protections:** Password hashing, CSRF protection, and session security settings.

### Planned

- Multiple file attachments, including PDFs, Word documents, and images.
- Personalized email content using contact information.
- Further testing and usability improvements.

Features listed as planned are not yet represented as completed functionality.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core application logic |
| Flask | Web framework |
| Flask-SQLAlchemy | Database integration |
| SQLite | Local development database |
| Flask-Login | User authentication |
| Flask-WTF | CSRF protection |
| Cryptography | Credential encryption |
| SMTP | Email delivery |
| HTML, CSS, JavaScript | Frontend interface |

## Project Structure

```text
auto-email-sender/
├── app.py
├── config.py
├── models.py
├── security.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── templates/
├── static/
├── instance/
└── send_emails.py
```

This is a simplified overview. The actual directory structure may contain additional files.

## Getting Started

### Requirements

- Python 3.11 or later recommended.
- Git.
- An SMTP-compatible email account.
- An app password or other appropriate SMTP credentials.

### 1. Clone the Repository

```bash
git clone https://github.com/amanullahjappa2-creator/auto-email-sender.git
cd auto-email-sender
```

### 2. Create a Virtual Environment

```bash
python -m venv .venv
```

Activate it on Windows Command Prompt:

```bat
.venv\Scripts\activate.bat
```

### 3. Install Dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a local `.env` file using `.env.example` as a reference.

Configure the required application secrets and settings, including:

- `FLASK_SECRET_KEY`
- `MAIL_SETTINGS_ENCRYPTION_KEY`
- Any SMTP environment variables required by your local setup.

Generate unique secrets locally and never publish real credentials or secret keys:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use the first output for `FLASK_SECRET_KEY` and the second for `MAIL_SETTINGS_ENCRYPTION_KEY`. `COOKIE_SECURE=1` is the secure default and requires HTTPS. For local-only HTTP development, explicitly set `COOKIE_SECURE=0` in your untracked `.env`; do not use that setting in production. VS Code terminal auto-loading of `.env` is disabled in the repository settings.

### 5. Run the Application

```bash
python app.py
```

Open the following address in your browser:

http://127.0.0.1:5000

Register an account, configure email settings, and test sending with an email address you control.

## How It Works

1. Register or sign in to MailFlow.
2. Configure your SMTP sending account.
3. Compose a message and enter recipient addresses.
4. Review the recipient list and message preview.
5. Confirm and send the email.
6. Review the recorded result in Email History.

The current web application sends individual messages to recipients. A server accepting a message does not guarantee delivery to the inbox.

### Scheduled email worker

Scheduled messages are delivered by a separate worker process. Start it in a second terminal alongside the web app:

```bash
python app.py --scheduler
```

The worker checks for due messages every 15 seconds and uses each user's saved SMTP settings. Keep it running for scheduled delivery to occur. Run one worker for this application instance; a message interrupted while sending is marked failed after two hours instead of being sent again automatically, since its delivery outcome may be unknown. The selected send time uses `APP_TIMEZONE` (defaults to `Asia/Karachi`).

### Contacts CSV format

Use a UTF-8 CSV with an `email` column and an optional `name` column:

```csv
name,email
Example Recipient,recipient@example.com
```

You can also use `address` instead of `email`. Duplicate and invalid rows are skipped.

## Security and Responsible Use

MailFlow includes several security measures:

- Passwords are stored as hashes.
- Saved SMTP credentials are encrypted before database storage.
- Authenticated email activity is scoped to the current user.
- CSRF protection is enabled.
- Secret configuration files should remain private.
- Individual recipient messages help protect recipient privacy.

Use MailFlow responsibly. Contact appropriate recipients, respect email provider limits, and comply with applicable privacy and anti-spam requirements.

## Security incident response

Never commit `.env`, the `instance/` directory, local contact or sending CSVs, database files, or private credentials. If sensitive data was already pushed, removing it in a later commit does not remove it from previous Git history, forks, or caches. Rotate the exposed SMTP credentials immediately. Ask repository collaborators to discard old clones, then coordinate a Git-history purge and force-push before treating the old data as removed.

## Development Status

**Status: In active development**

MailFlow is a personal software project being developed incrementally.

The current implementation includes account authentication, email settings, message composition, SMTP sending, a dashboard, email history, saved contacts, reusable templates, and scheduled delivery.

Run the automated security and application tests locally with:

```bash
python -m unittest discover --start-directory tests --verbose
```

## Future Goals

- Complete secure multiple-attachment support.
- Add flexible email personalization.
- Expand automated testing and deployment options.

## Author

**Aman Ullah**

BS Information Technology Student  
Times University, Multan, Pakistan

Interests: Python, Artificial Intelligence, software development, and practical technology solutions.

- GitHub: [amanullahjappa2-creator](https://github.com/amanullahjappa2-creator)
- Email: [amanullahjappa2@gmail.com](mailto:amanullahjappa2@gmail.com)

## License

MailFlow is open-source software licensed under the [MIT License](LICENSE).

You are free to use, copy, modify, merge, publish, distribute, sublicense, and sell copies of the software, subject to the terms and conditions of the MIT License.

See the [LICENSE](LICENSE) file for the complete license text.
