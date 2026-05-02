from flask import Flask, render_template, request, url_for, redirect
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from werkzeug.security import generate_password_hash
from database import db, User, Notification

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///studysync.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()

@app.route("/")
def landing():
    return render_template("landing.html")

@app.route("/login")
def login():
    return render_template("loginpage.html")

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    return render_template("forgot_password.html")

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/profile")
def profile():
    return render_template("userpages.html")

@app.route("/register")
def register():
    return render_template("signup.html")

with app.app_context():
    db.create_all()

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
    app.run(debug=True, port=5050)
    
    