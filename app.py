from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///studysync.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

db = SQLAlchemy(app)

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

with app.app_context():
    db.create_all()

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/profile")
def profile():
    return render_template("userpages.html")

@app.route("/notifications")
def notifications():
    user = User.query.get(1)
    notifs = Notification.query.filter_by(user_id=1).order_by(Notification.created_at.desc()).all()
    return render_template("notifications.html",
        current_user = user,
        notifications = notifs,
        unread_count = sum(1 for n in notifs if not n.is_read),
        dm_count = sum(1 for n in notifs if n.type == 'dm' and not n.is_read),
        mention_count = sum(1 for n in notifs if n.type =='mention' and not n.is_read),)

@app.route("/notifications/read/<int:notif_id>", methods=["POST"])
def mark_read(notif_id):
    n = Notification.query.get_or_404(notif_id)
    n.is_read = True
    db.session.commit()
    return '', 204

@app.route("/notifications/read/all", methods=["POST"])
def mark_all_read():
    Notification.query.filter_by(user_id=1, is_read=False).update({'is_read': True})
    db.session.commit()
    return '', 204

with app.app_context():
    db.create_all()
    if Notification.query.count() == 0:
        db.session.add_all([
            Notification(user_id=1, sender_name="Daniel K.",  type="dm",     message="Hey, did you review the <strong>design brief</strong>?",    channel="Direct message"),
            Notification(user_id=1, sender_name="Marcus S.", type="mention", message="<strong>@you</strong> can you push the deploy before 5pm?", channel="#engineering"),
            Notification(user_id=1, sender_name="Tom N.",    type="dm",     message="Quick question about the <strong>Q3 report</strong>.",       channel="Direct message"),
        ])
        db.session.commit()
        
if __name__ == "__main__":
    app.run(debug=True)