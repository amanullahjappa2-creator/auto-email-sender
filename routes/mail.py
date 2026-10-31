from flask import Blueprint, current_app
mail_bp = Blueprint('mail', __name__)
from config import INSTANCE_DIR
from extensions import db
from models import Contact, EmailLog, ScheduledEmail
from template_models import EmailTemplate
from compose_tools import ACCEPT_ATTRIBUTE, ALLOWED_LABEL, MAX_FILES, MAX_TOTAL_BYTES, add_files, cleanup_old_drafts, delete_draft, delete_files, draft_dir, extract_addresses, format_size, is_valid_draft_id, list_files, new_draft_id, read_address_file, read_attachments
from flask_login import current_user, login_required
from flask import flash, redirect, render_template, request, url_for
from sqlalchemy import or_
from utils import MAX_BODY, MAX_RECIPIENTS, MAX_SUBJECT, MAX_TEMPLATES, MAX_TEMPLATE_NAME, check_compose, check_template, clean_body, merge_addresses, validate_email_address


def _services():
    return current_app.extensions["mailflow_services"]

@mail_bp.route("/compose", methods=["GET", "POST"])
@login_required
def compose():
    form = {
        "recipient": "",
        "subject": "",
        "body": "",
        "confirmed": False,
        "template_name": "",
    }
    errors = []
    preview = None
    notice = None
    notice_type = "info"
    draft_id = ""

    # Abandoned attachment drafts (older than a day) are removed.
    cleanup_old_drafts(INSTANCE_DIR, current_user.id)

    if request.method == "GET":
        # No email is sent by a GET request.
        contact_id = request.args.get("contact", type=int)
        if contact_id:
            chosen_contact = Contact.query.filter_by(
                id=contact_id,
                user_id=current_user.id,
            ).first()
            if chosen_contact:
                form["recipient"] = chosen_contact.email
                notice = f'Contact "{chosen_contact.name or chosen_contact.email}" added to the recipient list.'
            else:
                notice = "That contact could not be found."

        template_id = request.args.get("template", type=int)
        if template_id:
            chosen = EmailTemplate.query.filter_by(
                id=template_id,
                user_id=current_user.id,
            ).first()
            if chosen:
                form["subject"] = chosen.subject
                form["body"] = chosen.body
                notice = f'Template "{chosen.name}" loaded. Add the recipients, then preview.'
            else:
                notice = "That template could not be found."

    if request.method == "POST":
        action = request.form.get("action", "")
        form["recipient"] = request.form.get("recipient", "").strip()
        form["subject"] = request.form.get("subject", "").strip()
        form["body"] = clean_body(request.form.get("body", ""))
        form["confirmed"] = request.form.get("confirmed") == "yes"
        form["template_name"] = request.form.get("template_name", "").strip()

        draft_id = request.form.get("draft_id", "")
        if not is_valid_draft_id(draft_id):
            draft_id = ""

        if action not in ("preview", "send", "save_template"):
            errors.append(("form", "Please use a valid form button."))

        elif action == "save_template":
            errors = check_template(
                form["template_name"], form["subject"], form["body"]
            )
            if not errors:
                try:
                    saved, created = _services().save_template(
                        form["template_name"], form["subject"], form["body"]
                    )
                except ValueError as exc:
                    errors.append(("template_name", str(exc)))
                else:
                    flash(
                        f'Template "{saved.name}" '
                        f'{"saved" if created else "updated"}.',
                        "success",
                    )
                    return redirect(url_for("mail.compose", template=saved.id))

        else:
            # True when attachments or addresses changed in this request.
            # Such changes must be previewed again before anything is sent.
            changed = False
            folder = draft_dir(INSTANCE_DIR, current_user.id, draft_id) if draft_id else None

            removals = request.form.getlist("remove_attachment")
            if removals and folder and delete_files(folder, removals):
                changed = True

            new_files = [f for f in request.files.getlist("attachments") if f and f.filename]
            if new_files:
                if not draft_id:
                    draft_id = new_draft_id()
                    folder = draft_dir(INSTANCE_DIR, current_user.id, draft_id)
                saved_count, problems = add_files(folder, new_files)
                changed = changed or saved_count > 0
                for problem in problems:
                    errors.append(("attachments", problem))

            address_file = request.files.get("recipient_file")
            if address_file and address_file.filename:
                text, problem = read_address_file(address_file)
                if problem:
                    errors.append(("recipient_file", problem))
                else:
                    found, skipped = extract_addresses(text, validate_email_address)
                    form["recipient"], added = merge_addresses(form["recipient"], found)
                    changed = changed or added > 0
                    notice = (
                        f"Added {added} address(es) from {address_file.filename[:60]}."
                        if added
                        else "No new email addresses were found in that file."
                    )
                    if skipped:
                        notice += f" {skipped} entry(ies) that did not look like addresses were skipped."

            recipients, more_errors = check_compose(form)
            errors.extend(more_errors)

            if action == "send" and not form["confirmed"]:
                errors.append(("confirmed", "Confirm that you checked the email."))

            if action == "send" and changed:
                errors.append(
                    (
                        "form",
                        "You changed the attachments or the address list. "
                        "Select Preview email again before sending.",
                    )
                )

            if not errors:
                files = list_files(folder) if folder else []
                preview = {
                    "recipients": recipients,
                    "count": len(recipients),
                    "subject": form["subject"],
                    "body": form["body"],
                    "words": len(form["body"].split()),
                    "attachments": files,
                }

                if action == "send":
                    try:
                        attachment_data = read_attachments(folder) if folder else []
                        results = _services().send_compose_emails(
                            current_user.id,
                            recipients,
                            form["subject"],
                            form["body"],
                            attachment_data,
                        )
                        sent_count = sum(status == "sent" for _, status in results)
                        failed_count = sum(status == "failed" for _, status in results)

                        if sent_count and not failed_count:
                            flash(
                                f"The mail server accepted all {sent_count} message(s).",
                                "success",
                            )
                        elif sent_count:
                            flash(
                                f"{sent_count} accepted; {failed_count} failed. "
                                "Check your email history.",
                                "info",
                            )
                        else:
                            flash(
                                "No message was confirmed as sent. Check your settings.",
                                "error",
                            )

                        # The attachment copies are no longer needed.
                        if sent_count and folder:
                            delete_draft(folder)
                    except ValueError as exc:
                        db.session.rollback()
                        flash(str(exc), "error")

                    return redirect(url_for("mail.compose"))

    field_errors = {}
    for field, message in errors:
        field_errors.setdefault(field, message)

    attachments = (
        list_files(draft_dir(INSTANCE_DIR, current_user.id, draft_id))
        if draft_id
        else []
    )

    return render_template(
        "compose.html",
        form=form,
        errors=errors,
        field_errors=field_errors,
        preview=preview,
        notice=notice,
        notice_type=notice_type,
        draft_id=draft_id,
        attachments=attachments,
        templates=_services().user_templates(),
        contacts=(
            Contact.query.filter_by(user_id=current_user.id)
            .order_by(Contact.name, Contact.email)
            .limit(5000)
            .all()
        ),
        accept=ACCEPT_ATTRIBUTE,
        limits={
            "subject": MAX_SUBJECT,
            "body": MAX_BODY,
            "max_files": MAX_FILES,
            "max_total": format_size(MAX_TOTAL_BYTES),
            "allowed": ALLOWED_LABEL,
            "max_recipients": MAX_RECIPIENTS,
        },
    )


# ---------------- Templates page ----------------

@mail_bp.route("/templates", methods=["GET", "POST"])
@login_required
def templates_list():
    form = {"template_name": "", "subject": "", "body": ""}
    errors = []

    if request.method == "POST":
        form["template_name"] = request.form.get("template_name", "").strip()
        form["subject"] = request.form.get("subject", "").strip()
        form["body"] = clean_body(request.form.get("body", ""))

        errors = check_template(form["template_name"], form["subject"], form["body"])

        if not errors:
            try:
                saved, created = _services().save_template(
                    form["template_name"], form["subject"], form["body"]
                )
            except ValueError as exc:
                errors.append(("template_name", str(exc)))
            else:
                flash(
                    f'Template "{saved.name}" {"saved" if created else "updated"}.',
                    "success",
                )
                return redirect(url_for("mail.templates_list"))

    field_errors = {}
    for field, message in errors:
        field_errors.setdefault(field, message)

    return render_template(
        "email_templates.html",
        form=form,
        errors=errors,
        field_errors=field_errors,
        templates=_services().user_templates(),
        limits={
            "name": MAX_TEMPLATE_NAME,
            "subject": MAX_SUBJECT,
            "body": MAX_BODY,
            "max_templates": MAX_TEMPLATES,
        },
    )


@mail_bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def template_delete(template_id):
    template = EmailTemplate.query.filter_by(
        id=template_id,
        user_id=current_user.id,
    ).first()

    if template is None:
        flash("That template could not be found.", "error")
    else:
        name = template.name
        db.session.delete(template)
        db.session.commit()
        flash(f'Template "{name}" deleted.', "success")

    return redirect(url_for("mail.templates_list"))


# ---------------- Email history ----------------

@mail_bp.route("/search")
@login_required
def search():
    query = request.args.get("q", "").strip()
    results = {
        "contacts": [],
        "emails": [],
        "scheduled": [],
        "templates": [],
    }
    error = None

    if len(query) > 120:
        error = "Search terms must be 120 characters or fewer."
    elif query:
        pattern = (
            "%"
            + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        results["contacts"] = (
            Contact.query.filter_by(user_id=current_user.id)
            .filter(
                or_(
                    Contact.name.ilike(pattern, escape="\\"),
                    Contact.email.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Contact.name, Contact.email)
            .limit(25)
            .all()
        )
        results["emails"] = (
            EmailLog.query.filter_by(user_id=current_user.id)
            .filter(
                or_(
                    EmailLog.recipient.ilike(pattern, escape="\\"),
                    EmailLog.subject.ilike(pattern, escape="\\"),
                    EmailLog.status.ilike(pattern, escape="\\"),
                )
            )
            .order_by(EmailLog.id.desc())
            .limit(25)
            .all()
        )
        results["scheduled"] = (
            ScheduledEmail.query.filter_by(user_id=current_user.id)
            .filter(
                or_(
                    ScheduledEmail.recipient.ilike(pattern, escape="\\"),
                    ScheduledEmail.subject.ilike(pattern, escape="\\"),
                    ScheduledEmail.status.ilike(pattern, escape="\\"),
                )
            )
            .order_by(ScheduledEmail.scheduled_for.desc())
            .limit(25)
            .all()
        )
        results["templates"] = (
            EmailTemplate.query.filter_by(user_id=current_user.id)
            .filter(
                or_(
                    EmailTemplate.name.ilike(pattern, escape="\\"),
                    EmailTemplate.subject.ilike(pattern, escape="\\"),
                    EmailTemplate.body.ilike(pattern, escape="\\"),
                )
            )
            .order_by(EmailTemplate.updated_at.desc(), EmailTemplate.name)
            .limit(25)
            .all()
        )

    return render_template(
        "search.html",
        query=query,
        results=results,
        error=error,
    )


@mail_bp.route("/history")
@login_required
def history():
    # Always filter by the authenticated user's ID.
    logs = (
        EmailLog.query.filter_by(user_id=current_user.id)
        .order_by(EmailLog.id.desc())
        .limit(200)
        .all()
    )
    return render_template("history.html", logs=logs)


# Database schema creation is handled by Flask-Migrate (`flask db upgrade`).
# Keeping startup free of `create_all()` prevents schema drift in production.


