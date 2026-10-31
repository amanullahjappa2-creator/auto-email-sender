from flask import Blueprint
auth_bp = Blueprint('auth', __name__)
from app import *

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().casefold()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or len(name) > 120:
            flash("Enter your name (up to 120 characters).", "error")
        elif not validate_email_address(email):
            flash("Enter a valid email address.", "error")
        elif len(password) < 12 or len(password) > 128:
            flash("Your password must be between 12 and 128 characters.", "error")
        elif password != confirm_password:
            flash("The passwords do not match.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(full_name=name, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            ensure_sample_templates_for_user(user.id)

            login_user(user)
            flash("Your account has been created. Configure email settings to start sending.", "success")
            return redirect(url_for("settings"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    "5 per minute",
    methods=["POST"],
    exempt_when=lambda: app.config.get("TESTING", False),
)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().casefold()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if db.session.get(UserSuspension, user.id):
                flash("This account is suspended. Contact the site administrator.", "error")
                return render_template("login.html")
            login_user(user)
            destination = request.args.get("next", "")

            # Only allow local application paths as post-login destinations.
            if destination.startswith("/") and not destination.startswith("//"):
                return redirect(destination)

            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------- User email settings ----------------

@auth_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = db.session.get(User, current_user.id)

    if request.method == "POST":
        mail_address = request.form.get("mail_address", "").strip()
        app_password = request.form.get("app_password", "").strip()
        sender_name = request.form.get("sender_name", "").strip()
        smtp_host = request.form.get("smtp_host", "smtp.gmail.com").strip()
        smtp_port_raw = request.form.get("smtp_port", "465").strip()

        try:
            smtp_port = int(smtp_port_raw)
        except ValueError:
            smtp_port = 0

        if not validate_email_address(mail_address):
            flash("Enter a valid Gmail sending address.", "error")
        elif not smtp_host or len(smtp_host) > 255:
            flash("Enter a valid SMTP host.", "error")
        elif not 1 <= smtp_port <= 65535:
            flash("Enter a valid SMTP port.", "error")
        elif len(sender_name) > 120 or "\r" in sender_name or "\n" in sender_name:
            flash("Check your sender name.", "error")
        elif not app_password and not user.encrypted_app_password:
            flash("Enter your Gmail App Password to configure sending.", "error")
        else:
            user.mail_address = mail_address
            user.sender_name = sender_name
            user.smtp_host = smtp_host
            user.smtp_port = smtp_port

            if app_password:
                try:
                    user.encrypted_app_password = encrypt_secret(app_password)
                except (RuntimeError, ValueError):
                    app.logger.exception("Credential encryption failed.")
                    flash("Email settings could not be saved. Check server configuration.", "error")
                    return render_template("settings.html", user=user)

            db.session.commit()
            flash("Your email settings have been saved.", "success")
            return redirect(url_for("settings"))

    return render_template("settings.html", user=user)


# ---------------- Dashboard ----------------

