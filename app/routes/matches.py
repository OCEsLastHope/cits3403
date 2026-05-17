from flask import flash, render_template, request
from flask_login import current_user, login_required

from .. import db
from ..blueprints import main_bp
from ..database import Notification, User, UserAvailability
from .common import UNIT_CODE_PATTERN, find_matches, get_degree_options_by_category


@main_bp.route("/matches")
@login_required
def matches():
    selected_degree_option_id = request.args.get("degree_option_id", type=int)
    selected_unit_codes_raw = request.args.get("unit_codes", "")
    selected_unit_codes = []
    invalid_unit_codes = []

    for item in selected_unit_codes_raw.split(","):
        unit_code = item.strip().upper()
        if not unit_code:
            continue
        if not UNIT_CODE_PATTERN.match(unit_code):
            invalid_unit_codes.append(unit_code)
            continue
        if unit_code not in selected_unit_codes:
            selected_unit_codes.append(unit_code)

    if invalid_unit_codes:
        flash("Unit filters must use format AAAA1234.", "error")

    degree_options = get_degree_options_by_category()
    requester = current_user
    match_results = find_matches(requester.id, selected_degree_option_id, selected_unit_codes)

    message = ""
    if not match_results:
        if not UserAvailability.query.filter_by(user_id=requester.id).first():
            message = "Add your availability in Profile to find matches."
        else:
            message = "No matches found with overlapping availability."

    return render_template(
        "matches.html",
        current_user=requester,
        matches=match_results[:10],
        degree_options=degree_options,
        selected_degree_option_id=selected_degree_option_id,
        selected_unit_codes=selected_unit_codes,
        message=message,
    )


@main_bp.route("/matches/ignore/<int:user_id>", methods=["POST"])
@login_required
def ignore_match(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return "", 404

    db.session.add(
        Notification(
            user_id=current_user.id,
            sender_name=user.username,
            type="match",
            message=f"You passed on matching with <strong>{user.username}</strong>.",
            channel="Matches",
            is_read=True,
        )
    )
    db.session.commit()
    return "", 204
