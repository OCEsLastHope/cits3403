from flask import abort, render_template
from flask_login import current_user, login_required
from sqlalchemy import or_

from .. import db
from ..blueprints import main_bp
from ..database import FriendRequest, Invitation, Notification


@main_bp.route("/notifications")
@login_required
def notifications():
    user = current_user
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    pending_invites = Invitation.query.filter_by(receiver_id=current_user.id, status="pending").all()
    pending_invite_map = {invite.sender.username: invite.id for invite in pending_invites}
    incoming_friend_requests = (
        FriendRequest.query.filter_by(status="pending")
        .filter(FriendRequest.requested_by_id != current_user.id)
        .filter(
            or_(
                FriendRequest.user_low_id == current_user.id,
                FriendRequest.user_high_id == current_user.id,
            )
        )
        .all()
    )
    pending_friend_request_ids = {friend_request.id for friend_request in incoming_friend_requests}
    return render_template(
        "notifications.html",
        current_user=user,
        notifications=notifs,
        pending_invites=pending_invites,
        pending_invite_map=pending_invite_map,
        pending_friend_request_ids=pending_friend_request_ids,
        unread_count=sum(1 for n in notifs if not n.is_read),
        dm_count=sum(1 for n in notifs if n.type == "dm" and not n.is_read),
        friend_request_count=sum(1 for n in notifs if n.type == "friend_request" and not n.is_read),
    )


@main_bp.route("/notifications/read/<int:notif_id>", methods=["POST"])
@login_required
def mark_read(notif_id):
    n = Notification.query.get_or_404(notif_id)
    if n.user_id != current_user.id:
        abort(403)
    n.is_read = True
    db.session.commit()
    return "", 204


@main_bp.route("/notifications/read/all", methods=["POST"])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return "", 204
