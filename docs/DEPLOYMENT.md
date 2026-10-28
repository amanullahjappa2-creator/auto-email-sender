# Deployment guide

## Local development

1. Copy `.env.example` to `.env`.
2. Set `FLASK_SECRET_KEY` and `MAIL_SETTINGS_ENCRYPTION_KEY`.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Start the app with `python app.py`.

## Production notes

- Keep `.env` outside source control.
- Use a strong secret key and stable Fernet key.
- Run a scheduler worker if scheduled emails are required.
- Use HTTPS in front of Flask when exposing the app publicly.
