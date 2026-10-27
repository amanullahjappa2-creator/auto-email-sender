# MailFlow Studio startup checklist

## Prerequisites

- Python 3.11+
- A valid `.env` file with secrets configured
- A working SMTP account for sending mail

## Startup

1. Activate the project virtual environment.
2. Install dependencies with `python -m pip install -r requirements.txt`.
3. Run the app with `python app.py`.
4. Optionally use `python app.py --scheduler` for scheduled sends.
5. Verify `/healthz` returns a healthy status.
