import re

from flask import redirect, render_template, request, url_for, session
from flask_socketio import emit, join_room

from . import app, db, socketio
from .database import (
    Conversation,
    ConversationMember,
    Message,
    Notification,
    User,
    UserAvailability,
    UserSubject,
)



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

def get_current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return db.session.get(User, user_id)



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


@app.route("/register", methods=["GET", "POST"])
def register():
    degree_options = {
        "bachelors": [
            "Bachelor of Agribusiness [BP020]",
            "Bachelor of Agricultural Science [BP019]",
            "Bachelor of Art History and Curatorial Studies [BP070]",
            "Bachelor of Arts [BP001]",
            "Bachelor of Arts (Integrated Professional) [BW001]",
            "Bachelor of Biological Science [BP025]",
            "Bachelor of Biomedical Science [BP006]",
            "Bachelor of Biomedicine (Specialised) [BP056]",
            "Bachelor of Business [BP009]",
            "Bachelor of Commerce [BP002]",
            "Bachelor of Commerce (Integrated Professional) [BW002]",
            "Bachelor of Criminology and Criminal Justice [BP050]",
            "Bachelor of Earth Sciences [BP029]",
            "Bachelor of Economics [BP013]",
            "Bachelor of Environmental Design [BP011]",
            "Bachelor of Environmental Science [BP022]",
            "Bachelor of Geographical and Spatial Science [BP055]",
            "Bachelor of Human Rights [BP034]",
            "Bachelor of Human Sciences [BP031]",
            "Bachelor of International Relations [BP058]",
            "Bachelor of Letters [BP501]",
            "Bachelor of Marine Science [BP023]",
            "Bachelor of Mathematics [BP059]",
            "Bachelor of Media and Communication [BP069]",
            "Bachelor of Modern Languages [BP054]",
            "Bachelor of Molecular Sciences [BP028]",
            "Bachelor of Music [BP008]",
            "Bachelor of Philosophy, Politics and Economics [BP012]",
            "Bachelor of Psychological Studies [BP503]",
            "Bachelor of Psychology [BP030]",
            "Bachelor of Science [BP004]",
            "Bachelor of Science (Integrated Professional) [BW004]",
            "Bachelor of Science and Technology [BP502]",
            "Bachelor of Social and Environmental Sustainability [BP062]",
            "Bachelor of Sport and Exercise Sciences [BP026]"
        ],
        "honours": [
            "Bachelor of Advanced Computer Science [Honours] [BH008]",
            "Bachelor of Arts (Honours) [BH001]",
            "Bachelor of Biological Science (Honours) [BH024]",
            "Bachelor of Biomedical Science (Honours) [BH006]",
            "Bachelor of Business (Honours) [BH021]",
            "Bachelor of Commerce (Honours) [BH002]",
            "Bachelor of Criminology and Criminal Justice (Honours) [BH018]",
            "Bachelor of Earth Sciences (Honours) [BH026]",
            "Bachelor of Economics (Honours) [BH013]",
            "Bachelor of Education (Primary) (Honours) [BH020]",
            "Bachelor of Engineering (Honours) [BH011]",
            "Bachelor of Environmental Design (Honours) [BH040]",
            "Bachelor of Human Rights Honours [BH019]",
            "Bachelor of Landscape Architecture (Honours) [BH039]",
            "Bachelor of Marine Science (Honours) [BH025]",
            "Bachelor of Mathematics (Honours) [BH035]",
            "Bachelor of Modern Languages Honours [BH016]",
            "Bachelor of Music (Honours) [BH009]",
            "Bachelor of Nursing (Honours) [BH028]",
            "Bachelor of Philosophy (Honours) [BH005]",
            "Bachelor of Philosophy, Politics, and Economics (Honours) [BH015]",
            "Bachelor of Psychology (Honours) [BH014]",
            "Bachelor of Science (Honours) [BH004]",
            "Bachelor of Social Work (Honours) [BH017]",
            "Bachelor of Sport and Exercise Sciences (Honours) [BH032]"
        ],
        "combined_bachelors": [
            # paste your full combined_bachelors list here
        ],
        "combined_masters": [
            # paste your full combined_masters list here
        ]
    }

    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip()
        username = request.form.get("username", "").strip()
        degree = request.form.get("degree", "").strip()
        major = request.form.get("major", "").strip()

        if degree == "other":
            degree = request.form.get("other_degree", "").strip()

        if User.query.filter_by(email=email).first():
            return "Email already exists"

        if User.query.filter_by(username=username).first():
            return "Username already taken"

        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            username=username,
            degree=degree,
            major=major,
        )

        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for("login"))

    return render_template("signup.html", degree_options=degree_options)



@app.route("/notifications")
def notifications():
    user = User.query.get(1)
    notifs = Notification.query.filter_by(user_id=1).order_by(Notification.created_at.desc()).all()
    return render_template(
        "notifications.html",
        current_user=user,
        notifications=notifs,
        unread_count=sum(1 for n in notifs if not n.is_read),
        dm_count=sum(1 for n in notifs if n.type == "dm" and not n.is_read),
        mention_count=sum(1 for n in notifs if n.type == "mention" and not n.is_read),
    )


@app.route("/notifications/read/<int:notif_id>", methods=["POST"])
def mark_read(notif_id):
    n = Notification.query.get_or_404(notif_id)
    n.is_read = True
    db.session.commit()
    return "", 204


@app.route("/notifications/read/all", methods=["POST"])
def mark_all_read():
    Notification.query.filter_by(user_id=1, is_read=False).update({"is_read": True})
    db.session.commit()
    return "", 204


@app.route("/messages/<int:conversation_id>")
def messages(conversation_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

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

    return render_template(
        "messages.html",
        current_user=current_user,
        conversation=conversation,
        messages=message_history,
    )


@app.route("/messages/start/<int:receiver_id>", methods=["POST"])
def start_conversation(receiver_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

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
            return redirect(url_for("messages", conversation_id=conversation.id))

    conversation = Conversation(is_group_chat=False)
    db.session.add(conversation)
    db.session.flush()

    db.session.add(ConversationMember(
        conversation_id=conversation.id,
        user_id=current_user.id,
    ))

    db.session.add(ConversationMember(
        conversation_id=conversation.id,
        user_id=receiver.id,
    ))

    db.session.commit()

    return redirect(url_for("messages", conversation_id=conversation.id))


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


@socketio.on("send_message")
def handle_send_message(data):
    current_user = get_current_user()
    if current_user is None:
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
        user_id=current_user.id,
    ).first()

    if membership is None:
        return

    message = Message(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        body=body,
    )

    db.session.add(message)
    db.session.commit()

    emit(
        "receive_message",
        {
            "id": message.id,
            "conversation_id": conversation_id,
            "sender_id": current_user.id,
            "sender_name": current_user.username,
            "body": message.body,
            "created_at": message.created_at.strftime("%H:%M"),
        },
        room=f"conversation-{conversation_id}",
    )

