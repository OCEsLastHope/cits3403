from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .. import db
from ..blueprints import main_bp
from ..database import Event, EventAttendee, Notification, User
from .common import (
    EVENT_VISIBILITY_MODES,
    build_event_card_data,
    count_event_accepted_attendees,
    find_event_overlap_for_user,
    is_event_full,
    parse_event_datetime,
)


# Show upcoming, invited, open, and past event buckets.
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


# Create a new study event from form input.
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


# Edit a scheduled event owned by the current user.
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


# Cancel an event and notify affected attendees.
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


# Invite users to an existing event by username/email list.
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


# Join an open event when capacity allows.
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
        db.session.add(
            Notification(
                user_id=event.creator_user_id,
                sender_name=current_user.username,
                type="event",
                message=f"<strong>{current_user.username}</strong> joined your event: <strong>{event.title}</strong>.",
                channel="Events",
            )
        )

    db.session.commit()
    flash("You joined the event.", "success")
    return redirect(url_for("main.events_page"))


# Accept or decline an event invitation.
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


# Leave an event as a non-creator attendee.
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
