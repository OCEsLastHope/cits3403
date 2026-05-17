import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from flask import current_app, has_app_context, url_for
from flask_login import current_user
from flask_mail import Message as MailMessage
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import func, or_

from .. import db, mail
from ..database import (
    DegreeOption,
    Event,
    EventAttendee,
    FriendRequest,
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
EVENT_VISIBILITY_MODES = {"invite_only", "open"}
ATTENDEE_STATUSES = {"invited", "accepted", "declined", "left"}
MAX_PROFILE_UNITS = 6
UNIT_CODE_PATTERN = re.compile(r"^[A-Z]{4}[0-9]{4}$")
ONBOARDING_STEP_ENDPOINTS = {
    1: "dashboard",
    2: "matches",
    3: "people",
    4: "messages_inbox",
    5: "events_page",
    6: "notifications",
    7: "profile",
}
ONBOARDING_STEP_COPY = {
    1: "This is your dashboard. You can track upcoming meetings and suggested matches here.",
    2: "This is your matches page. StudyCollabz ranks people by overlapping availability and profile fit.",
    3: "This is your people page. Search students and send friend requests before starting conversations.",
    4: "This is your messages page. Use it to chat and coordinate study sessions.",
    5: "This is your events page. Create or join sessions to plan study time.",
    6: "This is your notifications page. Track invites, mentions, and request updates in one place.",
    7: "This is your profile. Add at least one unit and one availability slot, then finish onboarding.",
}


def load_valid_uwa_2026_unit_codes():
    app_root = Path(current_app.root_path) if has_app_context() else Path(__file__).resolve().parent
    data_path = app_root.parent / "data" / "uwa_2026_unit_codes.txt"
    if not data_path.exists():
        return set()
    return {
        line.strip().upper()
        for line in data_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


VALID_UWA_2026_UNIT_CODES = load_valid_uwa_2026_unit_codes()


def load_uwa_majors():
    app_root = Path(current_app.root_path) if has_app_context() else Path(__file__).resolve().parent
    data_path = app_root.parent / "data" / "uwa_majors.txt"
    if not data_path.exists():
        return []
    majors = []
    for line in data_path.read_text(encoding="utf-8").splitlines():
        major = line.strip()
        if major:
            majors.append(major)
    return sorted(set(majors), key=str.lower)


UWA_MAJORS = load_uwa_majors()


def load_uwa_minors():
    app_root = Path(current_app.root_path) if has_app_context() else Path(__file__).resolve().parent
    data_path = app_root.parent / "data" / "uwa_minors.txt"
    if not data_path.exists():
        return []
    minors = []
    for line in data_path.read_text(encoding="utf-8").splitlines():
        minor = line.strip()
        if minor:
            minors.append(minor)
    return sorted(set(minors), key=str.lower)


UWA_MINORS = load_uwa_minors()


def get_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generate_reset_token(email):
    return get_serializer().dumps(email, salt="password-reset-salt")


def verify_reset_token(token, expiration=1800):
    try:
        return get_serializer().loads(token, salt="password-reset-salt", max_age=expiration)
    except Exception:
        return None


def send_reset_email(user):
    token = generate_reset_token(user.email)
    reset_link = url_for("main.reset_password", token=token, _external=True)

    msg = MailMessage(
        subject="Reset your StudyCollabz password",
        recipients=[user.email],
        body=f"""
Hi {user.first_name},

We received a request to reset your StudyCollabz password.

Click the link below to reset your password:

{reset_link}

This link expires in 30 minutes.

If you did not request this, you can safely ignore this email.

StudyCollabz
""",
    )
    mail.send(msg)


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
    if not current_user.is_authenticated:
        return None
    return current_user


def get_friend_pair_ids(user_a_id, user_b_id):
    return (user_a_id, user_b_id) if user_a_id < user_b_id else (user_b_id, user_a_id)


def get_friend_request_between(user_a_id, user_b_id):
    low_id, high_id = get_friend_pair_ids(user_a_id, user_b_id)
    return FriendRequest.query.filter_by(user_low_id=low_id, user_high_id=high_id).first()


def get_onboarding_step_for_user(user):
    step = user.onboarding_step or 1
    if step not in ONBOARDING_STEP_ENDPOINTS:
        return 1
    return step


def get_onboarding_target_endpoint(user):
    return ONBOARDING_STEP_ENDPOINTS[get_onboarding_step_for_user(user)]


def can_finish_onboarding(user):
    has_degree = bool((user.degree or "").strip()) or user.degree_option_id is not None
    subjects = UserSubject.query.filter_by(user_id=user.id).all()
    subject_codes = [subject.subject_code.strip().upper() for subject in subjects if subject.subject_code]

    if len(subject_codes) > MAX_PROFILE_UNITS or len(subject_codes) != len(set(subject_codes)) or not subject_codes:
        return False

    for code in subject_codes:
        if not UNIT_CODE_PATTERN.match(code):
            return False
        if VALID_UWA_2026_UNIT_CODES and code not in VALID_UWA_2026_UNIT_CODES:
            return False

    has_availability = UserAvailability.query.filter_by(user_id=user.id).first() is not None
    return has_degree and has_availability


def parse_mentions(body):
    return re.findall(r"@(\w+)", body)


def notify_mentions(message, conversation_id):
    mentioned_usernames = parse_mentions(message.body)
    for username in mentioned_usernames:
        mentioned_user = User.query.filter_by(username=username).first()
        if mentioned_user and mentioned_user.id != message.sender_id:
            db.session.add(
                Notification(
                    user_id=mentioned_user.id,
                    sender_name=message.sender.username,
                    type="mention",
                    message=f"<strong>@{mentioned_user.username}</strong>: {message.body[:80]}",
                    channel=f"conversation:{conversation_id}",
                )
            )


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


def normalise_text(value):
    if not value:
        return ""
    return value.strip().lower()


def get_shared_unit_score(shared_unit_count):
    return shared_unit_count * 100


def calculate_academic_score(requester, candidate):
    score = 0
    matched_fields = []

    requester_major = normalise_text(requester.major)
    requester_second_major = normalise_text(requester.second_major)
    requester_minor = normalise_text(requester.minor)
    candidate_major = normalise_text(candidate.major)
    candidate_second_major = normalise_text(candidate.second_major)
    candidate_minor = normalise_text(candidate.minor)

    requester_major_fields = {requester_major, requester_second_major} - {""}
    candidate_major_fields = {candidate_major, candidate_second_major} - {""}
    shared_major_fields = requester_major_fields.intersection(candidate_major_fields)

    for shared_field in shared_major_fields:
        score += 70
        if requester_major == candidate_major == shared_field:
            matched_fields.append("Same major")
        elif requester_second_major == candidate_second_major == shared_field:
            matched_fields.append("Same second major")
        else:
            matched_fields.append("Major/second major match")

    if requester_minor and requester_minor == candidate_minor:
        score += 25
        matched_fields.append("Same minor")
    if requester_minor and requester_minor in candidate_major_fields:
        score += 25
        matched_fields.append("Your minor matches their major/second major")
    if candidate_minor and candidate_minor in requester_major_fields:
        score += 25
        matched_fields.append("Their minor matches your major/second major")

    same_degree = (
        requester.degree_option_id is not None and candidate.degree_option_id == requester.degree_option_id
    ) or (
        requester.degree and candidate.degree and requester.degree.strip().lower() == candidate.degree.strip().lower()
    )

    if same_degree:
        score += 20
        matched_fields.append("Same degree")

    return score, matched_fields, same_degree


def calculate_availability_score(overlap_by_day):
    valid_overlap_days = 0
    useful_overlap_days = 0
    strong_overlap_days = 0
    overlap_minutes_total = 0
    strongest_single_day_overlap = 0

    for overlaps in overlap_by_day.values():
        day_total = 0
        for start_time, end_time in overlaps:
            day_total += time_to_minutes(end_time) - time_to_minutes(start_time)
        overlap_minutes_total += day_total
        if day_total >= 30:
            valid_overlap_days += 1
        if day_total >= 45:
            useful_overlap_days += 1
        if day_total >= 90:
            strong_overlap_days += 1
        strongest_single_day_overlap = max(strongest_single_day_overlap, day_total)

    if valid_overlap_days == 0:
        return None

    overlap_hours_total = overlap_minutes_total / 60
    strongest_day_hours = strongest_single_day_overlap / 60
    availability_score = (
        valid_overlap_days * 25
        + useful_overlap_days * 35
        + strong_overlap_days * 45
        + overlap_hours_total * 25
        + strongest_day_hours * 15
    )

    return {
        "availability_score": availability_score,
        "valid_overlap_days": valid_overlap_days,
        "useful_overlap_days": useful_overlap_days,
        "strong_overlap_days": strong_overlap_days,
        "overlap_minutes_total": overlap_minutes_total,
        "strongest_single_day_overlap": strongest_single_day_overlap,
    }


def find_matches(user_id, selected_degree_option_id=None, selected_unit_codes=None):
    requester = db.session.get(User, user_id)
    if not requester:
        return []

    requester_availability = UserAvailability.query.filter_by(user_id=requester.id).all()
    if not requester_availability:
        return []

    requester_units = {subject.subject_code.upper() for subject in UserSubject.query.filter_by(user_id=requester.id).all()}
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

        _, overlap_by_day = build_overlap_summary(requester_availability, candidate_availability)
        availability_data = calculate_availability_score(overlap_by_day)
        if availability_data is None:
            continue

        candidate_units = {subject.subject_code.upper() for subject in UserSubject.query.filter_by(user_id=candidate.id).all()}
        shared_units = sorted(requester_units.intersection(candidate_units))

        if selected_unit_codes and not set(selected_unit_codes).intersection(shared_units):
            continue

        shared_unit_count = len(shared_units)
        unit_score = get_shared_unit_score(shared_unit_count)
        academic_score, matched_academic_fields, same_degree = calculate_academic_score(requester, candidate)
        match_score = unit_score + academic_score + availability_data["availability_score"]

        match_results.append(
            {
                "user": candidate,
                "match_score": round(match_score, 2),
                "shared_units": shared_units,
                "shared_unit_count": shared_unit_count,
                "unit_score": unit_score,
                "academic_score": academic_score,
                "matched_academic_fields": matched_academic_fields,
                "same_degree": same_degree,
                "availability_score": round(availability_data["availability_score"], 2),
                "overlap_minutes_total": availability_data["overlap_minutes_total"],
                "overlap_by_day": overlap_by_day,
                "valid_overlap_days": availability_data["valid_overlap_days"],
                "useful_overlap_days": availability_data["useful_overlap_days"],
                "strong_overlap_days": availability_data["strong_overlap_days"],
                "strongest_single_day_overlap": availability_data["strongest_single_day_overlap"],
            }
        )

    match_results.sort(key=lambda item: item["match_score"], reverse=True)
    return match_results


def parse_event_datetime(value):
    try:
        return datetime.fromisoformat(value.strip())
    except (TypeError, ValueError, AttributeError):
        return None


def count_event_accepted_attendees(event):
    return sum(1 for attendee in event.attendees if attendee.invite_status == "accepted")


def is_event_full(event):
    if event.max_attendees is None:
        return False
    return count_event_accepted_attendees(event) >= event.max_attendees


def find_event_overlap_for_user(user_id, start_at, end_at, exclude_event_id=None):
    query = (
        Event.query.join(EventAttendee, EventAttendee.event_id == Event.id)
        .filter(Event.status == "scheduled")
        .filter(EventAttendee.user_id == user_id)
        .filter(EventAttendee.invite_status == "accepted")
        .filter(Event.end_at > start_at)
        .filter(Event.start_at < end_at)
    )
    if exclude_event_id is not None:
        query = query.filter(Event.id != exclude_event_id)
    return query.order_by(Event.start_at.asc()).first()


def build_event_card_data(event, user_id):
    attendee_record = next((item for item in event.attendees if item.user_id == user_id), None)
    attendee_status_counts = {key: 0 for key in ATTENDEE_STATUSES}
    for attendee in event.attendees:
        if attendee.invite_status in attendee_status_counts:
            attendee_status_counts[attendee.invite_status] += 1
    return {
        "event": event,
        "attendee_record": attendee_record,
        "accepted_count": attendee_status_counts["accepted"],
        "status_counts": attendee_status_counts,
        "is_full": is_event_full(event),
        "is_creator": event.creator_user_id == user_id,
    }
