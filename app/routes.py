import re
from datetime import datetime
from collections import defaultdict
from pathlib import Path

from flask import abort, current_app, flash, has_app_context, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, or_
from flask_socketio import emit, join_room
from email_validator import validate_email, EmailNotValidError

from . import db, socketio, mail
from flask_mail import Message as MailMessage
from itsdangerous import URLSafeTimedSerializer
from .blueprints import main_bp
from .database import (
    Conversation,
    ConversationMember,
    DegreeOption,
    Event,
    EventAttendee,
    FriendRequest,
    Invitation,
    Message,
    MessageRead,
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
EVENT_STATUSES = {"scheduled", "cancelled"}
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
    2: "This is matches. StudySync ranks people by overlapping availability and profile fit.",
    3: "This is people. Search students and send friend requests before starting conversations.",
    4: "This is messages. Use it to chat and coordinate study sessions.",
    5: "This is events. Create or join sessions to plan study time.",
    6: "This is notifications. Track invites, mentions, and request updates in one place.",
    7: "This is profile. Add at least one unit and one availability slot, then finish onboarding.",
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
        email = get_serializer().loads(
            token,
            salt="password-reset-salt",
            max_age=expiration
        )

        return email

    except Exception:
        return None
    
def send_reset_email(user):

    token = generate_reset_token(user.email)

    reset_link = url_for(
        "main.reset_password",
        token=token,
        _external=True
    )

    msg = MailMessage(
        subject="Reset your StudySync password",

        recipients=[user.email],

        body=f"""
Hi {user.first_name},

We received a request to reset your StudySync password.

Click the link below to reset your password:

{reset_link}

This link expires in 30 minutes.

If you did not request this, you can safely ignore this email.

StudySync
"""
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

    if len(subject_codes) > MAX_PROFILE_UNITS:
        return False

    if len(subject_codes) != len(set(subject_codes)):
        return False

    if not subject_codes:
        return False

    for code in subject_codes:
        if not UNIT_CODE_PATTERN.match(code):
            return False
        if VALID_UWA_2026_UNIT_CODES and code not in VALID_UWA_2026_UNIT_CODES:
            return False

    has_availability = UserAvailability.query.filter_by(user_id=user.id).first() is not None
    return has_degree and has_availability


@main_bp.app_context_processor
def inject_onboarding_guide():
    if not current_user.is_authenticated or current_user.onboarding_completed:
        return {"onboarding_guide": None}
    step = get_onboarding_step_for_user(current_user)
    target_endpoint = f"main.{ONBOARDING_STEP_ENDPOINTS[step]}"
    if request.endpoint != target_endpoint:
        return {"onboarding_guide": None}
    return {
        "onboarding_guide": {
            "step": step,
            "total_steps": len(ONBOARDING_STEP_ENDPOINTS),
            "message": ONBOARDING_STEP_COPY.get(step, ""),
            "show_finish": step == len(ONBOARDING_STEP_ENDPOINTS),
        }
    }


@main_bp.before_app_request
def require_onboarding_completion():
    if not current_user.is_authenticated or current_user.onboarding_completed:
        return None
    if request.endpoint is None:
        return None
    onboarding_nav_endpoints = {f"main.{endpoint}" for endpoint in ONBOARDING_STEP_ENDPOINTS.values()}
    allowed_endpoints = {"main.onboarding", "main.onboarding_advance", "main.logout", "static"}.union(onboarding_nav_endpoints)
    if request.endpoint in allowed_endpoints:
        return None
    target_endpoint = f"main.{get_onboarding_target_endpoint(current_user)}"
    if request.endpoint != target_endpoint:
        return redirect(url_for(target_endpoint))
    return None

def parse_mentions(body):
    """Extract @username mentions from a message body."""
    return re.findall(r"@(\w+)", body)

def notify_mentions(message, conversation_id):
    """Create Notification records for @mentioned users."""
    mentioned_usernames = parse_mentions(message.body)
    for username in mentioned_usernames:
        mentioned_user = User.query.filter_by(username=username).first()
        if mentioned_user and mentioned_user.id != message.sender_id:
            notif = Notification(
                user_id=mentioned_user.id,
                sender_name=message.sender.username,
                type="mention",
                message=f"<strong>@{mentioned_user.username}</strong>: {message.body[:80]}",
                channel=f"conversation:{conversation_id}",
            )

            db.session.add(notif)



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

    requester_major_fields = {
        requester_major,
        requester_second_major,
    } - {""}

    candidate_major_fields = {
        candidate_major,
        candidate_second_major,
    } - {""}

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
        requester.degree_option_id is not None
        and candidate.degree_option_id == requester.degree_option_id
    ) or (
        requester.degree
        and candidate.degree
        and requester.degree.strip().lower() == candidate.degree.strip().lower()
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
            day_total += (
                time_to_minutes(end_time)
                - time_to_minutes(start_time)
            )

        overlap_minutes_total += day_total

        if day_total >= 30:
            valid_overlap_days += 1

        if day_total >= 45:
            useful_overlap_days += 1

        if day_total >= 90:
            strong_overlap_days += 1

        strongest_single_day_overlap = max(
            strongest_single_day_overlap,
            day_total
        )

    # Require at least one meaningful overlap day
    if valid_overlap_days == 0:
        return None

    overlap_hours_total = overlap_minutes_total / 60
    strongest_day_hours = strongest_single_day_overlap / 60

    # Balanced availability weighting.
    # Availability matters a lot,
    # but should not overpower academic compatibility.

    availability_score = (
        # Consistency across days
        valid_overlap_days * 25

        # Better overlap quality
        + useful_overlap_days * 35
        + strong_overlap_days * 45

        # Total overlap time
        + overlap_hours_total * 25

        # Strongest single study session
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

    requester_availability = UserAvailability.query.filter_by(
        user_id=requester.id
    ).all()

    if not requester_availability:
        return []

    requester_units = {
        subject.subject_code.upper()
        for subject in UserSubject.query.filter_by(
            user_id=requester.id
        ).all()
    }

    requester_days = sorted({
        slot.day_of_week
        for slot in requester_availability
    })

    candidate_query = (
        User.query
        .join(
            UserAvailability,
            UserAvailability.user_id == User.id
        )
        .filter(User.id != requester.id)
        .filter(
            UserAvailability.day_of_week.in_(requester_days)
        )
    )

    if selected_degree_option_id is not None:
        degree_option = DegreeOption.query.filter_by(
            id=selected_degree_option_id,
            is_active=True
        ).first()

        if degree_option:
            candidate_query = candidate_query.filter(
                or_(
                    User.degree_option_id
                    == selected_degree_option_id,

                    func.lower(
                        func.trim(User.degree)
                    ) == degree_option.name.strip().lower(),
                )
            )

    candidates = candidate_query.distinct().all()

    match_results = []

    for candidate in candidates:
        candidate_availability = (
            UserAvailability.query.filter_by(
                user_id=candidate.id
            ).all()
        )

        if not candidate_availability:
            continue

        _, overlap_by_day = build_overlap_summary(
            requester_availability,
            candidate_availability
        )

        availability_data = calculate_availability_score(
            overlap_by_day
        )

        if availability_data is None:
            continue

        candidate_units = {
            subject.subject_code.upper()
            for subject in UserSubject.query.filter_by(
                user_id=candidate.id
            ).all()
        }

        shared_units = sorted(
            requester_units.intersection(candidate_units)
        )

        if selected_unit_codes and not set(selected_unit_codes).intersection(shared_units):
            continue

        shared_unit_count = len(shared_units)

        unit_score = get_shared_unit_score(
            shared_unit_count
        )

        (
            academic_score,
            matched_academic_fields,
            same_degree
        ) = calculate_academic_score(
            requester,
            candidate
        )

        match_score = (
            unit_score
            + academic_score
            + availability_data["availability_score"]
        )

        match_results.append({
            "user": candidate,

            "match_score": round(match_score, 2),

            "shared_units": shared_units,
            "shared_unit_count": shared_unit_count,
            "unit_score": unit_score,

            "academic_score": academic_score,
            "matched_academic_fields": matched_academic_fields,
            "same_degree": same_degree,

            "availability_score":
                round(
                    availability_data["availability_score"],
                    2
                ),

            "overlap_minutes_total":
                availability_data["overlap_minutes_total"],

            "overlap_by_day": overlap_by_day,

            "valid_overlap_days":
                availability_data["valid_overlap_days"],

            "useful_overlap_days":
                availability_data["useful_overlap_days"],

            "strong_overlap_days":
                availability_data["strong_overlap_days"],

            "strongest_single_day_overlap":
                availability_data[
                    "strongest_single_day_overlap"
                ],
        })

    # True weighted ranking
    match_results.sort(
        key=lambda item: item["match_score"],
        reverse=True
    )

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


@main_bp.route("/")
def landing():
    return render_template("landing.html")


@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter(
            or_(
                User.username == identifier,
                User.email == identifier,
            )
        ).first()

        if user is None or not user.check_password(password):
            flash("Invalid username/email or password.", "error")
            return render_template("loginpage.html")

        login_user(user, remember=remember)
        if not user.onboarding_completed:
            return redirect(url_for("main.onboarding"))
        return redirect(url_for("main.dashboard"))

    return render_template("loginpage.html")


@main_bp.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        identifier = request.form.get("identifier", "").strip()

        user = User.query.filter(
            or_(
                User.email == identifier,
                User.username == identifier
            )
        ).first()

        if user:
            send_reset_email(user)

        flash(
            "If an account exists with that email or username, a reset link has been sent.",
            "info"
        )

        return redirect(url_for("main.login"))

    return render_template("forgot_password.html")

@main_bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):

    email = verify_reset_token(token)

    if not email:
        flash("Invalid or expired reset link.", "error")
        return redirect(url_for("main.forgot_password"))

    user = User.query.filter_by(email=email).first()

    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("main.forgot_password"))

    if request.method == "POST":

        password = request.form.get("password", "").strip()

        confirm_password = request.form.get("confirm_password", "").strip()

        if not password or password != confirm_password:
            flash("Passwords must match.", "error")
            return redirect(request.url)

        user.set_password(password)

        db.session.commit()

        flash("Password reset successful. Please log in.", "success")

        return redirect(url_for("main.login"))

    return render_template("reset_password.html")




@main_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    if not user:
        # Fallback for demo if no session is active
        user = db.session.get(User, 1)

    stats = {
        "total_matches": 0,
        "active_sessions": 0,
        "pending_requests": 0,
    }

    if user:
        # Get the top 3 matches for the dashboard preview
        all_matches = find_matches(user.id)
        stats["total_matches"] = len(all_matches)
        suggested_matches = all_matches[:3]

        # Get all upcoming accepted meetings for the scrollbox
        now = datetime.utcnow()
        upcoming_events = (
            Event.query.join(EventAttendee, EventAttendee.event_id == Event.id)
            .filter(Event.status == "scheduled")
            .filter(Event.end_at >= now)
            .filter(EventAttendee.user_id == user.id)
            .filter(EventAttendee.invite_status == "accepted")
            .order_by(Event.start_at.asc())
            .all()
        )
        stats["active_sessions"] = len(upcoming_events)

        # Count pending invitations and event invites
        pending_study_invites = Invitation.query.filter_by(receiver_id=user.id, status="pending").count()
        pending_event_invites = EventAttendee.query.filter_by(user_id=user.id, invite_status="invited").count()
        stats["pending_requests"] = pending_study_invites + pending_event_invites

    return render_template(
        "dashboard.html",
        current_user=user,
        suggested_matches=suggested_matches,
        upcoming_events=upcoming_events,
        stats=stats,
    )


@main_bp.route("/onboarding", methods=["GET"])
@login_required
def onboarding():
    if current_user.onboarding_completed:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for(f"main.{get_onboarding_target_endpoint(current_user)}"))
@main_bp.route("/onboarding/advance", methods=["POST"])
@login_required
def onboarding_advance():
    if current_user.onboarding_completed:
        return redirect(url_for("main.dashboard"))
    action = request.form.get("action", "next")
    step = get_onboarding_step_for_user(current_user)
    max_step = len(ONBOARDING_STEP_ENDPOINTS)
    if action == "back":
        current_user.onboarding_step = max(1, step - 1)
    elif action == "finish":
        if not can_finish_onboarding(current_user):
            flash(
                "Before finishing, ensure degree is set and add valid units (max 6, unique UWA codes) plus at least one availability slot in Profile.",
                "error",
            )
            current_user.onboarding_step = max_step
            db.session.commit()
            return redirect(url_for("main.profile"))
        current_user.onboarding_completed = True
        db.session.commit()
        flash("Onboarding complete. Welcome to StudySync!", "success")
        return redirect(url_for("main.dashboard"))
    else:
        current_user.onboarding_step = min(max_step, step + 1)
    db.session.commit()
    return redirect(url_for(f"main.{get_onboarding_target_endpoint(current_user)}"))


@main_bp.route("/events")
@login_required
def events_page():
    now = datetime.utcnow()

    my_upcoming_events = (
        Event.query.join(EventAttendee, EventAttendee.event_id == Event.id)
        .filter(Event.status == "scheduled")
        .filter(Event.end_at >= now)
        .filter(EventAttendee.user_id == current_user.id)
        .filter(EventAttendee.invite_status == "accepted")
        .order_by(Event.start_at.asc())
        .all()
    )

    invitation_events = (
        Event.query.join(EventAttendee, EventAttendee.event_id == Event.id)
        .filter(Event.status == "scheduled")
        .filter(EventAttendee.user_id == current_user.id)
        .filter(EventAttendee.invite_status == "invited")
        .filter(Event.creator_user_id != current_user.id)
        .order_by(Event.start_at.asc())
        .all()
    )

    open_events = (
        Event.query.filter_by(status="scheduled", visibility_mode="open")
        .filter(Event.end_at >= now)
        .filter(Event.creator_user_id != current_user.id)
        .order_by(Event.start_at.asc())
        .all()
    )

    past_events = (
        Event.query.join(EventAttendee, EventAttendee.event_id == Event.id)
        .filter(EventAttendee.user_id == current_user.id)
        .filter(Event.end_at < now)
        .order_by(Event.start_at.desc())
        .all()
    )

    available_invite_users = User.query.filter(User.id != current_user.id).order_by(User.username.asc()).all()

    return render_template(
        "events.html",
        current_user=current_user,
        my_upcoming_events=[build_event_card_data(event, current_user.id) for event in my_upcoming_events],
        invitation_events=[build_event_card_data(event, current_user.id) for event in invitation_events],
        open_events=[build_event_card_data(event, current_user.id) for event in open_events],
        past_events=[build_event_card_data(event, current_user.id) for event in past_events],
        available_invite_users=available_invite_users,
        now=now,
    )


@main_bp.route("/events/create", methods=["POST"])
@login_required
def create_event():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    location_or_link = request.form.get("location_or_link", "").strip()
    visibility_mode = request.form.get("visibility_mode", "invite_only").strip()
    max_attendees_raw = request.form.get("max_attendees", "").strip()
    start_at = parse_event_datetime(request.form.get("start_at"))
    end_at = parse_event_datetime(request.form.get("end_at"))

    if not title or len(title) < 3 or len(title) > 120:
        flash("Event title must be between 3 and 120 characters.", "error")
        return redirect(url_for("main.events_page"))

    if visibility_mode not in EVENT_VISIBILITY_MODES:
        flash("Invalid event type.", "error")
        return redirect(url_for("main.events_page"))

    if start_at is None or end_at is None:
        flash("Valid start and end times are required.", "error")
        return redirect(url_for("main.events_page"))

    if end_at <= start_at:
        flash("Event end time must be after start time.", "error")
        return redirect(url_for("main.events_page"))

    if (end_at - start_at).total_seconds() > 12 * 3600:
        flash("Event duration cannot exceed 12 hours.", "error")
        return redirect(url_for("main.events_page"))

    max_attendees = None
    if max_attendees_raw:
        if not max_attendees_raw.isdigit():
            flash("Max attendees must be a number.", "error")
            return redirect(url_for("main.events_page"))
        max_attendees = int(max_attendees_raw)
        if max_attendees < 2 or max_attendees > 100:
            flash("Max attendees must be between 2 and 100.", "error")
            return redirect(url_for("main.events_page"))

    if visibility_mode == "open" and max_attendees is None:
        flash("Open events must include a max attendee limit.", "error")
        return redirect(url_for("main.events_page"))

    event = Event(
        creator_user_id=current_user.id,
        title=title,
        description=description or None,
        location_or_link=location_or_link or None,
        visibility_mode=visibility_mode,
        max_attendees=max_attendees,
        start_at=start_at,
        end_at=end_at,
        status="scheduled",
    )
    db.session.add(event)
    db.session.flush()

    db.session.add(
        EventAttendee(
            event_id=event.id,
            user_id=current_user.id,
            invite_status="accepted",
            responded_at=datetime.utcnow(),
        )
    )

    db.session.commit()
    flash("Event created successfully.", "success")
    return redirect(url_for("main.events_page"))


@main_bp.route("/events/<int:event_id>/edit", methods=["POST"])
@login_required
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.creator_user_id != current_user.id:
        abort(403)
    if event.status != "scheduled":
        flash("Only scheduled events can be edited.", "error")
        return redirect(url_for("main.events_page"))

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    location_or_link = request.form.get("location_or_link", "").strip()
    visibility_mode = request.form.get("visibility_mode", "invite_only").strip()
    max_attendees_raw = request.form.get("max_attendees", "").strip()
    start_at = parse_event_datetime(request.form.get("start_at"))
    end_at = parse_event_datetime(request.form.get("end_at"))

    if not title or len(title) < 3 or len(title) > 120:
        flash("Event title must be between 3 and 120 characters.", "error")
        return redirect(url_for("main.events_page"))
    if visibility_mode not in EVENT_VISIBILITY_MODES:
        flash("Invalid event type.", "error")
        return redirect(url_for("main.events_page"))
    if start_at is None or end_at is None:
        flash("Valid start and end times are required.", "error")
        return redirect(url_for("main.events_page"))
    if end_at <= start_at:
        flash("Event end time must be after start time.", "error")
        return redirect(url_for("main.events_page"))

    max_attendees = None
    if max_attendees_raw:
        if not max_attendees_raw.isdigit():
            flash("Max attendees must be a number.", "error")
            return redirect(url_for("main.events_page"))
        max_attendees = int(max_attendees_raw)
        if max_attendees < 2 or max_attendees > 100:
            flash("Max attendees must be between 2 and 100.", "error")
            return redirect(url_for("main.events_page"))

    if visibility_mode == "open" and max_attendees is None:
        flash("Open events must include a max attendee limit.", "error")
        return redirect(url_for("main.events_page"))

    accepted_count = count_event_accepted_attendees(event)
    if max_attendees is not None and accepted_count > max_attendees:
        flash("Max attendees cannot be below current accepted attendee count.", "error")
        return redirect(url_for("main.events_page"))

    event.title = title
    event.description = description or None
    event.location_or_link = location_or_link or None
    event.visibility_mode = visibility_mode
    event.max_attendees = max_attendees
    event.start_at = start_at
    event.end_at = end_at

    accepted_attendees = [item for item in event.attendees if item.user_id != current_user.id and item.invite_status == "accepted"]
    for attendee in accepted_attendees:
        db.session.add(
            Notification(
                user_id=attendee.user_id,
                sender_name=current_user.username,
                type="event",
                message=f"Event updated: <strong>{event.title}</strong> now starts at {event.start_at.strftime('%Y-%m-%d %H:%M')}.",
                channel="Events",
            )
        )

    db.session.commit()
    flash("Event updated.", "success")
    return redirect(url_for("main.events_page"))


@main_bp.route("/events/<int:event_id>/cancel", methods=["POST"])
@login_required
def cancel_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.creator_user_id != current_user.id:
        abort(403)
    if event.status != "scheduled":
        flash("Event is already cancelled.", "info")
        return redirect(url_for("main.events_page"))

    event.status = "cancelled"

    for attendee in event.attendees:
        if attendee.user_id == current_user.id or attendee.invite_status == "declined":
            continue
        db.session.add(
            Notification(
                user_id=attendee.user_id,
                sender_name=current_user.username,
                type="event",
                message=f"Event cancelled: <strong>{event.title}</strong>.",
                channel="Events",
            )
        )

    db.session.commit()
    flash("Event cancelled.", "success")
    return redirect(url_for("main.events_page"))


@main_bp.route("/events/<int:event_id>/invite", methods=["POST"])
@login_required
def invite_to_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.creator_user_id != current_user.id:
        abort(403)
    if event.status != "scheduled":
        flash("Cannot invite attendees to a cancelled event.", "error")
        return redirect(url_for("main.events_page"))

    identifiers = request.form.get("invite_identifiers", "")
    raw_items = [item.strip() for item in identifiers.split(",") if item.strip()]
    if not raw_items:
        flash("Enter at least one username or email to invite.", "error")
        return redirect(url_for("main.events_page"))

    if len(raw_items) > 20:
        flash("You can invite up to 20 users per event at a time.", "error")
        return redirect(url_for("main.events_page"))

    invited_count = 0
    skipped_count = 0

    for identifier in raw_items:
        user = User.query.filter(or_(User.username == identifier, User.email == identifier)).first()
        if user is None or user.id == current_user.id:
            skipped_count += 1
            continue

        existing = EventAttendee.query.filter_by(event_id=event.id, user_id=user.id).first()
        if existing is not None:
            skipped_count += 1
            continue

        db.session.add(EventAttendee(event_id=event.id, user_id=user.id, invite_status="invited"))
        db.session.add(
            Notification(
                user_id=user.id,
                sender_name=current_user.username,
                type="event",
                message=f"You were invited to <strong>{event.title}</strong>.",
                channel="Events",
            )
        )
        invited_count += 1

    db.session.commit()

    if invited_count:
        flash(f"Sent {invited_count} event invite(s).", "success")
    if skipped_count:
        flash(f"Skipped {skipped_count} user(s) (not found, self, or already invited).", "info")
    return redirect(url_for("main.events_page"))


@main_bp.route("/events/<int:event_id>/join", methods=["POST"])
@login_required
def join_open_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.status != "scheduled" or event.visibility_mode != "open":
        flash("This event is not open for joining.", "error")
        return redirect(url_for("main.events_page"))

    attendee = EventAttendee.query.filter_by(event_id=event.id, user_id=current_user.id).first()
    if attendee and attendee.invite_status == "accepted":
        flash("You already joined this event.", "info")
        return redirect(url_for("main.events_page"))

    if is_event_full(event):
        flash("Event is full.", "error")
        return redirect(url_for("main.events_page"))

    if attendee is None:
        attendee = EventAttendee(event_id=event.id, user_id=current_user.id)
        db.session.add(attendee)

    attendee.invite_status = "accepted"
    attendee.responded_at = datetime.utcnow()

    if event.creator_user_id != current_user.id:
        db.session.add(Notification(
            user_id=event.creator_user_id,
            sender_name=current_user.username,
            type="event",
            message=f"<strong>{current_user.username}</strong> joined your event: <strong>{event.title}</strong>.",
            channel="Events",
        ))

    db.session.commit()
    flash("You joined the event.", "success")
    return redirect(url_for("main.events_page"))


@main_bp.route("/events/<int:event_id>/respond", methods=["POST"])
@login_required
def respond_to_event_invite(event_id):
    event = Event.query.get_or_404(event_id)
    action = request.form.get("action", "").strip()
    confirm_conflict = request.form.get("confirm_conflict") == "1"

    attendee = EventAttendee.query.filter_by(event_id=event.id, user_id=current_user.id).first()
    if attendee is None:
        abort(403)

    if action not in {"accept", "decline"}:
        flash("Invalid invite response.", "error")
        return redirect(url_for("main.events_page"))

    if event.status != "scheduled":
        flash("This event is no longer active.", "error")
        return redirect(url_for("main.events_page"))

    if action == "decline":
        attendee.invite_status = "declined"
        attendee.responded_at = datetime.utcnow()
        db.session.commit()
        flash("Invitation declined.", "info")
        return redirect(url_for("main.events_page"))

    overlap = find_event_overlap_for_user(current_user.id, event.start_at, event.end_at, exclude_event_id=event.id)
    if overlap is not None and not confirm_conflict:
        flash(
            f"Schedule conflict with '{overlap.title}'. Click accept again to confirm.",
            "error",
        )
        return redirect(url_for("main.events_page"))

    if is_event_full(event) and attendee.invite_status != "accepted":
        flash("Event is full.", "error")
        return redirect(url_for("main.events_page"))

    attendee.invite_status = "accepted"
    attendee.responded_at = datetime.utcnow()
    db.session.commit()
    flash("Invitation accepted.", "success")
    return redirect(url_for("main.events_page"))


@main_bp.route("/events/<int:event_id>/leave", methods=["POST"])
@login_required
def leave_event(event_id):
    event = Event.query.get_or_404(event_id)
    attendee = EventAttendee.query.filter_by(event_id=event.id, user_id=current_user.id).first()
    if attendee is None:
        abort(403)
    if event.creator_user_id == current_user.id:
        flash("Event creators cannot leave their own event. Cancel it instead.", "error")
        return redirect(url_for("main.events_page"))

    attendee.invite_status = "left"
    attendee.responded_at = datetime.utcnow()
    db.session.commit()
    flash("You left the event.", "info")
    return redirect(url_for("main.events_page"))


@main_bp.route("/matches")
@login_required
def matches():
    selected_degree_option_id = request.args.get("degree_option_id", type=int)
    selected_unit_codes_raw = request.args.get("unit_codes", "")
    selected_unit_codes = []
    invalid_unit_codes = []

    for item in selected_unit_codes_raw.split(","):
        unit_code = item.strip().upper()
        if not unit_code:
            continue
        if not UNIT_CODE_PATTERN.match(unit_code):
            invalid_unit_codes.append(unit_code)
            continue
        if unit_code not in selected_unit_codes:
            selected_unit_codes.append(unit_code)

    if invalid_unit_codes:
        flash("Unit filters must use format AAAA1234.", "error")

    degree_options = get_degree_options_by_category()
    requester = current_user

    match_results = find_matches(requester.id, selected_degree_option_id, selected_unit_codes)

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
        selected_unit_codes=selected_unit_codes,
        message=message,
    )


@main_bp.route("/people")
@login_required
def people():
    query = request.args.get("q", "").strip()
    active_tab = request.args.get("tab", "discover")
    if active_tab not in {"discover", "friends"}:
        active_tab = "discover"

    search_results = []
    if len(query) >= 2:
        matches = (
            User.query
            .filter(User.id != current_user.id)
            .filter(User.username.ilike(f"{query}%"))
            .order_by(User.username.asc())
            .limit(20)
            .all()
        )

        candidate_ids = [user.id for user in matches]
        relationship_rows = []
        if candidate_ids:
            relationship_rows = FriendRequest.query.filter(
                or_(
                    (FriendRequest.user_low_id == current_user.id) & FriendRequest.user_high_id.in_(candidate_ids),
                    (FriendRequest.user_high_id == current_user.id) & FriendRequest.user_low_id.in_(candidate_ids),
                )
            ).all()

        relationship_map = {}
        for relation in relationship_rows:
            other_user_id = relation.user_high_id if relation.user_low_id == current_user.id else relation.user_low_id
            relationship_map[other_user_id] = relation

        for user in matches:
            relation = relationship_map.get(user.id)
            relation_state = "none"

            if relation is not None:
                if relation.status == "pending":
                    if relation.requested_by_id == current_user.id:
                        relation_state = "outgoing_pending"
                    else:
                        relation_state = "incoming_pending"
                elif relation.status == "accepted":
                    relation_state = "accepted"

            search_results.append({
                "user": user,
                "state": relation_state,
                "friend_request_id": relation.id if relation else None,
            })

    incoming_requests = (
        FriendRequest.query.filter(FriendRequest.status == "pending")
        .filter(FriendRequest.requested_by_id != current_user.id)
        .filter(
            or_(
                FriendRequest.user_low_id == current_user.id,
                FriendRequest.user_high_id == current_user.id,
            )
        )
        .order_by(FriendRequest.created_at.desc())
        .limit(50)
        .all()
    )

    outgoing_requests = (
        FriendRequest.query.filter_by(status="pending", requested_by_id=current_user.id)
        .order_by(FriendRequest.created_at.desc())
        .limit(50)
        .all()
    )

    accepted_relationships = (
        FriendRequest.query.filter_by(status="accepted")
        .filter(
            or_(
                FriendRequest.user_low_id == current_user.id,
                FriendRequest.user_high_id == current_user.id,
            )
        )
        .order_by(FriendRequest.updated_at.desc())
        .limit(50)
        .all()
    )

    def other_user(friend_request):
        other_id = friend_request.user_high_id if friend_request.user_low_id == current_user.id else friend_request.user_low_id
        return db.session.get(User, other_id)

    incoming_payload = [{"request": item, "user": other_user(item)} for item in incoming_requests]
    outgoing_payload = [{"request": item, "user": other_user(item)} for item in outgoing_requests]
    accepted_payload = [{"request": item, "user": other_user(item)} for item in accepted_relationships]

    return render_template(
        "people.html",
        current_user=current_user,
        query=query,
        active_tab=active_tab,
        search_results=search_results,
        incoming_requests=incoming_payload,
        outgoing_requests=outgoing_payload,
        friends=accepted_payload,
    )


@main_bp.route("/friends/request/<int:user_id>", methods=["POST"])
@login_required
def send_friend_request(user_id):
    if user_id == current_user.id:
        flash("You cannot send a friend request to yourself.", "error")
        return redirect(url_for("main.people", tab="discover"))

    target_user = db.session.get(User, user_id)
    if target_user is None:
        flash("User not found.", "error")
        return redirect(url_for("main.people", tab="discover"))

    existing = get_friend_request_between(current_user.id, user_id)
    if existing is None:
        low_id, high_id = get_friend_pair_ids(current_user.id, user_id)
        friend_request = FriendRequest(
            user_low_id=low_id,
            user_high_id=high_id,
            requested_by_id=current_user.id,
            status="pending",
        )
        db.session.add(friend_request)
        db.session.flush()
        db.session.add(
            Notification(
                user_id=target_user.id,
                sender_name=current_user.username,
                type="friend_request",
                message=f"<strong>{current_user.username}</strong> sent you a friend request.",
                channel=f"friend_request:{friend_request.id}",
            )
        )
        db.session.commit()
        flash("Friend request sent.", "success")
        return redirect(url_for("main.people", tab="discover"))

    if existing.status == "pending":
        flash("A friend request is already pending.", "info")
        return redirect(url_for("main.people", tab="discover"))

    if existing.status == "accepted":
        flash("You are already friends.", "info")
        return redirect(url_for("main.people", tab="discover"))

    existing.requested_by_id = current_user.id
    existing.status = "pending"
    db.session.add(
        Notification(
            user_id=target_user.id,
            sender_name=current_user.username,
            type="friend_request",
            message=f"<strong>{current_user.username}</strong> sent you a friend request.",
            channel=f"friend_request:{existing.id}",
        )
    )
    db.session.commit()
    flash("Friend request sent.", "success")
    return redirect(url_for("main.people", tab="discover"))


@main_bp.route("/friends/<int:friend_request_id>/accept", methods=["POST"])
@login_required
def accept_friend_request(friend_request_id):
    friend_request = FriendRequest.query.get_or_404(friend_request_id)

    if friend_request.status != "pending":
        flash("This friend request is no longer pending.", "info")
        return redirect(url_for("main.people", tab="friends"))

    if friend_request.requested_by_id == current_user.id:
        abort(403)

    if current_user.id not in {friend_request.user_low_id, friend_request.user_high_id}:
        abort(403)

    friend_request.status = "accepted"
    db.session.commit()
    flash("Friend request accepted.", "success")
    return redirect(url_for("main.people", tab="friends"))


@main_bp.route("/friends/<int:friend_request_id>/reject", methods=["POST"])
@login_required
def reject_friend_request(friend_request_id):
    friend_request = FriendRequest.query.get_or_404(friend_request_id)

    if friend_request.status != "pending":
        flash("This friend request is no longer pending.", "info")
        return redirect(url_for("main.people", tab="friends"))

    if friend_request.requested_by_id == current_user.id:
        abort(403)

    if current_user.id not in {friend_request.user_low_id, friend_request.user_high_id}:
        abort(403)

    friend_request.status = "rejected"
    db.session.commit()
    flash("Friend request rejected.", "info")
    return redirect(url_for("main.people", tab="friends"))


@main_bp.route("/friends/<int:friend_request_id>/cancel", methods=["POST"])
@login_required
def cancel_friend_request(friend_request_id):
    friend_request = FriendRequest.query.get_or_404(friend_request_id)

    if friend_request.status != "pending":
        flash("This friend request is no longer pending.", "info")
        return redirect(url_for("main.people", tab="friends"))

    if friend_request.requested_by_id != current_user.id:
        abort(403)

    if current_user.id not in {friend_request.user_low_id, friend_request.user_high_id}:
        abort(403)

    friend_request.status = "cancelled"
    db.session.commit()
    flash("Friend request cancelled.", "info")
    return redirect(url_for("main.people", tab="friends"))


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

    matches = [
        code for code in VALID_UWA_2026_UNIT_CODES
        if code.startswith(query)
    ]
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


@main_bp.route("/register", methods=["GET", "POST"])
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
        second_major = request.form.get("second_major", "").strip()
        minor = request.form.get("minor", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not first_name or not last_name or not email or not username or not major:
            flash("All required fields must be filled.", "error")
            return render_template("signup.html", degree_options=degree_options)

        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            flash("Invalid email address", "error")
            return render_template("signup.html", degree_options=degree_options)

        if not password or password != confirm_password:
            flash("Password and confirm password must match.", "error")
            return render_template("signup.html", degree_options=degree_options)

        selected_degree_option = None

        if degree_type != "other" and degree_option_id:
            selected_degree_option = DegreeOption.query.filter_by(
                id=degree_option_id,
                is_active=True
            ).first()

            if selected_degree_option is None:
                flash("Selected degree is invalid.", "error")
                return render_template("signup.html", degree_options=degree_options)

        if selected_degree_option is None and not degree:
            flash("Degree is required.", "error")
            return render_template("signup.html", degree_options=degree_options)

        if User.query.filter_by(email=email).first():
            flash("Email already exists.", "error")
            return render_template("signup.html", degree_options=degree_options)

        if User.query.filter_by(username=username).first():
            flash("Username is already taken.", "error")
            return render_template("signup.html", degree_options=degree_options)

        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            username=username,
            degree=selected_degree_option.name if selected_degree_option else degree,
            degree_option_id=selected_degree_option.id if selected_degree_option else None,
            major=major,
            onboarding_step=1,
            second_major=second_major or None,
            minor=minor or None,
        )

        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        flash("Registration successful. Let's finish setup.", "success")
        return redirect(url_for("main.onboarding"))
        
    return render_template("signup.html", degree_options=degree_options)


@main_bp.route("/notifications")
@login_required
def notifications():
    user = current_user
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    pending_invites = Invitation.query.filter_by(receiver_id=current_user.id, status="pending").all()
    pending_invite_map = {invite.sender.username: invite.id for invite in pending_invites}
    incoming_friend_requests = (
        FriendRequest.query.filter_by(status="pending")
        .filter(FriendRequest.requested_by_id != current_user.id)
        .filter(
            or_(
                FriendRequest.user_low_id == current_user.id,
                FriendRequest.user_high_id == current_user.id,
            )
        )
        .all()
    )
    pending_friend_request_ids = {friend_request.id for friend_request in incoming_friend_requests}
    return render_template(
        "notifications.html",
        current_user=user,
        notifications=notifs,
        pending_invites=pending_invites,
        pending_invite_map=pending_invite_map,
        pending_friend_request_ids=pending_friend_request_ids,
        unread_count=sum(1 for n in notifs if not n.is_read),
        dm_count=sum(1 for n in notifs if n.type == "dm" and not n.is_read),
        friend_request_count=sum(1 for n in notifs if n.type == "friend_request" and not n.is_read),
    )


@main_bp.route("/notifications/read/<int:notif_id>", methods=["POST"])
@login_required
def mark_read(notif_id):
    n = Notification.query.get_or_404(notif_id)
    if n.user_id != current_user.id:
        abort(403)
    n.is_read = True
    db.session.commit()
    return "", 204


@main_bp.route("/notifications/read/all", methods=["POST"])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return "", 204

@main_bp.route("/matches/ignore/<int:user_id>", methods=["POST"])
@login_required
def ignore_match(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return "", 404
    db.session.add(Notification(
        user_id=current_user.id,
        sender_name=user.username,
        type="match",
        message=f"You passed on matching with <strong>{user.username}</strong>.",
        channel="Matches",
        is_read=True,
    ))
    db.session.commit()
    return "", 204


@main_bp.route("/invitations/send<int:receiver_id>", methods=["POST"])
@login_required
def send_invitation(receiver_id):
    receiver = db.session.get(User, receiver_id)
    if receiver is None:
        return "User not found", 404

    if receiver.id == current_user.id:
        return "You are unable to invite yourself.", 400

    existing = Invitation.query.filter_by(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        status="pending",
    ).first()

    if existing:
        flash("Invitation already sent.", "info")
        return redirect(request.referrer or url_for("main.matches"))

    message_text = request.form.get("message", "").strip()

    invite = Invitation(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        message=message_text or None,
    )

    db.session.add(invite)

    notif = Notification(
        user_id=receiver_id,
        sender_name=current_user.username,
        type="dm",
        message=f"<strong>{current_user.username}</strong> wants to message you.",
        channel="Invitations",
    )

    db.session.add(notif)
    db.session.commit()

    flash("Invitation sent!", "success")
    return redirect(request.referrer or url_for("main.matches"))

@main_bp.route("/invitations/<int:invite_id>/accept", methods=["POST"])
@login_required
def accept_invitation(invite_id):
    invite = Invitation.query.get_or_404(invite_id)

    if invite.receiver_id != current_user.id:
        abort(403)

    if invite.status != "pending":
        flash("This invitation has already been responded to.", "info")
        return redirect(url_for("main.notifications"))

    invite.status = "accepted"
    invite.responded_at = datetime.utcnow()

    existing_conversations = (
        Conversation.query
        .join(ConversationMember)
        .filter(
            Conversation.is_group_chat.is_(False),
            ConversationMember.user_id == current_user.id
        )
        .all()
    )

    conversation = None
    for conv in existing_conversations:
        member_ids = {member.user_id for member in conv.members}
        if member_ids == {current_user.id, invite.sender_id}:
            conversation = conv
            break

    if conversation is None:
        conversation = Conversation(is_group_chat=False)
        db.session.add(conversation)
        db.session.flush()
        db.session.add(ConversationMember(conversation_id=conversation.id, user_id=current_user.id))
        db.session.add(ConversationMember(conversation_id=conversation.id, user_id=invite.sender_id))

    notif = Notification(
        user_id=invite.sender_id,
        sender_name=current_user.username,
        type="match",
        message=f"<strong>{current_user.username}</strong> accepted your study invite!",
        channel=f"Conversation {conversation.id}",
    )

    db.session.add(notif)
    db.session.commit()

    flash("Invitation accepted!", "success")
    return redirect(url_for("main.messages", conversation_id=conversation.id))

@main_bp.route("/invitations/<int:invite_id>/reject", methods=["POST"])
@login_required
def reject_invitation(invite_id):
    invite = Invitation.query.get_or_404(invite_id)

    if invite.receiver_id != current_user.id:
        abort(403)

    if invite.status != "pending":
        flash("This invitation has already been responded to.", "info")
        return redirect(url_for("main.notifications"))

    invite.status = "rejected"
    invite.responded_at = datetime.utcnow()

    Notification.query.filter_by(
        user_id=current_user.id,
        sender_name=invite.sender.username,
        channel="Invitations",
        type="dm",
        is_read=False,
    ).update({"is_read": True})

    db.session.commit()

    flash("Invitation declined.", "info")
    return redirect(url_for("main.notifications"))




@main_bp.route("/messages/<int:conversation_id>")
@login_required
def messages(conversation_id):
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

    #Mark messages as read when opening
    already_read_ids = {
        mr.message_id
        for mr in MessageRead.query.filter_by(user_id=current_user.id).all()
    }

    for msg in message_history:
        if msg.id not in already_read_ids and msg.sender_id != current_user.id:
            db.session.add(MessageRead(message_id=msg.id, user_id=current_user.id))
    db.session.commit()

    return render_template(
        "messages.html",
        current_user=current_user,
        conversation=conversation,
        messages=message_history,
    )


@main_bp.route("/messages")
@login_required
def messages_inbox():
    memberships = (
        ConversationMember.query.filter_by(user_id=current_user.id)
        .join(Conversation)
        .order_by(Conversation.created_at.desc())
        .all()
    )

    conversations = []
    for membership in memberships:
        conversation = membership.conversation
        other_members = [member.user for member in conversation.members if member.user_id != current_user.id]
        latest_message = (
            Message.query.filter_by(conversation_id=conversation.id)
            .order_by(Message.created_at.desc())
            .first()
        )

        if conversation.title:
            display_name = conversation.title
        elif other_members:
            display_name = ", ".join(member.username for member in other_members)
        else:
            display_name = "Direct Message"

        read_ids = {
            mr.message_id
            for mr in MessageRead.query.filter_by(user_id=current_user.id).all()
        }
        unread_count = Message.query.filter(
            Message.conversation_id == conversation.id,
            Message.sender_id != current_user.id,
            Message.id.notin_(read_ids),
            Message.is_deleted.is_(False),
        ).count()
        
        conversations.append(
            {
                "conversation": conversation,
                "display_name": display_name,
                "latest_message": latest_message,
                "unread_count": unread_count,
            }
        )

    return render_template(
        "messages_inbox.html",
        current_user=current_user,
        conversations=conversations,
    )


@main_bp.route("/messages/start/<int:receiver_id>", methods=["POST"])
@login_required
def start_conversation(receiver_id):
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
            return redirect(url_for("main.messages", conversation_id=conversation.id))

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

    db.session.add(Notification(
        user_id=receiver.id,
        sender_name=current_user.username,
        type="match",
        message=f"<strong>{current_user.username}</strong> accepted your match and wants to study with you!",
        channel=f"Conversation {conversation.id}",
    ))

    db.session.commit()

    return redirect(url_for("main.messages", conversation_id=conversation.id))

@main_bp.route("/messages/delete/<int:message_id>", methods=["POST"])
@login_required
def delete_message(message_id):
    message = Message.query.get_or_404(message_id)

    if message.sender_id != current_user.id:
        abort(403)

    message.is_deleted = True
    db.session.commit()

    socketio.emit(
        "message_deleted",
        {"message_id": message_id},
        room=f"conversation-{message.conversation_id}",
    )

    return "", 204

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
    db.session.flush()

    db.session.add(MessageRead(message_id=message.id, user_id=current_user.id))

    notify_mentions(message, conversation_id)

    db.session.commit()

    # Create DM notification for other users in conversation
    conversation = db.session.get(Conversation, conversation_id)
    for member in conversation.members:
        if member.user_id != current_user.id:
            notif = Notification(
                user_id=member.user_id,
                sender_name=current_user.username,
                type="dm",
                message=f"<strong>{current_user.username}</strong>: {body[:80]}",
                channel=f"Conversation {conversation_id}",
            )
            db.session.add(notif)

    db.session.commit()
@main_bp.route("/check_register_details")
def check_register_details():
    email = request.args.get("email", "").strip()
    username = request.args.get("username", "").strip()

    email_exists = False
    username_exists = False

    if email:
        email_exists = User.query.filter_by(email=email).first() is not None

    if username:
        username_exists = User.query.filter_by(username=username).first() is not None

    return {
        "email_exists": email_exists,
        "username_exists": username_exists
    }
    
    
