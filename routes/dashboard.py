from flask import Blueprint
dashboard_bp = Blueprint('dashboard', __name__)
from app import APP_TIMEZONE_NAME, accepted_rate, build_week, clock_parts, first_name_of, greeting_for, local_now, setup_status, to_local, validate_email_address
from extensions import db
from models import Contact, EmailLog, ScheduledEmail
from flask_login import current_user, login_required
from flask import abort, flash, redirect, render_template, request, url_for
import csv, io

@dashboard_bp.route("/")
@login_required
def dashboard():
    now = local_now()

    sent_count = EmailLog.query.filter_by(
        user_id=current_user.id,
        status="sent",
    ).count()

    failed_count = EmailLog.query.filter_by(
        user_id=current_user.id,
        status="failed",
    ).count()

    unique_contacts = Contact.query.filter_by(user_id=current_user.id).count()
    scheduled_count = ScheduledEmail.query.filter(
        ScheduledEmail.user_id == current_user.id,
        ScheduledEmail.status.in_(("scheduled", "sending")),
    ).count()

    # One query feeds the 7-day chart and the "last email" row.
    # It is always filtered by the logged-in user's ID.
    recent_logs = (
        EmailLog.query.filter_by(user_id=current_user.id)
        .order_by(EmailLog.id.desc())
        .limit(5000)
        .all()
    )

    week = build_week(recent_logs, now)
    last_time = to_local(recent_logs[0].sent_at) if recent_logs else None

    return render_template(
        "dashboard.html",
        greeting=greeting_for(now),
        clock=clock_parts(now),
        clock_tz=APP_TIMEZONE_NAME,
        today_sent=week["days"][-1]["sent"],
        rate=accepted_rate(sent_count, failed_count),
        last_time=last_time,
        first_name=first_name_of(current_user),
        post_day=now.day,
        post_month=now.strftime("%b"),
        post_year=now.year,
        stats={
            "sent": sent_count,
            "scheduled": scheduled_count,
            "contacts": unique_contacts,
            "failed": failed_count,
        },
        week=week,
        last_email=recent_logs[0] if recent_logs else None,
        setup=setup_status(current_user, sent_count + failed_count),
    )


@dashboard_bp.route("/contacts", methods=["GET", "POST"])
@login_required
def contacts():
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            if len(name) > 120 or "\n" in name or "\r" in name:
                flash("Keep the contact name to one line and under 120 characters.", "error")
            elif not validate_email_address(email):
                flash("Enter a valid email address.", "error")
            else:
                normalized_email = email.casefold()
                exists = Contact.query.filter_by(
                    user_id=current_user.id,
                    email=normalized_email,
                ).first()
                if exists:
                    flash("That email address is already in your contacts.", "info")
                else:
                    db.session.add(
                        Contact(
                            user_id=current_user.id,
                            name=name,
                            email=normalized_email,
                        )
                    )
                    db.session.commit()
                    flash("Contact saved.", "success")

        elif action == "import":
            upload = request.files.get("contact_file")
            if not upload or not upload.filename:
                flash("Choose a CSV file to import.", "error")
            else:
                content = upload.stream.read(1_000_001)
                if len(content) > 1_000_000:
                    flash("The CSV file must be smaller than 1 MB.", "error")
                else:
                    try:
                        reader = csv.DictReader(
                            io.StringIO(content.decode("utf-8-sig"), newline="")
                        )
                        headers = {
                            (header or "").strip().casefold(): header
                            for header in (reader.fieldnames or [])
                        }
                        email_key = headers.get("email") or headers.get("address")
                        name_key = headers.get("name") or headers.get("full name")
                        if not email_key:
                            flash("The CSV needs an 'email' or 'address' column.", "error")
                        else:
                            existing = {
                                email
                                for (email,) in db.session.query(Contact.email)
                                .filter_by(user_id=current_user.id)
                                .all()
                            }
                            added = skipped = 0
                            for row_number, row in enumerate(reader, start=2):
                                if row_number > 501:
                                    skipped += 1
                                    continue
                                email = (row.get(email_key) or "").strip().casefold()
                                name = (row.get(name_key) or "").strip() if name_key else ""
                                if (
                                    not validate_email_address(email)
                                    or len(name) > 120
                                    or "\n" in name
                                    or "\r" in name
                                    or email in existing
                                ):
                                    skipped += 1
                                    continue
                                db.session.add(
                                    Contact(
                                        user_id=current_user.id,
                                        name=name,
                                        email=email,
                                    )
                                )
                                existing.add(email)
                                added += 1
                            db.session.commit()
                            flash(
                                f"Imported {added} contact(s); skipped {skipped} invalid or duplicate row(s).",
                                "success" if added else "info",
                            )
                    except (UnicodeDecodeError, csv.Error):
                        db.session.rollback()
                        flash("The uploaded file is not a readable UTF-8 CSV.", "error")
        else:
            abort(400)

        return redirect(url_for("contacts"))

    saved_contacts = (
        Contact.query.filter_by(user_id=current_user.id)
        .order_by(Contact.name, Contact.email)
        .limit(5000)
        .all()
    )
    return render_template("contacts.html", contacts=saved_contacts)


@dashboard_bp.route("/contacts/<int:contact_id>/delete", methods=["POST"])
@login_required
def delete_contact(contact_id):
    contact = Contact.query.filter_by(
        id=contact_id,
        user_id=current_user.id,
    ).first_or_404()
    db.session.delete(contact)
    db.session.commit()
    flash("Contact deleted.", "success")
    return redirect(url_for("contacts"))


