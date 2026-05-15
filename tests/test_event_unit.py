import unittest
import os
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")

from app import app, db
from app.database import User, Event, EventAttendee
from config import TestConfig

class EventUnitTests(unittest.TestCase):

    def setUp(self):
        app.config.from_object(TestConfig)
        self.client = app.test_client()

        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
            
            # Create three users
            self.user1 = self.create_user("user1", "user1@test.com")
            self.user2 = self.create_user("user2", "user2@test.com")
            self.user3 = self.create_user("user3", "user3@test.com")
            
            # Create an open event with max 2 attendees
            self.event = Event(
                creator_user_id=self.user1.id,
                title="Test Event",
                visibility_mode="open",
                max_attendees=2,
                start_at=datetime.utcnow() + timedelta(hours=1),
                end_at=datetime.utcnow() + timedelta(hours=2),
                status="scheduled"
            )
            db.session.add(self.event)
            db.session.commit()
            
            # Add creator as accepted attendee
            db.session.add(EventAttendee(
                event_id=self.event.id,
                user_id=self.user1.id,
                invite_status="accepted"
            ))
            db.session.commit()
            self.event_id = self.event.id

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def create_user(self, username, email):
        user = User(
            first_name=username,
            last_name="Test",
            email=email,
            username=username,
            degree="Engineering",
            major="Software",
            onboarding_completed=True
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        return user

    def login(self, username):
        return self.client.post(
            "/login",
            data={"username": username, "password": "password123"},
            follow_redirects=True
        )

    def test_capacity_enforcement(self):
        # 1. User2 joins the event (making it full: User1 + User2 = 2)
        self.login("user2")
        response = self.client.post(f"/events/{self.event_id}/join", follow_redirects=True)
        self.assertIn(b"You joined the event", response.data)
        
        with app.app_context():
            count = EventAttendee.query.filter_by(event_id=self.event_id, invite_status="accepted").count()
            self.assertEqual(count, 2)
        
        # 2. User3 attempts to join the full event
        self.login("user3")
        response = self.client.post(f"/events/{self.event_id}/join", follow_redirects=True)
        self.assertIn(b"Event is full", response.data)
        
        with app.app_context():
            # Verify count is still 2
            count = EventAttendee.query.filter_by(event_id=self.event_id, invite_status="accepted").count()
            self.assertEqual(count, 2)
            
            # Verify user3 is not an accepted attendee
            user3_attendee = EventAttendee.query.filter_by(event_id=self.event_id, user_id=self.user3.id).first()
            if user3_attendee:
                self.assertNotEqual(user3_attendee.invite_status, "accepted")

if __name__ == "__main__":
    unittest.main()
