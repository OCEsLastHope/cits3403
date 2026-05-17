from flask import abort, redirect, render_template, url_for
from flask_login import current_user, login_required

from .. import db, socketio
from ..blueprints import main_bp
from ..database import Conversation, ConversationMember, Message, MessageRead, Notification, User


# Render one conversation and mark newly seen messages as read.
@main_bp.route("/messages/<int:conversation_id>")
@login_required
def messages(conversation_id):
    membership = ConversationMember.query.filter_by(
        conversation_id=conversation_id,
        user_id=current_user.id,
    ).first()

    if membership is None:
        return "You do not have access to this conversation.", 403

    conversation = db.session.get(Conversation, conversation_id)
    if conversation is None:
        return "Conversation not found.", 404

    message_history = Message.query.filter_by(
        conversation_id=conversation.id,
        is_deleted=False,
    ).order_by(Message.created_at.asc()).all()

    already_read_ids = {
        mr.message_id
        for mr in MessageRead.query.filter_by(user_id=current_user.id).all()
    }

    for msg in message_history:
        if msg.id not in already_read_ids and msg.sender_id != current_user.id:
            db.session.add(MessageRead(message_id=msg.id, user_id=current_user.id))
    db.session.commit()

    return render_template(
        "messages.html",
        current_user=current_user,
        conversation=conversation,
        messages=message_history,
    )


# Render the user's conversation inbox with unread counts.
@main_bp.route("/messages")
@login_required
def messages_inbox():
    memberships = (
        ConversationMember.query.filter_by(user_id=current_user.id)
        .join(Conversation)
        .order_by(Conversation.created_at.desc())
        .all()
    )

    conversations = []
    for membership in memberships:
        conversation = membership.conversation
        other_members = [member.user for member in conversation.members if member.user_id != current_user.id]
        latest_message = (
            Message.query.filter_by(conversation_id=conversation.id)
            .order_by(Message.created_at.desc())
            .first()
        )

        if conversation.title:
            display_name = conversation.title
        elif other_members:
            display_name = ", ".join(member.username for member in other_members)
        else:
            display_name = "Direct Message"

        read_ids = {
            mr.message_id
            for mr in MessageRead.query.filter_by(user_id=current_user.id).all()
        }
        unread_count = Message.query.filter(
            Message.conversation_id == conversation.id,
            Message.sender_id != current_user.id,
            Message.id.notin_(read_ids),
            Message.is_deleted.is_(False),
        ).count()

        conversations.append(
            {
                "conversation": conversation,
                "display_name": display_name,
                "latest_message": latest_message,
                "unread_count": unread_count,
            }
        )

    return render_template(
        "messages_inbox.html",
        current_user=current_user,
        conversations=conversations,
    )


# Start or reuse a direct conversation with another user.
@main_bp.route("/messages/start/<int:receiver_id>", methods=["POST"])
@login_required
def start_conversation(receiver_id):
    receiver = db.session.get(User, receiver_id)
    if receiver is None:
        return "User not found.", 404

    if receiver.id == current_user.id:
        return "You cannot start a conversation with yourself.", 400

    existing_conversations = (
        Conversation.query
        .join(ConversationMember)
        .filter(
            Conversation.is_group_chat.is_(False),
            ConversationMember.user_id == current_user.id,
        )
        .all()
    )

    for conversation in existing_conversations:
        member_ids = {member.user_id for member in conversation.members}
        if member_ids == {current_user.id, receiver.id}:
            return redirect(url_for("main.messages", conversation_id=conversation.id))

    conversation = Conversation(is_group_chat=False)
    db.session.add(conversation)
    db.session.flush()

    db.session.add(
        ConversationMember(
            conversation_id=conversation.id,
            user_id=current_user.id,
        )
    )

    db.session.add(
        ConversationMember(
            conversation_id=conversation.id,
            user_id=receiver.id,
        )
    )

    db.session.add(
        Notification(
            user_id=receiver.id,
            sender_name=current_user.username,
            type="match",
            message=f"<strong>{current_user.username}</strong> accepted your match and wants to study with you!",
            channel=f"Conversation {conversation.id}",
        )
    )

    db.session.commit()

    return redirect(url_for("main.messages", conversation_id=conversation.id))


# Soft-delete a sent message and broadcast removal.
@main_bp.route("/messages/delete/<int:message_id>", methods=["POST"])
@login_required
def delete_message(message_id):
    message = Message.query.get_or_404(message_id)

    if message.sender_id != current_user.id:
        abort(403)

    message.is_deleted = True
    db.session.commit()

    socketio.emit(
        "message_deleted",
        {"message_id": message_id},
        room=f"conversation-{message.conversation_id}",
    )

    return "", 204
