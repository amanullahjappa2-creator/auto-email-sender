# MailFlow

**A Web-Based Email Automation Platform Built with Python and Flask**

MailFlow is a web-based email automation application designed to simplify email composition, recipient management, and email delivery through SMTP.

The project aims to make repetitive email tasks easier with a user-friendly interface, secure credential management, reusable email templates, and efficient recipient handling.

## Overview

MailFlow is being developed as a practical email automation tool for students, developers, and individuals who regularly send emails for professional, academic, and personal purposes.

The application includes user authentication, email account configuration, message composition, individual recipient delivery, an activity dashboard, and email history.

Additional features are being developed to support attachments, saved contacts, reusable templates, and scheduled emails.

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
- **Security Protections:** Password hashing, CSRF protection, and session security settings.

### Planned

- Multiple file attachments, including PDFs, Word documents, and images.
- Contact management with saved recipient details.
- Reusable email templates with editing and saving capabilities.
- Personalized email content using contact information.
- Scheduled email delivery.
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

Generate strong, unique secret values locally. Never publish real credentials or secret keys in your repository.

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

## Security and Responsible Use

MailFlow includes several security measures:

- Passwords are stored as hashes.
- Saved SMTP credentials are encrypted before database storage.
- Authenticated email activity is scoped to the current user.
- CSRF protection is enabled.
- Secret configuration files should remain private.
- Individual recipient messages help protect recipient privacy.

Use MailFlow responsibly. Contact appropriate recipients, respect email provider limits, and comply with applicable privacy and anti-spam requirements.

## Development Status

**Status: In active development**

MailFlow is a personal software project being developed incrementally.

The current implementation includes account authentication, email settings, message composition, SMTP sending, a dashboard, and email history. Multiple attachments, contact management, reusable templates, and scheduled delivery remain planned improvements.

## Future Goals

- Complete secure multiple-attachment support.
- Build a functional contacts page.
- Implement template creation and management.
- Add flexible email personalization.
- Implement reliable scheduled sending.
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
