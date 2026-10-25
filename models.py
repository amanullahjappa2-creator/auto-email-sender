
"""Database models for MailFlow Studio."""

from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
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


class SiteVisitor(db.Model):
    """One anonymous browser session counted per local calendar day."""

    id = db.Column(db.Integer, primary_key=True)
    visit_date = db.Column(db.Date, nullable=False, index=True)
    visitor_hash = db.Column(db.String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "visit_date",
            "visitor_hash",
            name="uq_site_visitor_date_hash",
        ),
    )


class AdminGrant(db.Model):
    """An administrator granted through the verified admin interface."""

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    granted_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AdminVerification(db.Model):
    """A short-lived, one-use code challenge for granting admin access."""

    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_email = db.Column(db.String(254), nullable=False)
    code_digest = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.Integer, nullable=False, index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    consumed = db.Column(db.Boolean, nullable=False, default=False)


class UserSuspension(db.Model):
    """An administrator-suspended account, without altering the user schema."""

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    suspended_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    suspended_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


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


class Contact(db.Model):
    """A saved recipient belonging to one MailFlow account."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False, default="")
    email = db.Column(db.String(254), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "email", name="uq_contact_user_email"),
    )


class ScheduledEmail(db.Model):
    """An email waiting for delivery by the scheduler worker."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient = db.Column(db.String(5_000), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    scheduled_for = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="scheduled", index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    error_message = db.Column(db.String(255), nullable=True)
