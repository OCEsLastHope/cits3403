from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..blueprints import main_bp
from ..database import Notification
from .common import (
    ONBOARDING_STEP_COPY,
    ONBOARDING_STEP_ENDPOINTS,
    can_finish_onboarding,
    get_onboarding_step_for_user,
    get_onboarding_target_endpoint,
)


@main_bp.app_context_processor
def inject_onboarding_guide():
    unread_notifications = 0
    if current_user.is_authenticated:
        unread_notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()

    if not current_user.is_authenticated or current_user.onboarding_completed:
        return {
            "onboarding_guide": None,
            "unread_notifications": unread_notifications,
        }

    step = get_onboarding_step_for_user(current_user)
    target_endpoint = f"main.{ONBOARDING_STEP_ENDPOINTS[step]}"
    if request.endpoint != target_endpoint:
        return {
            "onboarding_guide": None,
            "unread_notifications": unread_notifications,
        }

    return {
        "onboarding_guide": {
            "step": step,
            "total_steps": len(ONBOARDING_STEP_ENDPOINTS),
            "message": ONBOARDING_STEP_COPY.get(step, ""),
            "show_finish": step == len(ONBOARDING_STEP_ENDPOINTS) and can_finish_onboarding(current_user),
            "can_finish": can_finish_onboarding(current_user),
        },
        "unread_notifications": unread_notifications,
    }


@main_bp.before_app_request
def require_onboarding_completion():
    if not current_user.is_authenticated or current_user.onboarding_completed:
        return None
    if request.endpoint is None:
        return None

    onboarding_nav_endpoints = {f"main.{endpoint}" for endpoint in ONBOARDING_STEP_ENDPOINTS.values()}
    allowed_endpoints = {
        "main.onboarding",
        "main.onboarding_advance",
        "main.logout",
        "main.search_units",
        "main.search_majors",
        "main.search_minors",
        "static",
    }.union(onboarding_nav_endpoints)
    if request.endpoint in allowed_endpoints:
        return None

    target_endpoint = f"main.{get_onboarding_target_endpoint(current_user)}"
    if request.endpoint != target_endpoint:
        return redirect(url_for(target_endpoint))
    return None


@main_bp.route("/onboarding", methods=["GET"])
@login_required
def onboarding():
    if current_user.onboarding_completed:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for(f"main.{get_onboarding_target_endpoint(current_user)}"))


@main_bp.route("/onboarding/advance", methods=["POST"])
@login_required
def onboarding_advance():
    if current_user.onboarding_completed:
        return redirect(url_for("main.dashboard"))
    action = request.form.get("action", "next")
    step = get_onboarding_step_for_user(current_user)
    max_step = len(ONBOARDING_STEP_ENDPOINTS)
    if action == "back":
        current_user.onboarding_step = max(1, step - 1)
    elif action == "finish":
        if not can_finish_onboarding(current_user):
            flash(
                "Before finishing, ensure degree is set and add valid units (max 6, unique UWA codes) plus at least one availability slot in Profile.",
                "error",
            )
            current_user.onboarding_step = max_step
            db.session.commit()
            return redirect(url_for("main.profile"))
        current_user.onboarding_completed = True
        db.session.commit()
        flash("Onboarding complete. Welcome to StudyCollabz!", "success")
        return redirect(url_for("main.dashboard"))
    else:
        current_user.onboarding_step = min(max_step, step + 1)
    db.session.commit()
    return redirect(url_for(f"main.{get_onboarding_target_endpoint(current_user)}"))
