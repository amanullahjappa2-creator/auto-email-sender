from flask import Blueprint
scheduled_bp = Blueprint('scheduled', __name__)
from app import *

@scheduled_bp.route("/scheduled", methods=["GET", "POST"])
@login_required
def scheduled():
    errors = []
    form = {
        "recipient": "",
        "subject": "",
        "body": "",
        "scheduled_for": "",
    }

    if request.method == "POST":
        form["recipient"] = request.form.get("recipient", "").strip()
        form["subject"] = request.form.get("subject", "").strip()
        form["body"] = clean_body(request.form.get("body", ""))
        form["scheduled_for"] = request.form.get("scheduled_for", "").strip()

        if not current_user.mail_address or not current_user.encrypted_app_password:
            errors.append(("form", "Connect your sending account in Email Settings before scheduling."))

        recipients, compose_errors = check_compose(form)
        errors.extend(compose_errors)

        try:
            local_schedule = datetime.fromisoformat(form["scheduled_for"])
            if local_schedule.tzinfo is not None:
                raise ValueError
            local_schedule = local_schedule.replace(tzinfo=APP_TZ)
            scheduled_for = local_schedule.astimezone(timezone.utc)
            if local_schedule <= local_now():
                errors.append(("scheduled_for", "Choose a time in the future."))
        except ValueError:
            errors.append(("scheduled_for", "Enter a valid date and time."))

        if not errors:
            db.session.add(
                ScheduledEmail(
                    user_id=current_user.id,
                    recipient=", ".join(recipients),
                    subject=form["subject"],
                    body=form["body"],
                    scheduled_for=scheduled_for,
                )
            )
            db.session.commit()
            flash("Email scheduled. Keep the scheduler worker running to deliver it on time.", "success")
            return redirect(url_for("scheduled"))

    queued = (
        ScheduledEmail.query.filter_by(user_id=current_user.id)
        .order_by(ScheduledEmail.scheduled_for.desc())
        .limit(200)
        .all()
    )
    return render_template(
        "scheduled.html",
        schedules=queued,
        form=form,
        errors=errors,
        min_schedule=local_now().strftime("%Y-%m-%dT%H:%M"),
        clock=clock_parts(local_now()),
        contacts=(
            Contact.query.filter_by(user_id=current_user.id)
            .order_by(Contact.name, Contact.email)
            .limit(5000)
            .all()
        ),
    )


@scheduled_bp.route("/scheduled/<int:schedule_id>/cancel", methods=["POST"])
@login_required
def cancel_schedule(schedule_id):
    schedule = ScheduledEmail.query.filter_by(
        id=schedule_id,
        user_id=current_user.id,
        status="scheduled",
    ).first()
    if schedule is None:
        flash("That email is no longer waiting and cannot be cancelled.", "error")
    else:
        db.session.delete(schedule)
        db.session.commit()
        flash("Scheduled email cancelled.", "success")
    return redirect(url_for("scheduled"))


# ---------------- Saved templates ----------------

