import re
from datetime import datetime
from collections import defaultdict
from pathlib import Path

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, or_
from flask_socketio import emit, join_room
from email_validator import validate_email, EmailNotValidError

from . import app, db, socketio, mail
from flask_mail import Message as MailMessage
from itsdangerous import URLSafeTimedSerializer
from .database import (
    Conversation,
    ConversationMember,
    DegreeOption,
    Event,
    EventAttendee,
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
MAX_PROFILE_UNITS = 4
UNIT_CODE_PATTERN = re.compile(r"^[A-Z]{4}[0-9]{4}$")


def load_valid_uwa_2026_unit_codes():
    data_path = Path(app.root_path).parent / "data" / "uwa_2026_unit_codes.txt"
    if not data_path.exists():
        return set()
    return {
        line.strip().upper()
        for line in data_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


VALID_UWA_2026_UNIT_CODES = load_valid_uwa_2026_unit_codes()
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])


def generate_reset_token(email):
    return serializer.dumps(email, salt="password-reset-salt")


def verify_reset_token(token, expiration=1800):
    try:
        email = serializer.loads(
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
        "reset_password",
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

    requester_secondary_fields = {
        requester_second_major,
        requester_minor,
    } - {""}

    candidate_secondary_fields = {
        candidate_second_major,
        candidate_minor,
    } - {""}

    if requester_major and requester_major == candidate_major:
        score += 70
        matched_fields.append("Same major")

    if requester_second_major and requester_second_major == candidate_second_major:
        score += 45
        matched_fields.append("Same second major")

    if requester_minor and requester_minor == candidate_minor:
        score += 25
        matched_fields.append("Same minor")

    if requester_major and requester_major in candidate_secondary_fields:
        score += 45
        matched_fields.append("Your major matches their second major/minor")

    if candidate_major and candidate_major in requester_secondary_fields:
        score += 45
        matched_fields.append("Their major matches your second major/minor")

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

    if valid_overlap_days == 0:
        return None

    availability_score = (
        valid_overlap_days * 30
        + useful_overlap_days * 45
        + strong_overlap_days * 60
        + (overlap_minutes_total / 60) * 40
        + (strongest_single_day_overlap / 60) * 20
    )

    return {
        "availability_score": availability_score,
        "valid_overlap_days": valid_overlap_days,
        "useful_overlap_days": useful_overlap_days,
        "strong_overlap_days": strong_overlap_days,
        "overlap_minutes_total": overlap_minutes_total,
        "strongest_single_day_overlap": strongest_single_day_overlap,
    }


def normalise_text(value):
    if not value:
        return ""
    return value.strip().lower()


def get_shared_unit_score(shared_unit_count):
    # Strong academic weighting without becoming overwhelming.
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

    requester_secondary_fields = {
        requester_second_major,
        requester_minor,
    } - {""}

    candidate_secondary_fields = {
        candidate_second_major,
        candidate_minor,
    } - {""}

    # Same primary major
    if requester_major and requester_major == candidate_major:
        score += 70
        matched_fields.append("Same major")

    # Same second major
    if (
        requester_second_major
        and requester_second_major == candidate_second_major
    ):
        score += 45
        matched_fields.append("Same second major")

    # Same minor
    if requester_minor and requester_minor == candidate_minor:
        score += 25
        matched_fields.append("Same minor")

    # Cross-field matches
    if (
        requester_major
        and requester_major in candidate_secondary_fields
    ):
        score += 45
        matched_fields.append(
            "Your major matches their second major/minor"
        )

    if (
        candidate_major
        and candidate_major in requester_secondary_fields
    ):
        score += 45
        matched_fields.append(
            "Their major matches your second major/minor"
        )

    # Same degree
    same_degree = (
        requester.degree_option_id is not None
        and candidate.degree_option_id == requester.degree_option_id
    ) or (
        requester.degree
        and candidate.degree
        and requester.degree.strip().lower()
        == candidate.degree.strip().lower()
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


def find_matches(user_id, selected_degree_option_id=None):
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


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

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
        return redirect(url_for("dashboard"))

    return render_template("loginpage.html")


@app.route("/forgot_password", methods=["GET", "POST"])
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

        return redirect(url_for("login"))

    return render_template("forgot_password.html")

@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):

    email = verify_reset_token(token)

    if not email:
        flash("Invalid or expired reset link.", "error")
        return redirect(url_for("forgot_password"))

    user = User.query.filter_by(email=email).first()

    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":

        password = request.form.get("password", "").strip()

        confirm_password = request.form.get("confirm_password", "").strip()

        if not password or password != confirm_password:
            flash("Passwords must match.", "error")
            return redirect(request.url)

        user.set_password(password)

        db.session.commit()

        flash("Password reset successful. Please log in.", "success")

        return redirect(url_for("login"))

    return render_template("reset_password.html")




@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    if not user:
        # Fallback for demo if no session is active
        user = db.session.get(User, 1)

    suggested_matches = []
    upcoming_events = []
    
    if user:
        # Get the top 3 matches for the dashboard preview
        suggested_matches = find_matches(user.id)[:3]
        
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

    return render_template(
        "dashboard.html",
        current_user=user,
        suggested_matches=suggested_matches,
        upcoming_events=upcoming_events
    )


@app.route("/events")
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


@app.route("/events/create", methods=["POST"])
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
        return redirect(url_for("events_page"))

    if visibility_mode not in EVENT_VISIBILITY_MODES:
        flash("Invalid event type.", "error")
        return redirect(url_for("events_page"))

    if start_at is None or end_at is None:
        flash("Valid start and end times are required.", "error")
        return redirect(url_for("events_page"))

    if end_at <= start_at:
        flash("Event end time must be after start time.", "error")
        return redirect(url_for("events_page"))

    if (end_at - start_at).total_seconds() > 12 * 3600:
        flash("Event duration cannot exceed 12 hours.", "error")
        return redirect(url_for("events_page"))

    max_attendees = None
    if max_attendees_raw:
        if not max_attendees_raw.isdigit():
            flash("Max attendees must be a number.", "error")
            return redirect(url_for("events_page"))
        max_attendees = int(max_attendees_raw)
        if max_attendees < 2 or max_attendees > 100:
            flash("Max attendees must be between 2 and 100.", "error")
            return redirect(url_for("events_page"))

    if visibility_mode == "open" and max_attendees is None:
        flash("Open events must include a max attendee limit.", "error")
        return redirect(url_for("events_page"))

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
    return redirect(url_for("events_page"))


@app.route("/events/<int:event_id>/edit", methods=["POST"])
@login_required
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.creator_user_id != current_user.id:
        abort(403)
    if event.status != "scheduled":
        flash("Only scheduled events can be edited.", "error")
        return redirect(url_for("events_page"))

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    location_or_link = request.form.get("location_or_link", "").strip()
    visibility_mode = request.form.get("visibility_mode", "invite_only").strip()
    max_attendees_raw = request.form.get("max_attendees", "").strip()
    start_at = parse_event_datetime(request.form.get("start_at"))
    end_at = parse_event_datetime(request.form.get("end_at"))

    if not title or len(title) < 3 or len(title) > 120:
        flash("Event title must be between 3 and 120 characters.", "error")
        return redirect(url_for("events_page"))
    if visibility_mode not in EVENT_VISIBILITY_MODES:
        flash("Invalid event type.", "error")
        return redirect(url_for("events_page"))
    if start_at is None or end_at is None:
        flash("Valid start and end times are required.", "error")
        return redirect(url_for("events_page"))
    if end_at <= start_at:
        flash("Event end time must be after start time.", "error")
        return redirect(url_for("events_page"))

    max_attendees = None
    if max_attendees_raw:
        if not max_attendees_raw.isdigit():
            flash("Max attendees must be a number.", "error")
            return redirect(url_for("events_page"))
        max_attendees = int(max_attendees_raw)
        if max_attendees < 2 or max_attendees > 100:
            flash("Max attendees must be between 2 and 100.", "error")
            return redirect(url_for("events_page"))

    if visibility_mode == "open" and max_attendees is None:
        flash("Open events must include a max attendee limit.", "error")
        return redirect(url_for("events_page"))

    accepted_count = count_event_accepted_attendees(event)
    if max_attendees is not None and accepted_count > max_attendees:
        flash("Max attendees cannot be below current accepted attendee count.", "error")
        return redirect(url_for("events_page"))

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
                type="mention",
                message=f"Event updated: <strong>{event.title}</strong> now starts at {event.start_at.strftime('%Y-%m-%d %H:%M')}.",
                channel="Events",
            )
        )

    db.session.commit()
    flash("Event updated.", "success")
    return redirect(url_for("events_page"))


@app.route("/events/<int:event_id>/cancel", methods=["POST"])
@login_required
def cancel_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.creator_user_id != current_user.id:
        abort(403)
    if event.status != "scheduled":
        flash("Event is already cancelled.", "info")
        return redirect(url_for("events_page"))

    event.status = "cancelled"

    for attendee in event.attendees:
        if attendee.user_id == current_user.id or attendee.invite_status == "declined":
            continue
        db.session.add(
            Notification(
                user_id=attendee.user_id,
                sender_name=current_user.username,
                type="mention",
                message=f"Event cancelled: <strong>{event.title}</strong>.",
                channel="Events",
            )
        )

    db.session.commit()
    flash("Event cancelled.", "success")
    return redirect(url_for("events_page"))


@app.route("/events/<int:event_id>/invite", methods=["POST"])
@login_required
def invite_to_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.creator_user_id != current_user.id:
        abort(403)
    if event.status != "scheduled":
        flash("Cannot invite attendees to a cancelled event.", "error")
        return redirect(url_for("events_page"))

    identifiers = request.form.get("invite_identifiers", "")
    raw_items = [item.strip() for item in identifiers.split(",") if item.strip()]
    if not raw_items:
        flash("Enter at least one username or email to invite.", "error")
        return redirect(url_for("events_page"))

    if len(raw_items) > 20:
        flash("You can invite up to 20 users per event at a time.", "error")
        return redirect(url_for("events_page"))

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
                type="mention",
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
    return redirect(url_for("events_page"))


@app.route("/events/<int:event_id>/join", methods=["POST"])
@login_required
def join_open_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.status != "scheduled" or event.visibility_mode != "open":
        flash("This event is not open for joining.", "error")
        return redirect(url_for("events_page"))

    attendee = EventAttendee.query.filter_by(event_id=event.id, user_id=current_user.id).first()
    if attendee and attendee.invite_status == "accepted":
        flash("You already joined this event.", "info")
        return redirect(url_for("events_page"))

    if is_event_full(event):
        flash("Event is full.", "error")
        return redirect(url_for("events_page"))

    if attendee is None:
        attendee = EventAttendee(event_id=event.id, user_id=current_user.id)
        db.session.add(attendee)

    attendee.invite_status = "accepted"
    attendee.responded_at = datetime.utcnow()
    db.session.commit()
    flash("You joined the event.", "success")
    return redirect(url_for("events_page"))


@app.route("/events/<int:event_id>/respond", methods=["POST"])
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
        return redirect(url_for("events_page"))

    if event.status != "scheduled":
        flash("This event is no longer active.", "error")
        return redirect(url_for("events_page"))

    if action == "decline":
        attendee.invite_status = "declined"
        attendee.responded_at = datetime.utcnow()
        db.session.commit()
        flash("Invitation declined.", "info")
        return redirect(url_for("events_page"))

    overlap = find_event_overlap_for_user(current_user.id, event.start_at, event.end_at, exclude_event_id=event.id)
    if overlap is not None and not confirm_conflict:
        flash(
            f"Schedule conflict with '{overlap.title}'. Click accept again to confirm.",
            "error",
        )
        return redirect(url_for("events_page"))

    if is_event_full(event) and attendee.invite_status != "accepted":
        flash("Event is full.", "error")
        return redirect(url_for("events_page"))

    attendee.invite_status = "accepted"
    attendee.responded_at = datetime.utcnow()
    db.session.commit()
    flash("Invitation accepted.", "success")
    return redirect(url_for("events_page"))


@app.route("/events/<int:event_id>/leave", methods=["POST"])
@login_required
def leave_event(event_id):
    event = Event.query.get_or_404(event_id)
    attendee = EventAttendee.query.filter_by(event_id=event.id, user_id=current_user.id).first()
    if attendee is None:
        abort(403)
    if event.creator_user_id == current_user.id:
        flash("Event creators cannot leave their own event. Cancel it instead.", "error")
        return redirect(url_for("events_page"))

    attendee.invite_status = "left"
    attendee.responded_at = datetime.utcnow()
    db.session.commit()
    flash("You left the event.", "info")
    return redirect(url_for("events_page"))


@app.route("/matches")
@login_required
def matches():
    selected_degree_option_id = request.args.get("degree_option_id", type=int)
    degree_options = get_degree_options_by_category()
    requester = current_user

    match_results = find_matches(requester.id, selected_degree_option_id)

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


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    degree_options = get_degree_options_by_category()
    user = current_user

    if request.method == "POST":
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

        unit_values = [
            request.form.get("unit1", "").strip().upper(),
            request.form.get("unit2", "").strip().upper(),
            request.form.get("unit3", "").strip().upper(),
            request.form.get("unit4", "").strip().upper(),
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

        non_empty_units = [value for value in unit_values if value]
        if len(non_empty_units) > MAX_PROFILE_UNITS:
            profile_errors.append("You can add a maximum of 4 units.")

        if len(non_empty_units) != len(set(non_empty_units)):
            profile_errors.append("Units must be unique.")

        for value in non_empty_units:
            if not UNIT_CODE_PATTERN.match(value):
                profile_errors.append(f"{value} is invalid. Use 4 letters followed by 4 numbers.")
                continue
            if VALID_UWA_2026_UNIT_CODES and value not in VALID_UWA_2026_UNIT_CODES:
                profile_errors.append(f"{value} is not a valid UWA 2026 unit code.")

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
                units=non_empty_units,
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
        for value in non_empty_units:
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
        return redirect(url_for("profile"))

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


@app.route("/units/search")
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
            second_major=second_major or None,
            minor=minor or None,
        )

        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html", degree_options=degree_options)


@app.route("/notifications")
@login_required
def notifications():
    user = current_user
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    pending_invites = Invitation.query.filter_by(receiver_id=current_user.id, status="pending").all()
    return render_template(
        "notifications.html",
        current_user=user,
        notifications=notifs,
        pending_invites=pending_invites,
        unread_count=sum(1 for n in notifs if not n.is_read),
        dm_count=sum(1 for n in notifs if n.type == "dm" and not n.is_read),
        mention_count=sum(1 for n in notifs if n.type == "mention" and not n.is_read),
    )


@app.route("/notifications/read/<int:notif_id>", methods=["POST"])
@login_required
def mark_read(notif_id):
    n = Notification.query.get_or_404(notif_id)
    if n.user_id != current_user.id:
        abort(403)
    n.is_read = True
    db.session.commit()
    return "", 204


@app.route("/notifications/read/all", methods=["POST"])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return "", 204

@app.route("/invitations/send<int:receiver_id>", methods=["POST"])
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
        return redirect(request.referrer or url_for("matches"))

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
        type="mention",
        message=f"<strong>{current_user.username}</strong> sent you a study invite.",
        channel="Invitations",
    )

    db.session.add(notif)
    db.session.commit()

    flash("Invitation sent!", "success")
    return redirect(request.referrer or url_for("matches"))

@app.route("/invitations/<int:invite_id>/accept", methods=["POST"])
@login_required
def accept_invitation(invite_id):
    invite = Invitation.query.get_or_404(invite_id)

    if invite.receiver_id != current_user.id:
        abort(403)

    if invite.status != "pending":
        flash("This invitation has already been responded to.", "info")
        return redirect(url_for("notifications"))

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
        sender_name= current_user.username,
        type="dm",
        message=f"<strong>{current_user.username}</strong> accepted your study invite!",
        channel="Invitations",
    )

    db.session.add(notif)
    db.session.commit()

    flash("Invitation accepted!", "success")
    return redirect(url_for("messages", conversation_id=conversation.id))

@app.route("/invitations/<int:invite_id>/reject", methods=["POST"])
@login_required
def reject_invitation(invite_id):
    invite = Invitation.query.get_or_404(invite_id)

    if invite.receiver_id != current_user.id:
        abort(403)

    if invite.status != "pending":
        flash("This invitation has already been responded to.", "info")
        return redirect(url_for("notifications"))

    invite.status = "rejected"
    invite.responded_at = datetime.utcnow()
    db.session.commit()

    flash("Invitation rejected.", "info")
    return redirect(url_for("notifications"))




@app.route("/messages/<int:conversation_id>")
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


@app.route("/messages")
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


@app.route("/messages/start/<int:receiver_id>", methods=["POST"])
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

@app.route("/messages/delete/<int:message_id>", methods=["POST"])
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
@app.route("/check_register_details")
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
    
    
