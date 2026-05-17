from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .. import db
from ..blueprints import main_bp
from ..database import FriendRequest, Notification, User
from .common import get_friend_pair_ids, get_friend_request_between


@main_bp.route("/people")
@login_required
def people():
    query = request.args.get("q", "").strip()
    active_tab = request.args.get("tab", "discover")
    if active_tab not in {"discover", "friends"}:
        active_tab = "discover"

    search_results = []
    if len(query) >= 2:
        matches = (
            User.query.filter(User.id != current_user.id)
            .filter(User.username.ilike(f"{query}%"))
            .order_by(User.username.asc())
            .limit(20)
            .all()
        )

        candidate_ids = [user.id for user in matches]
        relationship_rows = []
        if candidate_ids:
            relationship_rows = FriendRequest.query.filter(
                or_(
                    (FriendRequest.user_low_id == current_user.id) & FriendRequest.user_high_id.in_(candidate_ids),
                    (FriendRequest.user_high_id == current_user.id) & FriendRequest.user_low_id.in_(candidate_ids),
                )
            ).all()

        relationship_map = {}
        for relation in relationship_rows:
            other_user_id = relation.user_high_id if relation.user_low_id == current_user.id else relation.user_low_id
            relationship_map[other_user_id] = relation

        for user in matches:
            relation = relationship_map.get(user.id)
            relation_state = "none"

            if relation is not None:
                if relation.status == "pending":
                    if relation.requested_by_id == current_user.id:
                        relation_state = "outgoing_pending"
                    else:
                        relation_state = "incoming_pending"
                elif relation.status == "accepted":
                    relation_state = "accepted"

            search_results.append(
                {
                    "user": user,
                    "state": relation_state,
                    "friend_request_id": relation.id if relation else None,
                }
            )

    incoming_requests = (
        FriendRequest.query.filter(FriendRequest.status == "pending")
        .filter(FriendRequest.requested_by_id != current_user.id)
        .filter(
            or_(
                FriendRequest.user_low_id == current_user.id,
                FriendRequest.user_high_id == current_user.id,
            )
        )
        .order_by(FriendRequest.created_at.desc())
        .limit(50)
        .all()
    )

    outgoing_requests = (
        FriendRequest.query.filter_by(status="pending", requested_by_id=current_user.id)
        .order_by(FriendRequest.created_at.desc())
        .limit(50)
        .all()
    )

    accepted_relationships = (
        FriendRequest.query.filter_by(status="accepted")
        .filter(
            or_(
                FriendRequest.user_low_id == current_user.id,
                FriendRequest.user_high_id == current_user.id,
            )
        )
        .order_by(FriendRequest.updated_at.desc())
        .limit(50)
        .all()
    )

    def other_user(friend_request):
        other_id = friend_request.user_high_id if friend_request.user_low_id == current_user.id else friend_request.user_low_id
        return db.session.get(User, other_id)

    incoming_payload = [{"request": item, "user": other_user(item)} for item in incoming_requests]
    outgoing_payload = [{"request": item, "user": other_user(item)} for item in outgoing_requests]
    accepted_payload = [{"request": item, "user": other_user(item)} for item in accepted_relationships]

    return render_template(
        "people.html",
        current_user=current_user,
        query=query,
        active_tab=active_tab,
        search_results=search_results,
        incoming_requests=incoming_payload,
        outgoing_requests=outgoing_payload,
        friends=accepted_payload,
    )


@main_bp.route("/friends/request/<int:user_id>", methods=["POST"])
@login_required
def send_friend_request(user_id):
    if user_id == current_user.id:
        flash("You cannot send a friend request to yourself.", "error")
        return redirect(url_for("main.people", tab="discover"))

    target_user = db.session.get(User, user_id)
    if target_user is None:
        flash("User not found.", "error")
        return redirect(url_for("main.people", tab="discover"))

    existing = get_friend_request_between(current_user.id, user_id)
    if existing is None:
        low_id, high_id = get_friend_pair_ids(current_user.id, user_id)
        friend_request = FriendRequest(
            user_low_id=low_id,
            user_high_id=high_id,
            requested_by_id=current_user.id,
            status="pending",
        )
        db.session.add(friend_request)
        db.session.flush()
        db.session.add(
            Notification(
                user_id=target_user.id,
                sender_name=current_user.username,
                type="friend_request",
                message=f"<strong>{current_user.username}</strong> sent you a friend request.",
                channel=f"friend_request:{friend_request.id}",
            )
        )
        db.session.commit()
        flash("Friend request sent.", "success")
        return redirect(url_for("main.people", tab="discover"))

    if existing.status == "pending":
        flash("A friend request is already pending.", "info")
        return redirect(url_for("main.people", tab="discover"))

    if existing.status == "accepted":
        flash("You are already friends.", "info")
        return redirect(url_for("main.people", tab="discover"))

    existing.requested_by_id = current_user.id
    existing.status = "pending"
    db.session.add(
        Notification(
            user_id=target_user.id,
            sender_name=current_user.username,
            type="friend_request",
            message=f"<strong>{current_user.username}</strong> sent you a friend request.",
            channel=f"friend_request:{existing.id}",
        )
    )
    db.session.commit()
    flash("Friend request sent.", "success")
    return redirect(url_for("main.people", tab="discover"))


@main_bp.route("/friends/<int:friend_request_id>/accept", methods=["POST"])
@login_required
def accept_friend_request(friend_request_id):
    friend_request = FriendRequest.query.get_or_404(friend_request_id)

    if friend_request.status != "pending":
        flash("This friend request is no longer pending.", "info")
        return redirect(url_for("main.people", tab="friends"))

    if friend_request.requested_by_id == current_user.id:
        abort(403)

    if current_user.id not in {friend_request.user_low_id, friend_request.user_high_id}:
        abort(403)

    friend_request.status = "accepted"

    requester = db.session.get(User, friend_request.requested_by_id)
    if requester is not None:
        db.session.add(
            Notification(
                user_id=requester.id,
                sender_name=current_user.username,
                type="friend_request",
                message=f"<strong>{current_user.username}</strong> accepted your friend request.",
                channel="friends",
            )
        )

    db.session.commit()
    flash("Friend request accepted.", "success")
    return redirect(url_for("main.people", tab="friends"))


@main_bp.route("/friends/<int:friend_request_id>/reject", methods=["POST"])
@login_required
def reject_friend_request(friend_request_id):
    friend_request = FriendRequest.query.get_or_404(friend_request_id)

    if friend_request.status != "pending":
        flash("This friend request is no longer pending.", "info")
        return redirect(url_for("main.people", tab="friends"))

    if friend_request.requested_by_id == current_user.id:
        abort(403)

    if current_user.id not in {friend_request.user_low_id, friend_request.user_high_id}:
        abort(403)

    friend_request.status = "rejected"
    db.session.commit()
    flash("Friend request rejected.", "info")
    return redirect(url_for("main.people", tab="friends"))


@main_bp.route("/friends/<int:friend_request_id>/cancel", methods=["POST"])
@login_required
def cancel_friend_request(friend_request_id):
    friend_request = FriendRequest.query.get_or_404(friend_request_id)

    if friend_request.status != "pending":
        flash("This friend request is no longer pending.", "info")
        return redirect(url_for("main.people", tab="friends"))

    if friend_request.requested_by_id != current_user.id:
        abort(403)

    if current_user.id not in {friend_request.user_low_id, friend_request.user_high_id}:
        abort(403)

    friend_request.status = "cancelled"
    db.session.commit()
    flash("Friend request cancelled.", "info")
    return redirect(url_for("main.people", tab="friends"))


@main_bp.route("/friends/<int:user_id>/remove", methods=["POST"])
@login_required
def unfriend_user(user_id):
    friend_request = FriendRequest.query.filter_by(status="accepted").filter(
        or_(
            db.and_(
                FriendRequest.user_low_id == current_user.id,
                FriendRequest.user_high_id == user_id,
            ),
            db.and_(
                FriendRequest.user_high_id == current_user.id,
                FriendRequest.user_low_id == user_id,
            ),
        )
    ).first()

    if friend_request is None:
        flash("Friendship not found.", "error")
        return redirect(url_for("main.people", tab="friends"))

    db.session.delete(friend_request)
    db.session.commit()
    flash("Friend removed.", "success")

    return redirect(url_for("main.people", tab="friends"))
