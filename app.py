import re

from flask import Flask, render_template, request, url_for, redirect
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from werkzeug.security import generate_password_hash
from sqlalchemy import text
from database import db, User, Notification, UserSubject, UserAvailability

app = Flask(__name__)

DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
TIME_OPTIONS = [f"{hour:02d}:00" for hour in range(6, 24)]

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///studysync.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


def ensure_user_profile_columns():
    user_columns = {
        row[1] for row in db.session.execute(text("PRAGMA table_info(user)")).fetchall()
    }

    if "bio" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN bio TEXT"))
    if "sessions_per_week" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN sessions_per_week INTEGER"))
    if "preferred_group_size" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN preferred_group_size VARCHAR(20)"))
    if "study_mode" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN study_mode VARCHAR(30)"))

    db.session.commit()


with app.app_context():
    db.create_all()
    ensure_user_profile_columns()

    if User.query.count() == 0:
        test_user = User(
            first_name="Mineth",
            last_name="Perera",
            email="mineth@test.com",
            degree="Engineering",
            major="Software Engineering"
        )

        db.session.add(test_user)
        db.session.commit()


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

@app.route("/profile", methods=["GET", "POST"])
def profile():
    user_id = request.args.get("user_id", type=int)
    if user_id is None:
        user_id = request.form.get("user_id", default=1, type=int)

    user = db.session.get(User, user_id)

    if request.method == "POST":
        if user is None:
            return redirect(url_for("profile", user_id=1))

        submitted_email = request.form.get("email", "").strip()
        submitted_degree = request.form.get("degree", "").strip()
        submitted_major = request.form.get("major", "").strip()
        submitted_bio = request.form.get("bio", "").strip()
        submitted_sessions_per_week = request.form.get("sessions_per_week", "").strip()
        submitted_group_size = request.form.get("preferred_group_size", "").strip()
        submitted_study_mode = request.form.get("study_mode", "").strip()

        subject_values = [
            request.form.get("subject1", "").strip(),
            request.form.get("subject2", "").strip(),
            request.form.get("subject3", "").strip(),
        ]
        profile_errors = []
        availability_errors = []
        submitted_availability_map = {day: [] for day in DAY_NAMES}
        valid_availability_rows = []

        if not submitted_email:
            profile_errors.append("Email is required.")
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", submitted_email):
            profile_errors.append("Email format is invalid.")
        else:
            existing_user = User.query.filter_by(email=submitted_email).first()
            if existing_user and existing_user.id != user.id:
                profile_errors.append("Email is already in use by another account.")

        if not submitted_degree:
            profile_errors.append("Degree is required.")
        if not submitted_major:
            profile_errors.append("Major is required.")
        if submitted_sessions_per_week and not submitted_sessions_per_week.isdigit():
            profile_errors.append("Sessions per week must be a valid number.")

        for day in DAY_NAMES:
            day_key = day.lower()
            start_times = request.form.getlist(f"{day_key}_start")
            end_times = request.form.getlist(f"{day_key}_end")

            for idx, (start_time, end_time) in enumerate(zip(start_times, end_times), start=1):
                start_time = start_time.strip()
                end_time = end_time.strip()

                if not start_time and not end_time:
                    continue

                submitted_availability_map[day].append((start_time, end_time))

                if not start_time or not end_time:
                    availability_errors.append(f"{day} slot {idx}: start and end time are both required.")
                    continue

                if start_time >= end_time:
                    availability_errors.append(f"{day} slot {idx}: end time must be later than start time.")
                    continue

                valid_availability_rows.append((day, start_time, end_time))

        by_day = {}
        for day, start_time, end_time in valid_availability_rows:
            by_day.setdefault(day, []).append((start_time, end_time))

        for day, slots in by_day.items():
            slots.sort(key=lambda slot: slot[0])
            for i in range(1, len(slots)):
                prev_start, prev_end = slots[i - 1]
                curr_start, curr_end = slots[i]
                if curr_start < prev_end:
                    availability_errors.append(
                        f"{day}: overlapping slots ({prev_start}-{prev_end} and {curr_start}-{curr_end})."
                    )

        if profile_errors or availability_errors:
            return render_template(
                "userpages.html",
                current_user=user,
                subjects=[value for value in subject_values if value],
                availability_map=submitted_availability_map,
                day_names=DAY_NAMES,
                time_options=TIME_OPTIONS,
                profile_errors=profile_errors + availability_errors,
                open_profile_modal=True,
            )

        user.email = submitted_email
        user.degree = submitted_degree
        user.major = submitted_major
        user.bio = submitted_bio
        user.sessions_per_week = int(submitted_sessions_per_week) if submitted_sessions_per_week else None
        user.preferred_group_size = submitted_group_size or None
        user.study_mode = submitted_study_mode or None

        UserSubject.query.filter_by(user_id=user.id).delete()
        for value in subject_values:
            if value:
                db.session.add(UserSubject(user_id=user.id, subject_code=value))

        UserAvailability.query.filter_by(user_id=user.id).delete()
        for day, start_time, end_time in valid_availability_rows:

                db.session.add(
                    UserAvailability(
                        user_id=user.id,
                        day_of_week=day,
                        start_time=start_time,
                        end_time=end_time,
                    )
                )

        db.session.commit()
        return redirect(url_for("profile", user_id=user.id))

    if user is None:
        return render_template(
            "userpages.html",
            current_user=None,
            subjects=[],
            availability_map={},
            day_names=DAY_NAMES,
            time_options=TIME_OPTIONS,
            profile_errors=[],
            open_profile_modal=False,
        )

    subject_codes = [item.subject_code for item in user.subjects]
    availability_map = {day: [] for day in DAY_NAMES}
    for item in user.availabilities:
        availability_map.setdefault(item.day_of_week, []).append((item.start_time, item.end_time))

    return render_template(
        "userpages.html",
        current_user=user,
        subjects=subject_codes,
        availability_map=availability_map,
        day_names=DAY_NAMES,
        time_options=TIME_OPTIONS,
        profile_errors=[],
        open_profile_modal=False,
    )

@app.route("/register")
def register():
    return render_template("signup.html")

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
    if Notification.query.count() == 0:
        db.session.add_all([
            Notification(user_id=1, sender_name="Daniel K.",  type="dm",     message="Hey, did you review the <strong>design brief</strong>?",    channel="Direct message"),
            Notification(user_id=1, sender_name="Marcus S.", type="mention", message="<strong>@you</strong> can you push the deploy before 5pm?", channel="#engineering"),
            Notification(user_id=1, sender_name="Tom N.",    type="dm",     message="Quick question about the <strong>Q3 report</strong>.",       channel="Direct message"),
        ])
        db.session.commit()
        
if __name__ == "__main__":
    app.run(debug=True, port=5050)
    
    
