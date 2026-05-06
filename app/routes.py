import re
from collections import defaultdict

from flask import redirect, render_template, request, url_for, session
from sqlalchemy import func, or_
from flask_socketio import emit, join_room

from . import app, db, socketio
from .database import (
    Conversation,
    ConversationMember,
    DegreeOption,
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


def get_degree_options_by_category():
    grouped = {"bachelors": [], "honours": [], "combined_bachelors": [], "combined_masters": []}
    options = DegreeOption.query.filter_by(is_active=True).all()

    for option in options:
        category_key = option.category.key if option.category else None
        if category_key in grouped:
            grouped[category_key].append({"id": option.id, "name": option.name})

    for key in grouped:
        grouped[key].sort(key=lambda item: item["name"].lower())

    return grouped

def get_current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return db.session.get(User, user_id)



def time_to_minutes(value):
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def minutes_to_time(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def build_overlap_summary(requester_availability, candidate_availability):
    requester_by_day = defaultdict(list)
    candidate_by_day = defaultdict(list)

    for slot in requester_availability:
        requester_by_day[slot.day_of_week].append((time_to_minutes(slot.start_time), time_to_minutes(slot.end_time)))

    for slot in candidate_availability:
        candidate_by_day[slot.day_of_week].append((time_to_minutes(slot.start_time), time_to_minutes(slot.end_time)))

    overlap_by_day = {}
    overlap_minutes_total = 0

    for day in DAY_NAMES:
        overlaps = []
        for req_start, req_end in requester_by_day.get(day, []):
            for cand_start, cand_end in candidate_by_day.get(day, []):
                overlap_start = max(req_start, cand_start)
                overlap_end = min(req_end, cand_end)
                if overlap_start < overlap_end:
                    overlaps.append((overlap_start, overlap_end))

        if not overlaps:
            continue

        overlaps.sort(key=lambda item: item[0])
        merged = [overlaps[0]]
        for start, end in overlaps[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))

        overlap_by_day[day] = [(minutes_to_time(start), minutes_to_time(end)) for start, end in merged]
        overlap_minutes_total += sum(end - start for start, end in merged)

    return overlap_minutes_total, overlap_by_day


def find_matches(user_id, selected_degree_option_id=None):
    requester = db.session.get(User, user_id)
    if not requester:
        return []

    requester_availability = UserAvailability.query.filter_by(user_id=requester.id).all()
    if not requester_availability:
        return []

    requester_days = sorted({slot.day_of_week for slot in requester_availability})
    candidate_query = (
        User.query.join(UserAvailability, UserAvailability.user_id == User.id)
        .filter(User.id != requester.id)
        .filter(UserAvailability.day_of_week.in_(requester_days))
    )

    if selected_degree_option_id is not None:
        degree_option = DegreeOption.query.filter_by(id=selected_degree_option_id, is_active=True).first()
        if degree_option:
            candidate_query = candidate_query.filter(
                or_(
                    User.degree_option_id == selected_degree_option_id,
                    func.lower(func.trim(User.degree)) == degree_option.name.strip().lower(),
                )
            )

    candidates = candidate_query.distinct().all()
    match_results = []

    for candidate in candidates:
        candidate_availability = UserAvailability.query.filter_by(user_id=candidate.id).all()
        if not candidate_availability:
            continue

        overlap_minutes_total, overlap_by_day = build_overlap_summary(requester_availability, candidate_availability)
        if overlap_minutes_total <= 0:
            continue

        match_results.append(
            {
                "user": candidate,
                "overlap_minutes_total": overlap_minutes_total,
                "overlap_by_day": overlap_by_day,
            }
        )

    match_results.sort(key=lambda item: item["overlap_minutes_total"], reverse=True)
    return match_results


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        return redirect(url_for("dashboard"))
    return render_template("loginpage.html")


@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    return render_template("forgot_password.html")


@app.route("/dashboard")
def dashboard():
    user = get_current_user()
    if not user:
        # Fallback for demo if no session is active
        user = db.session.get(User, 1)

    suggested_matches = []
    if user:
        # Get the top 3 matches for the dashboard preview
        suggested_matches = find_matches(user.id)[:3]

    return render_template(
        "dashboard.html",
        current_user=user,
        suggested_matches=suggested_matches
    )


@app.route("/matches")
def matches():
    user_id = request.args.get("user_id", type=int)
    selected_degree_option_id = request.args.get("degree_option_id", type=int)
    degree_options = get_degree_options_by_category()

    if user_id is None:
        return render_template(
            "matches.html",
            current_user=None,
            matches=[],
            degree_options=degree_options,
            selected_degree_option_id=None,
            message="Invalid or missing user_id.",
        )

    requester = db.session.get(User, user_id)
    if requester is None:
        return render_template(
            "matches.html",
            current_user=None,
            matches=[],
            degree_options=degree_options,
            selected_degree_option_id=selected_degree_option_id,
            message="Invalid user_id.",
        )

    match_results = find_matches(user_id, selected_degree_option_id)

    message = ""
    if not match_results:
        if not UserAvailability.query.filter_by(user_id=requester.id).first():
            message = "Add your availability in Profile to find matches."
        else:
            message = "No matches found with overlapping availability."

    return render_template(
        "matches.html",
        current_user=requester,
        matches=match_results[:10],
        degree_options=degree_options,
        selected_degree_option_id=selected_degree_option_id,
        message=message,
    )

    message = ""
    if not match_results:
        message = "No matches found with overlapping availability."

    return render_template(
        "matches.html",
        current_user=requester,
        matches=match_results[:10],
        degree_options=degree_options,
        selected_degree_option_id=selected_degree_option_id,
        message=message,
    )


@app.route("/profile", methods=["GET", "POST"])
def profile():
    degree_options = get_degree_options_by_category()
    user_id = request.args.get("user_id", type=int)
    if user_id is None:
        user_id = request.form.get("user_id", default=1, type=int)

    user = db.session.get(User, user_id)

    if request.method == "POST":
        if user is None:
            return redirect(url_for("profile", user_id=1))

        submitted_email = request.form.get("email", "").strip()
        submitted_degree = request.form.get("degree", "").strip()
        submitted_degree_option_id = request.form.get("degree_option_id", type=int)
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

        selected_degree_option = None
        if submitted_degree_option_id:
            selected_degree_option = DegreeOption.query.filter_by(id=submitted_degree_option_id, is_active=True).first()
            if selected_degree_option is None:
                profile_errors.append("Selected degree is invalid.")

        if not selected_degree_option and not submitted_degree:
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
                degree_options=degree_options,
                profile_errors=profile_errors + availability_errors,
                open_profile_modal=True,
            )

        user.email = submitted_email
        if selected_degree_option is not None:
            user.degree_option_id = selected_degree_option.id
            user.degree = selected_degree_option.name
        else:
            user.degree_option_id = None
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
            degree_options=degree_options,
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
        degree_options=degree_options,
        profile_errors=[],
        open_profile_modal=False,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    degree_options = get_degree_options_by_category()

    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip()
        username = request.form.get("username", "").strip()
        degree_type = request.form.get("degree_type", "").strip()
        degree_option_id = request.form.get("degree_option_id", type=int)
        degree = request.form.get("degree", "").strip()
        major = request.form.get("major", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not first_name or not last_name or not email or not username or not major:
            return "All required fields must be filled.", 400

        if not password or password != confirm_password:
            return "Password and confirm password must match.", 400

        selected_degree_option = None
        if degree_type != "other" and degree_option_id:
            selected_degree_option = DegreeOption.query.filter_by(id=degree_option_id, is_active=True).first()
            if selected_degree_option is None:
                return "Selected degree is invalid", 400

        if selected_degree_option is None and not degree:
            return "Degree is required", 400

        if User.query.filter_by(email=email).first():
            return "Email already exists"

        if User.query.filter_by(username=username).first():
            return "Username already taken"

        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            username=username,
            degree=selected_degree_option.name if selected_degree_option else degree,
            degree_option_id=selected_degree_option.id if selected_degree_option else None,
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
