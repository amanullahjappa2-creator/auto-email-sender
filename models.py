
"""Database models for MailFlow Studio."""

from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """A registered MailFlow Studio user."""

    id = db.Column(db.Integer, primary_key=True)

    # Website account details
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(
        db.String(254),
        unique=True,
        index=True,
        nullable=False,
    )
    password_hash = db.Column(db.String(255), nullable=False)

    # Each user configures their own email-sending account.
    mail_address = db.Column(db.String(254), nullable=True)
    encrypted_app_password = db.Column(db.Text, nullable=True)

    smtp_host = db.Column(
        db.String(255),
        nullable=False,
        default="smtp.gmail.com",
    )
    smtp_port = db.Column(
        db.Integer,
        nullable=False,
        default=465,
    )
    sender_name = db.Column(db.String(120), nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Every email log belongs to exactly one user.
    email_logs = db.relationship(
        "EmailLog",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def set_password(self, password: str) -> None:
        """Store a secure hash of the website login password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check a website login password."""
        return check_password_hash(self.password_hash, password)


class EmailLog(db.Model):
    """Email activity belonging to one specific user."""

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    recipient = db.Column(db.String(254), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False)

    sent_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", back_populates="email_logs")
