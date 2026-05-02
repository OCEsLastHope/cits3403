from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    degree = db.Column(db.String(100), nullable=False)
    major = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f'<User {self.email}>'

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender_name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    channel = db.Column(db.String(100), default='Direct Message')
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def sender_initial(self):
        parts = self.sender_name.split()
        return (parts[0][0] + parts[-1][0].upper() if len(parts)>1 else parts[0][:2].upper())

    @property
    def sender_online(self):
        return not self.is_read

    @property
    def avatar_bg(self):
        return {'dm': 'rgba(0, 212, 232, 0.15)', 'mention': 'rgba(214,58,249,0.15)'}.get(self.type, 'rgba(255,255,255,0.05)')

    @property
    def avatar_color(self):
        return {'dm': '#00d4e8', 'mention': '#d63af9'}.get(self.type, '#6b7280')

    @property
    def time_ago(self):
        from datetime import timezone
        delta = datetime.now(timezone.utc) - self.created_at.replace(tzinfo=timezone.utc)
        s = int(delta.total_seconds())
        if s < 60: return 'just now'
        if s < 3600: return f'{s//60}m ago'
        if s < 86400: return f'{s//3600}h ago'
        if s < 172800: return 'Yesterday'
        return f'{s//86400} days ago'
