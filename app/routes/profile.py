import re

from flask import redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..blueprints import main_bp
from ..database import DegreeOption, User, UserAvailability, UserSubject
from .common import (
    DAY_NAMES,
    MAX_PROFILE_UNITS,
    TIME_OPTIONS,
    UNIT_CODE_PATTERN,
    UWA_MAJORS,
    UWA_MINORS,
    VALID_UWA_2026_UNIT_CODES,
    get_degree_options_by_category,
)


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    degree_options = get_degree_options_by_category()
    user = current_user

    if request.method == "POST":
        form_type = request.form.get("form_type", "profile").strip().lower()

        submitted_email = request.form.get("email", "").strip()
        submitted_degree = request.form.get("degree", "").strip()
        submitted_degree_option_id = request.form.get("degree_option_id", type=int)
        submitted_major = request.form.get("major", "").strip()
        second_major = request.form.get("second_major", "").strip()
        minor = request.form.get("minor", "").strip()
        submitted_bio = request.form.get("bio", "").strip()
        submitted_sessions_per_week = request.form.get("sessions_per_week", "").strip()
        submitted_group_size = request.form.get("preferred_group_size", "").strip()
        submitted_study_mode = request.form.get("study_mode", "").strip()

        submitted_unit_items = []
        for key, value in request.form.items():
            if not key.startswith("unit"):
                continue
            suffix = key[4:]
            if not suffix.isdigit():
                continue
            submitted_unit_items.append((int(suffix), value.strip().upper()))

        submitted_unit_items.sort(key=lambda item: item[0])
        unit_values = [value for _, value in submitted_unit_items]
        profile_errors = []
        availability_errors = []
        submitted_availability_map = {day: [] for day in DAY_NAMES}
        valid_availability_rows = []

        selected_degree_option = None
        non_empty_units = [value for value in unit_values if value]

        if form_type == "profile":
            if not submitted_email:
                profile_errors.append("Email is required.")
            elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", submitted_email):
                profile_errors.append("Email format is invalid.")
            else:
                existing_user = User.query.filter_by(email=submitted_email).first()
                if existing_user and existing_user.id != user.id:
                    profile_errors.append("Email is already in use by another account.")

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

        if form_type == "subjects":
            if len(non_empty_units) > MAX_PROFILE_UNITS:
                profile_errors.append(f"You can add a maximum of {MAX_PROFILE_UNITS} units.")

            if len(non_empty_units) != len(set(non_empty_units)):
                profile_errors.append("Units must be unique.")

            for value in non_empty_units:
                if not UNIT_CODE_PATTERN.match(value):
                    profile_errors.append(f"{value} is invalid. Use 4 letters followed by 4 numbers.")
                    continue
                if VALID_UWA_2026_UNIT_CODES and value not in VALID_UWA_2026_UNIT_CODES:
                    profile_errors.append(f"{value} is not a valid UWA 2026 unit code.")

        if form_type == "availability":
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
            fallback_availability_map = {day: [] for day in DAY_NAMES}
            for item in user.availabilities:
                fallback_availability_map.setdefault(item.day_of_week, []).append((item.start_time, item.end_time))

            return render_template(
                "userpages.html",
                current_user=user,
                units=non_empty_units if form_type == "subjects" else [item.subject_code.upper() for item in user.subjects],
                availability_map=submitted_availability_map if form_type == "availability" else fallback_availability_map,
                day_names=DAY_NAMES,
                time_options=TIME_OPTIONS,
                degree_options=degree_options,
                profile_errors=profile_errors + availability_errors,
                open_profile_modal=True,
            )

        if form_type == "profile":
            user.email = submitted_email
            if selected_degree_option is not None:
                user.degree_option_id = selected_degree_option.id
                user.degree = selected_degree_option.name
            else:
                user.degree_option_id = None
                user.degree = submitted_degree
            user.major = submitted_major
            user.second_major = second_major or None
            user.minor = minor or None
            user.bio = submitted_bio
            user.sessions_per_week = int(submitted_sessions_per_week) if submitted_sessions_per_week else None
            user.preferred_group_size = submitted_group_size or None
            user.study_mode = submitted_study_mode or None

        elif form_type == "subjects":
            UserSubject.query.filter_by(user_id=user.id).delete()
            for value in non_empty_units:
                if value:
                    db.session.add(UserSubject(user_id=user.id, subject_code=value))

        elif form_type == "availability":
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
        return redirect(url_for("main.profile"))

    unit_codes = [item.subject_code.upper() for item in user.subjects]
    availability_map = {day: [] for day in DAY_NAMES}
    for item in user.availabilities:
        availability_map.setdefault(item.day_of_week, []).append((item.start_time, item.end_time))

    return render_template(
        "userpages.html",
        current_user=user,
        units=unit_codes,
        availability_map=availability_map,
        day_names=DAY_NAMES,
        time_options=TIME_OPTIONS,
        degree_options=degree_options,
        profile_errors=[],
        open_profile_modal=False,
    )


@main_bp.route("/units/search")
@login_required
def search_units():
    query = request.args.get("q", "").strip().upper()
    if not query:
        return {"units": []}

    if not re.match(r"^[A-Z0-9]+$", query):
        return {"units": []}

    matches = [code for code in VALID_UWA_2026_UNIT_CODES if code.startswith(query)]
    matches.sort()
    return {"units": matches[:12]}


@main_bp.route("/majors/search")
def search_majors():
    query = request.args.get("q", "").strip().lower()
    if len(query) < 2:
        return {"majors": []}

    if not re.match(r"^[a-z0-9 '&/-]+$", query):
        return {"majors": []}

    matches = [major for major in UWA_MAJORS if query in major.lower()]
    return {"majors": matches[:12]}


@main_bp.route("/minors/search")
def search_minors():
    query = request.args.get("q", "").strip().lower()
    if len(query) < 2:
        return {"minors": []}

    if not re.match(r"^[a-z0-9 '&/-]+$", query):
        return {"minors": []}

    matches = [minor for minor in UWA_MINORS if query in minor.lower()]
    return {"minors": matches[:12]}
