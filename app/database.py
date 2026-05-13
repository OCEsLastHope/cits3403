from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app import db



class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    degree = db.Column(db.String(100), nullable=False)
    major = db.Column(db.String(100), nullable=False)
    bio = db.Column(db.Text, nullable=True)
    sessions_per_week = db.Column(db.Integer, nullable=True)
    preferred_group_size = db.Column(db.String(20), nullable=True)
    study_mode = db.Column(db.String(30), nullable=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    degree_option_id = db.Column(db.Integer, db.ForeignKey("degree_option.id"), nullable=True)
    onboarding_completed = db.Column(db.Boolean, nullable=False, default=False)
    onboarding_step = db.Column(db.Integer, nullable=False, default=1)

    subjects = db.relationship("UserSubject", backref="user", lazy=True, cascade="all, delete-orphan")
    availabilities = db.relationship("UserAvailability", backref="user", lazy=True, cascade="all, delete-orphan")
    degree_option = db.relationship("DegreeOption", backref="users", lazy=True)
    
    


    def __repr__(self):
        return f"<User id={self.id} username={self.username} email={self.email}>"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    sender_name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    channel = db.Column(db.String(100), default="Direct Message")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def sender_initial(self):
        parts = self.sender_name.split()
        return parts[0][0] + parts[-1][0].upper() if len(parts) > 1 else parts[0][:2].upper()

    @property
    def sender_online(self):
        return not self.is_read

    @property
    def avatar_bg(self):
        return {"dm": "rgba(0, 212, 232, 0.15)", "mention": "rgba(214,58,249,0.15)"}.get(
            self.type, "rgba(255,255,255,0.05)"
        )

    @property
    def avatar_color(self):
        return {"dm": "#00d4e8", "mention": "#d63af9"}.get(self.type, "#6b7280")

    @property
    def time_ago(self):
        from datetime import timezone

        delta = datetime.now(timezone.utc) - self.created_at.replace(tzinfo=timezone.utc)
        s = int(delta.total_seconds())
        if s < 60:
            return "just now"
        if s < 3600:
            return f"{s // 60}m ago"
        if s < 86400:
            return f"{s // 3600}h ago"
        if s < 172800:
            return "Yesterday"
        return f"{s // 86400} days ago"


class UserSubject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    subject_code = db.Column(db.String(30), nullable=False)


class UserAvailability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    day_of_week = db.Column(db.String(20), nullable=False)
    start_time = db.Column(db.String(10), nullable=False)
    end_time = db.Column(db.String(10), nullable=False)


class DegreeCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    label = db.Column(db.String(100), nullable=False)


class DegreeOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("degree_category.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    category = db.relationship("DegreeCategory", backref="options", lazy=True)

    __table_args__ = (db.UniqueConstraint("category_id", "name", name="uq_degree_option_category_name"),)
    
class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=True)
    is_group_chat = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    members = db.relationship(
        "ConversationMember",
        backref="conversation",
        lazy=True,
        cascade="all, delete-orphan"
    )

    messages = db.relationship(
        "Message",
        backref="conversation",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Message.created_at"
    )

    def __repr__(self):
        return f"<Conversation {self.id}>"


class ConversationMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation.id"),
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="conversation_memberships", lazy=True)

    __table_args__ = (
        db.UniqueConstraint(
            "conversation_id",
            "user_id",
            name="uq_conversation_member"
        ),
    )
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation.id"),
        nullable=False
    )

    sender_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    edited_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)

    sender = db.relationship("User", backref="sent_messages", lazy=True)

    def __repr__(self):
        return f"<Message {self.id} from User {self.sender_id}>"

    @property
    def display_body(self):
        return "[deleted]" if self.is_deleted else self.body

class MessageRead(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    message_id = db.Column(
        db.Integer,
        db.ForeignKey("message.id"),
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    read_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    message = db.relationship("Message", backref="read_receipts", lazy=True)
    user = db.relationship("User", backref="message_reads", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("message_id", "user_id", name="uq_message_read"),
    )

class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    sender_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    receiver_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    # LINKING INVITE TO MESSAGES

    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation.id"),
        nullable=True
    )

    message = db.Column(db.Text, nullable=True) #invite message
    status = db.Column(db.String(20), nullable=False, default="pending") #reject, accept, or pending

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    responded_at = db.Column(db.DateTime, nullable=True)

    sender = db.relationship("User", foreign_keys=[sender_id], backref="sent_invitation", lazy=True)
    receiver = db.relationship("User", foreign_keys=[receiver_id], backref="received_invitation", lazy=True)
    conversation = db.relationship("Conversation", backref="invitations", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("sender_id", "receiver_id", "conversation_id", name="uq_invitation"),
    )

    def __repr__(self):
        return f"<Invitation {self.id} from {self.sender_id} to {self.receiver_id} [{self.status}]>"


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    creator_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    location_or_link = db.Column(db.String(255), nullable=True)
    visibility_mode = db.Column(db.String(20), nullable=False, default="invite_only")
    max_attendees = db.Column(db.Integer, nullable=True)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="scheduled")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    creator = db.relationship("User", backref="created_events", lazy=True)
    attendees = db.relationship("EventAttendee", backref="event", lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Event {self.id} {self.title}>"


class EventAttendee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    invite_status = db.Column(db.String(20), nullable=False, default="invited")
    responded_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="event_attendances", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("event_id", "user_id", name="uq_event_attendee"),
    )

    def __repr__(self):
        return f"<EventAttendee event={self.event_id} user={self.user_id} status={self.invite_status}>"
