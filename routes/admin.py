from flask import Blueprint, current_app
admin_bp = Blueprint('admin', __name__)
from config import ADMIN_CODE_MAX_ATTEMPTS, ADMIN_CODE_RESEND_SECONDS, ADMIN_CODE_TTL_SECONDS
from extensions import db
from models import AdminGrant, AdminVerification, Contact, EmailLog, ScheduledEmail, SiteVisitor, User, UserSuspension
from sqlalchemy import func, or_
from flask_login import current_user, login_required
from flask import abort, flash, redirect, render_template, request, url_for
from datetime import datetime, timedelta, timezone
import hashlib, hmac, re, secrets, smtplib, time
from utils import APP_TIMEZONE_NAME, local_now, to_local, validate_email_address


def admin_email_allowlist():
    granted_emails = db.session.query(AdminGrant.email).all()
    return current_app.config["ADMIN_EMAILS"] | {
        email.casefold() for (email,) in granted_emails
    }


def is_admin_user():
    return (
        current_user.is_authenticated
        and current_user.email.casefold() in admin_email_allowlist()
    )


def require_admin():
    if not is_admin_user():
        abort(404)


def _services():
    return current_app.extensions["mailflow_services"]

@admin_bp.route("/admin")
@login_required
def admin_dashboard():
    if not is_admin_user():
        abort(404)

    today = local_now().date()
    first_day = today - timedelta(days=29)
    visitor_rows = (
        db.session.query(SiteVisitor.visit_date, func.count(SiteVisitor.id))
        .filter(SiteVisitor.visit_date >= first_day)
        .group_by(SiteVisitor.visit_date)
        .all()
    )
    visitor_counts = {
        visit_date: count for visit_date, count in visitor_rows
    }
    daily_visits = [
        {
            "date": first_day + timedelta(days=offset),
            "count": visitor_counts.get(first_day + timedelta(days=offset), 0),
        }
        for offset in range(30)
    ]
    recent_accounts_since = datetime.now(timezone.utc) - timedelta(days=30)

    emails_sent = EmailLog.query.filter_by(status="sent").count()
    emails_failed = EmailLog.query.filter_by(status="failed").count()
    email_activity_rows = (
        db.session.query(EmailLog.status, EmailLog.sent_at)
        .order_by(EmailLog.sent_at.desc())
        .limit(2500)
        .all()
    )
    email_activity_counts = {}
    for status, sent_at in email_activity_rows:
        local_time = to_local(sent_at)
        local_day = local_time.date() if local_time else sent_at.date()
        key = local_day.isoformat()
        bucket = email_activity_counts.setdefault(key, {"sent": 0, "failed": 0})
        if status == "sent":
            bucket["sent"] += 1
        elif status == "failed":
            bucket["failed"] += 1

    daily_email_activity = [
        {
            "date": first_day + timedelta(days=offset),
            "sent": email_activity_counts.get(
                (first_day + timedelta(days=offset)).isoformat(),
                {"sent": 0, "failed": 0},
            )['sent'],
            "failed": email_activity_counts.get(
                (first_day + timedelta(days=offset)).isoformat(),
                {"sent": 0, "failed": 0},
            )['failed'],
        }
        for offset in range(30)
    ]
    stats = {
        "visitors_today": visitor_counts.get(today, 0),
        "visitors_30d": sum(visitor_counts.values()),
        "accounts": User.query.count(),
        "new_accounts_30d": User.query.filter(
            User.created_at >= recent_accounts_since
        ).count(),
        "emails_sent": emails_sent,
        "emails_failed": emails_failed,
        "emails_total": emails_sent + emails_failed,
        "scheduled": ScheduledEmail.query.filter(
            ScheduledEmail.status.in_(("scheduled", "sending"))
        ).count(),
        "contacts": Contact.query.count(),
    }
    account_query = User.query
    account_search = request.args.get("q", "").strip()[:120]
    if account_search:
        escaped_search = (
            account_search.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        account_query = account_query.filter(
            or_(
                User.email.ilike(f"%{escaped_search}%", escape="\\"),
                User.full_name.ilike(f"%{escaped_search}%", escape="\\"),
            )
        )
    accounts_per_page = 50
    account_count = account_query.count()
    total_account_pages = max(
        1,
        (account_count + accounts_per_page - 1) // accounts_per_page,
    )
    account_page = request.args.get("page", 1, type=int) or 1
    account_page = min(max(account_page, 1), total_account_pages)
    users = (
        account_query.order_by(User.created_at.desc(), User.id.desc())
        .offset((account_page - 1) * accounts_per_page)
        .limit(accounts_per_page)
        .all()
    )
    suspended_user_ids = {
        user_id for (user_id,) in db.session.query(UserSuspension.user_id).all()
    }
    admin_emails = admin_email_allowlist()
    admin_users = User.query.filter(User.email.in_(admin_emails)).all()
    current_epoch = int(time.time())
    pending_verification = (
        AdminVerification.query.filter_by(
            admin_user_id=current_user.id,
            consumed=False,
        )
        .filter(AdminVerification.expires_at > current_epoch)
        .order_by(AdminVerification.created_at.desc())
        .first()
    )

    return render_template(
        "admin.html",
        stats=stats,
        daily_visits=daily_visits,
        daily_email_activity=daily_email_activity,
        timezone_name=APP_TIMEZONE_NAME,
        users=users,
        account_search=account_search,
        account_page=account_page,
        total_account_pages=total_account_pages,
        account_count=account_count,
        suspended_user_ids=suspended_user_ids,
        admin_emails=admin_emails,
        admin_users=admin_users,
        bootstrap_admin_emails=current_app.config["ADMIN_EMAILS"],
        admin_grants=AdminGrant.query.order_by(AdminGrant.created_at.desc()).all(),
        pending_verification=pending_verification,
    )


@admin_bp.route("/admin/admins/invite", methods=["POST"])
@login_required
def admin_invite():
    require_admin()

    target_email = request.form.get("email", "").strip().casefold()
    target_user = User.query.filter_by(email=target_email).first()
    if not validate_email_address(target_email) or not target_user:
        flash("Enter the email of an existing MailFlow account.", "error")
        return redirect(url_for("admin.admin_dashboard"))
    if target_email in admin_email_allowlist():
        flash("That account already has administrator access.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    now = int(time.time())
    recent_challenge = (
        AdminVerification.query.filter_by(admin_user_id=current_user.id)
        .filter(
            AdminVerification.created_at
            > now - ADMIN_CODE_RESEND_SECONDS
        )
        .first()
    )
    if recent_challenge:
        flash("Please wait before requesting another verification code.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    code = f"{secrets.randbelow(1_000_000):06d}"
    AdminVerification.query.filter(
        AdminVerification.admin_user_id == current_user.id,
        AdminVerification.consumed.is_(False),
    ).update({"consumed": True}, synchronize_session=False)
    db.session.query(AdminVerification).filter(
        AdminVerification.created_at < now - 24 * 60 * 60
    ).delete(synchronize_session=False)
    challenge = AdminVerification(
        admin_user_id=current_user.id,
        target_email=target_email,
        code_digest=_services().admin_code_digest(current_user.id, target_email, code),
        expires_at=now + ADMIN_CODE_TTL_SECONDS,
        created_at=now,
    )
    db.session.add(challenge)
    db.session.commit()

    primary_email = current_app.config["PRIMARY_ADMIN_EMAIL"]
    primary_admin = User.query.filter_by(email=primary_email).first()
    if not primary_admin or primary_email not in current_app.config["ADMIN_EMAILS"]:
        challenge.consumed = True
        db.session.commit()
        flash("The primary admin email is not configured correctly.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    try:
        _services().send_admin_verification_code(primary_admin, primary_email, code)
    except (RuntimeError, ValueError, OSError, smtplib.SMTPException):
        current_app.logger.exception("Admin verification email could not be sent.")
        challenge.consumed = True
        db.session.commit()
        flash(
            "The verification email could not be sent. Check the primary admin's SMTP settings.",
            "error",
        )
        return redirect(url_for("admin.admin_dashboard"))
    flash("A verification code was sent to the primary admin email.", "success")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/admins/verify", methods=["POST"])
@login_required
def admin_verify_invite():
    require_admin()

    target_email = request.form.get("email", "").strip().casefold()
    code = request.form.get("code", "").strip()
    challenge = (
        AdminVerification.query.filter_by(
            admin_user_id=current_user.id,
            target_email=target_email,
            consumed=False,
        )
        .order_by(AdminVerification.created_at.desc())
        .first()
    )
    now = int(time.time())
    if (
        not challenge
        or challenge.expires_at <= now
        or challenge.attempts >= ADMIN_CODE_MAX_ATTEMPTS
    ):
        flash("The verification code expired or is no longer available.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    is_valid_code = bool(re.fullmatch(r"\d{6}", code))
    if is_valid_code:
        expected_digest = _services().admin_code_digest(current_user.id, target_email, code)
        is_valid_code = hmac.compare_digest(challenge.code_digest, expected_digest)
    if not is_valid_code:
        challenge.attempts += 1
        if challenge.attempts >= ADMIN_CODE_MAX_ATTEMPTS:
            challenge.consumed = True
        db.session.commit()
        flash("The verification code is incorrect.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    target_user = User.query.filter_by(email=target_email).first()
    if not target_user:
        challenge.consumed = True
        db.session.commit()
        flash("That account no longer exists.", "error")
        return redirect(url_for("admin.admin_dashboard"))
    if target_email in admin_email_allowlist():
        challenge.consumed = True
        db.session.commit()
        flash("That account already has administrator access.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    db.session.add(
        AdminGrant(
            email=target_email,
            granted_by_user_id=current_user.id,
        )
    )
    challenge.consumed = True
    db.session.commit()
    flash("Administrator access has been granted.", "success")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/admins/<int:grant_id>/revoke", methods=["POST"])
@login_required
def admin_revoke(grant_id):
    require_admin()

    grant = db.session.get(AdminGrant, grant_id)
    if not grant:
        abort(404)
    if grant.email.casefold() == current_user.email.casefold():
        flash("You cannot revoke your own administrator access.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    db.session.delete(grant)
    db.session.commit()
    flash("Administrator access has been revoked.", "success")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/users/<int:user_id>/suspension", methods=["POST"])
@login_required
def admin_set_user_suspension(user_id):
    require_admin()

    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == current_user.id or user.email.casefold() in admin_email_allowlist():
        flash("Administrator accounts cannot be suspended from this panel.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    suspension = db.session.get(UserSuspension, user.id)
    action = request.form.get("action")
    if action == "suspend" and not suspension:
        db.session.add(
            UserSuspension(
                user_id=user.id,
                suspended_by_user_id=current_user.id,
            )
        )
        db.session.commit()
        flash("The account has been suspended.", "success")
    elif action == "reactivate" and suspension:
        db.session.delete(suspension)
        db.session.commit()
        flash("The account has been reactivated.", "success")
    else:
        abort(400)
    return redirect(url_for("admin.admin_dashboard"))


