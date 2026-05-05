import re
from collections import defaultdict

from flask import redirect, render_template, request, url_for
from sqlalchemy import func, or_

from . import app, db
from .database import DegreeCategory, DegreeOption, Notification, User, UserAvailability, UserSubject

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
    categories = DegreeCategory.query.order_by(DegreeCategory.id.asc()).all()
    degree_options = {}
    for category in categories:
        options = (
            DegreeOption.query.filter_by(category_id=category.id, is_active=True)
            .order_by(DegreeOption.name.asc())
            .all()
        )
        degree_options[category.key] = [{"id": option.id, "name": option.name} for option in options]
    return degree_options


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

    requester_availability = UserAvailability.query.filter_by(user_id=requester.id).all()
    if not requester_availability:
        return render_template(
            "matches.html",
            current_user=requester,
            matches=[],
            degree_options=degree_options,
            selected_degree_option_id=selected_degree_option_id,
            message="Add your availability in Profile to find matches.",
        )

    requester_days = sorted({slot.day_of_week for slot in requester_availability})
    candidate_query = (
        User.query.join(UserAvailability, UserAvailability.user_id == User.id)
        .filter(User.id != requester.id)
        .filter(UserAvailability.day_of_week.in_(requester_days))
    )

    if selected_degree_option_id is not None:
        degree_option = DegreeOption.query.filter_by(id=selected_degree_option_id, is_active=True).first()
        if degree_option is None:
            return render_template(
                "matches.html",
                current_user=requester,
                matches=[],
                degree_options=degree_options,
                selected_degree_option_id=None,
                message="Selected degree filter is invalid.",
            )
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
    user_id = request.args.get("user_id", type=int)
    if user_id is None:
        user_id = request.form.get("user_id", default=1, type=int)

    user = db.session.get(User, user_id)

    if request.method == "POST":
        if user is None:
            return redirect(url_for("profile", user_id=1))

        submitted_email = request.form.get("email", "").strip()
        submitted_degree_type = request.form.get("degree_type", "").strip()
        submitted_degree_option_id_raw = request.form.get("degree_option_id", "").strip()
        submitted_custom_degree = request.form.get("degree", "").strip()
        submitted_degree = ""
        submitted_degree_option_id = None
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

        if submitted_degree_type == "other":
            submitted_degree = submitted_custom_degree
            if not submitted_degree and user is not None:
                submitted_degree = (user.degree or "").strip()
            if submitted_degree:
                submitted_degree_option_id = None
        elif submitted_degree_option_id_raw.isdigit():
            selected_option = DegreeOption.query.filter_by(id=int(submitted_degree_option_id_raw), is_active=True).first()
            if selected_option:
                submitted_degree_option_id = selected_option.id
                submitted_degree = selected_option.name

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
                degree_options=get_degree_options_by_category(),
                profile_errors=profile_errors + availability_errors,
                open_profile_modal=True,
            )

        user.email = submitted_email
        user.degree = submitted_degree
        user.degree_option_id = submitted_degree_option_id
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
            degree_options=get_degree_options_by_category(),
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
        degree_options=get_degree_options_by_category(),
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
        degree_option_id_raw = request.form.get("degree_option_id", "").strip()
        degree = ""
        degree_option_id = None
        major = request.form.get("major", "").strip()

        if degree_type == "other":
            degree = request.form.get("degree", "").strip()
        elif degree_option_id_raw.isdigit():
            degree_option = DegreeOption.query.filter_by(id=int(degree_option_id_raw), is_active=True).first()
            if degree_option is not None:
                degree_option_id = degree_option.id
                degree = degree_option.name

        if not degree:
            return "Please select a valid degree"

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
            degree_option_id=degree_option_id,
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
