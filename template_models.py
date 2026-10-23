"""MailFlow Studio - saved email templates.

This adds ONE new table. The existing tables (user, email log) are not
changed. `db.create_all()` in app.py creates the new table the next time the
app starts, and leaves your existing data alone.
"""

from datetime import datetime, timezone

from models import db


def _utc_now():
    # Saved without a time zone, the same way as the other timestamps.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EmailTemplate(db.Model):
    __tablename__ = "email_template"

    id = db.Column(db.Integer, primary_key=True)
    # Every query in app.py filters on this, so people only see their own.
    user_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)
