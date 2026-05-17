from email_validator import EmailNotValidError, validate_email
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import or_

from .. import db
from ..blueprints import main_bp
from ..database import DegreeOption, User
from .common import (
    get_degree_options_by_category,
    send_reset_email,
    verify_reset_token,
)


# Handle login form display and authentication.
@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter(
            or_(
                User.username == identifier,
                User.email == identifier,
            )
        ).first()

        if user is None or not user.check_password(password):
            flash("Invalid username/email or password.", "error")
            return render_template("loginpage.html")

        login_user(user, remember=remember)
        if not user.onboarding_completed:
            return redirect(url_for("main.onboarding"))
        return redirect(url_for("main.dashboard"))

    return render_template("loginpage.html")


# Start forgot-password flow and send reset email when account exists.
@main_bp.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()

        user = User.query.filter(
            or_(
                User.email == identifier,
                User.username == identifier,
            )
        ).first()

        if user:
            send_reset_email(user)

        flash(
            "If an account exists with that email or username, a reset link has been sent.",
            "info",
        )

        return redirect(url_for("main.login"))

    return render_template("forgot_password.html")


# Validate reset token and set a new password.
@main_bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    email = verify_reset_token(token)

    if not email:
        flash("Invalid or expired reset link.", "error")
        return redirect(url_for("main.forgot_password"))

    user = User.query.filter_by(email=email).first()

    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("main.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not password or password != confirm_password:
            flash("Passwords must match.", "error")
            return redirect(request.url)

        user.set_password(password)
        db.session.commit()

        flash("Password reset successful. Please log in.", "success")
        return redirect(url_for("main.login"))

    return render_template("reset_password.html")


# End the authenticated session.
@main_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))


# Check live availability for register email/username fields.
@main_bp.route("/check_register_details")
def check_register_details():
    email = request.args.get("email", "").strip()
    username = request.args.get("username", "").strip()

    return {
        "email_exists": User.query.filter_by(email=email).first() is not None if email else False,
        "username_exists": User.query.filter_by(username=username).first() is not None if username else False,
    }


# Create a new user account and start onboarding.
@main_bp.route("/register", methods=["GET", "POST"])
def register():
    degree_options = get_degree_options_by_category()

    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip()
        username = request.form.get("username", "").strip()
        degree_type = request.form.get("degree_type", "").strip()
        degree_option_id = request.form.get("degree_option_id", type=int)
        degree = request.form.get("degree", "").strip()
        major = request.form.get("major", "").strip()
        second_major = request.form.get("second_major", "").strip()
        minor = request.form.get("minor", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not first_name or not last_name or not email or not username or not major:
            flash("All required fields must be filled.", "error")
            return render_template("signup.html", degree_options=degree_options)

        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            flash("Invalid email address", "error")
            return render_template("signup.html", degree_options=degree_options)

        if not password or password != confirm_password:
            flash("Password and confirm password must match.", "error")
            return render_template("signup.html", degree_options=degree_options)

        selected_degree_option = None

        if degree_type != "other" and degree_option_id:
            selected_degree_option = DegreeOption.query.filter_by(
                id=degree_option_id,
                is_active=True,
            ).first()

            if selected_degree_option is None:
                flash("Selected degree is invalid.", "error")
                return render_template("signup.html", degree_options=degree_options)

        if selected_degree_option is None and not degree:
            flash("Degree is required.", "error")
            return render_template("signup.html", degree_options=degree_options)

        if User.query.filter_by(email=email).first():
            flash("Email already exists.", "error")
            return render_template("signup.html", degree_options=degree_options)

        if User.query.filter_by(username=username).first():
            flash("Username is already taken.", "error")
            return render_template("signup.html", degree_options=degree_options)

        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            username=username,
            degree=selected_degree_option.name if selected_degree_option else degree,
            degree_option_id=selected_degree_option.id if selected_degree_option else None,
            major=major,
            onboarding_step=1,
            second_major=second_major or None,
            minor=minor or None,
        )

        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        flash("Registration successful. Let's finish setup.", "success")
        return redirect(url_for("main.onboarding"))

    return render_template("signup.html", degree_options=degree_options)
