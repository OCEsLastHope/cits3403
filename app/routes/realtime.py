from flask_socketio import join_room

from .. import db, socketio
from ..database import Conversation, ConversationMember, Message, MessageRead, Notification
from .common import get_current_user, notify_mentions


# Subscribe an authorized user to a conversation room.
@socketio.on("join_conversation")
def handle_join_conversation(data):
    current_user = get_current_user()
    if current_user is None:
        return

    try:
        conversation_id = int(data.get("conversation_id"))
    except (TypeError, ValueError):
        return

    membership = ConversationMember.query.filter_by(
        conversation_id=conversation_id,
        user_id=current_user.id,
    ).first()

    if membership is None:
        return

    join_room(f"conversation-{conversation_id}")


# Persist and broadcast a new realtime chat message.
@socketio.on("send_message")
def handle_send_message(data):
    user = get_current_user()
    if user is None:
        return

    try:
        conversation_id = int(data.get("conversation_id"))
    except (TypeError, ValueError):
        return

    body = data.get("body", "").strip()

    if not body:
        return

    if len(body) > 1000:
        return

    membership = ConversationMember.query.filter_by(
        conversation_id=conversation_id,
        user_id=user.id,
    ).first()

    if membership is None:
        return

    message = Message(
        conversation_id=conversation_id,
        sender_id=user.id,
        body=body,
    )

    db.session.add(message)
    db.session.flush()

    db.session.add(MessageRead(message_id=message.id, user_id=user.id))

    notify_mentions(message, conversation_id)

    conversation = db.session.get(Conversation, conversation_id)

    for member in conversation.members:
        if member.user_id != user.id:
            notif = Notification(
                user_id=member.user_id,
                sender_name=user.username,
                type="dm",
                message=f"<strong>{user.username}</strong>: {body[:80]}",
                channel=f"Conversation {conversation_id}",
            )
            db.session.add(notif)

    db.session.commit()

    socketio.emit(
        "new_message",
        {
            "id": message.id,
            "conversation_id": conversation_id,
            "sender_id": user.id,
            "sender_name": user.username,
            "body": message.body,
            "created_at": message.created_at.strftime("%H:%M"),
        },
        room=f"conversation-{conversation_id}",
    )
