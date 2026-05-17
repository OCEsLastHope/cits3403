from datetime import datetime

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..blueprints import main_bp
from ..database import Conversation, ConversationMember, Invitation, Notification, User


@main_bp.route("/invitations/send<int:receiver_id>", methods=["POST"])
@login_required
def send_invitation(receiver_id):
    receiver = db.session.get(User, receiver_id)
    if receiver is None:
        return "User not found", 404

    if receiver.id == current_user.id:
        return "You are unable to invite yourself.", 400

    existing = Invitation.query.filter_by(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        status="pending",
    ).first()

    if existing:
        flash("Invitation already sent.", "info")
        return redirect(request.referrer or url_for("main.matches"))

    message_text = request.form.get("message", "").strip()

    invite = Invitation(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        message=message_text or None,
    )

    db.session.add(invite)

    notif = Notification(
        user_id=receiver_id,
        sender_name=current_user.username,
        type="dm",
        message=f"<strong>{current_user.username}</strong> wants to message you.",
        channel="Invitations",
    )

    db.session.add(notif)
    db.session.commit()

    flash("Invitation sent!", "success")
    return redirect(request.referrer or url_for("main.matches"))


@main_bp.route("/invitations/<int:invite_id>/accept", methods=["POST"])
@login_required
def accept_invitation(invite_id):
    invite = Invitation.query.get_or_404(invite_id)

    if invite.receiver_id != current_user.id:
        abort(403)

    if invite.status != "pending":
        flash("This invitation has already been responded to.", "info")
        return redirect(url_for("main.notifications"))

    invite.status = "accepted"
    invite.responded_at = datetime.utcnow()

    existing_conversations = (
        Conversation.query.join(ConversationMember)
        .filter(
            Conversation.is_group_chat.is_(False),
            ConversationMember.user_id == current_user.id,
        )
        .all()
    )

    conversation = None
    for conv in existing_conversations:
        member_ids = {member.user_id for member in conv.members}
        if member_ids == {current_user.id, invite.sender_id}:
            conversation = conv
            break

    if conversation is None:
        conversation = Conversation(is_group_chat=False)
        db.session.add(conversation)
        db.session.flush()
        db.session.add(ConversationMember(conversation_id=conversation.id, user_id=current_user.id))
        db.session.add(ConversationMember(conversation_id=conversation.id, user_id=invite.sender_id))

    notif = Notification(
        user_id=invite.sender_id,
        sender_name=current_user.username,
        type="match",
        message=f"<strong>{current_user.username}</strong> accepted your study invite!",
        channel=f"Conversation {conversation.id}",
    )

    db.session.add(notif)
    db.session.commit()

    flash("Invitation accepted!", "success")
    return redirect(url_for("main.messages", conversation_id=conversation.id))


@main_bp.route("/invitations/<int:invite_id>/reject", methods=["POST"])
@login_required
def reject_invitation(invite_id):
    invite = Invitation.query.get_or_404(invite_id)

    if invite.receiver_id != current_user.id:
        abort(403)

    if invite.status != "pending":
        flash("This invitation has already been responded to.", "info")
        return redirect(url_for("main.notifications"))

    invite.status = "rejected"
    invite.responded_at = datetime.utcnow()

    Notification.query.filter_by(
        user_id=current_user.id,
        sender_name=invite.sender.username,
        channel="Invitations",
        type="dm",
        is_read=False,
    ).update({"is_read": True})

    db.session.commit()

    flash("Invitation declined.", "info")
    return redirect(url_for("main.notifications"))
