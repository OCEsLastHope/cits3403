from datetime import datetime

from flask import render_template
from flask_login import login_required

from .. import db
from ..blueprints import main_bp
from ..database import Event, EventAttendee, Invitation, User
from .common import find_matches, get_current_user


@main_bp.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    if not user:
        user = db.session.get(User, 1)

    stats = {
        "total_matches": 0,
        "active_sessions": 0,
        "pending_requests": 0,
    }

    if user:
        all_matches = find_matches(user.id)
        stats["total_matches"] = len(all_matches)
        suggested_matches = all_matches[:3]

        now = datetime.utcnow()
        upcoming_events = (
            Event.query.join(EventAttendee, EventAttendee.event_id == Event.id)
            .filter(Event.status == "scheduled")
            .filter(Event.end_at >= now)
            .filter(EventAttendee.user_id == user.id)
            .filter(EventAttendee.invite_status == "accepted")
            .order_by(Event.start_at.asc())
            .all()
        )
        stats["active_sessions"] = len(upcoming_events)

        pending_study_invites = Invitation.query.filter_by(receiver_id=user.id, status="pending").count()
        pending_event_invites = EventAttendee.query.filter_by(user_id=user.id, invite_status="invited").count()
        stats["pending_requests"] = pending_study_invites + pending_event_invites

    return render_template(
        "dashboard.html",
        current_user=user,
        suggested_matches=suggested_matches,
        upcoming_events=upcoming_events,
        stats=stats,
    )
