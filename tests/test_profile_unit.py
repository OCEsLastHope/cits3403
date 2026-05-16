import unittest
import os
import re

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")

from app import app, db
from app.database import User, UserSubject, UserAvailability
from config import TestConfig

class ProfileUnitTests(unittest.TestCase):

    def setUp(self):
        app.config.from_object(TestConfig)
        self.client = app.test_client()

        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
            
            # Create a test user for profile updates
            self.user = User(
                first_name="Profile",
                last_name="Test",
                email="profile@test.com",
                username="profileuser",
                degree="Bachelor of Science",
                major="Data Science",
                onboarding_completed=True
            )
            self.user.set_password("password123")
            db.session.add(self.user)
            db.session.commit()
            self.user_id = self.user.id

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self):
        return self.client.post(
            "/login",
            data={"username": "profileuser", "password": "password123"},
            follow_redirects=True
        )

    def test_valid_profile_update(self):
        self.login()

        response = self.client.post(
            "/profile",
            data={
                "form_type": "profile",
                "email": "updated@test.com",
                "degree": "Master of Data Science",
                "major": "Machine Learning",
                "bio": "Updated bio text",
                "sessions_per_week": "3",
            },
            follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)

        self.client.post(
            "/profile",
            data={
                "form_type": "subjects",
                "unit1": "CITS1401",
            },
            follow_redirects=True,
        )

        self.client.post(
            "/profile",
            data={
                "form_type": "availability",
                "monday_start": "09:00",
                "monday_end": "11:00",
            },
            follow_redirects=True,
        )

        with app.app_context():
            user = db.session.get(User, self.user_id)
            self.assertEqual(user.email, "updated@test.com")
            self.assertEqual(user.major, "Machine Learning")
            self.assertEqual(user.sessions_per_week, 3)

            # Check subjects
            subjects = UserSubject.query.filter_by(user_id=self.user_id).all()
            self.assertEqual(len(subjects), 1)
            self.assertEqual(subjects[0].subject_code, "CITS1401")

            # Check availability
            avail = UserAvailability.query.filter_by(user_id=self.user_id).first()
            self.assertIsNotNone(avail)
            self.assertEqual(avail.day_of_week, "Monday")
            self.assertEqual(avail.start_time, "09:00")

    def test_missing_required_fields_fails(self):
        self.login()
        
        response = self.client.post(
            "/profile",
            data={
                "form_type": "profile",
                "email": "", # Required
                "degree": "Some Degree",
                "major": "", # Required
            },
            follow_redirects=True
        )
        
        self.assertIn(b"Email is required", response.data)
        self.assertIn(b"Major is required", response.data)

    def test_invalid_unit_code_is_rejected(self):
        self.login()
        
        response = self.client.post(
            "/profile",
            data={
                "form_type": "subjects",
                "unit1": "INVALID123" # Must be AAAA1111
            },
            follow_redirects=True
        )
        
        self.assertIn(b"is invalid. Use 4 letters followed by 4 numbers", response.data)

    def test_max_units_exceeded_is_rejected(self):
        self.login()
        
        # Route allows max 6 units (based on routes.py line 46)
        response = self.client.post(
            "/profile",
            data={
                "form_type": "subjects",
                "unit1": "CITS3401",
                "unit2": "CITS3402",
                "unit3": "CITS3403",
                "unit4": "CITS3404",
                "unit5": "CITS3405",
                "unit6": "CITS3406",
                "unit7": "CITS3407"
            },
            follow_redirects=True
        )
        
        self.assertIn(b"You can add a maximum of 6 units", response.data)


    def test_invalid_availability_times_rejected(self):
        self.login()
        
        response = self.client.post(
            "/profile",
            data={
                "form_type": "availability",
                "monday_start": "12:00",
                "monday_end": "10:00" # End before start
            },
            follow_redirects=True
        )
        
        self.assertIn(b"end time must be later than start time", response.data)

    def test_duplicate_email_update_is_rejected(self):
        # Create another user
        with app.app_context():
            other_user = User(
                first_name="Other",
                last_name="User",
                email="other@test.com",
                username="otheruser",
                degree="Arts",
                major="History"
            )
            other_user.set_password("password123")
            db.session.add(other_user)
            db.session.commit()
            
        self.login()
        
        response = self.client.post(
            "/profile",
            data={
                "form_type": "profile",
                "email": "other@test.com", # Already in use
                "degree": "Bachelor of Science",
                "major": "Data Science",
            },
            follow_redirects=True
        )

        self.assertIn(b"Email is already in use", response.data)

    def test_onboarding_finish_preserves_units_and_availability_after_profile_save(self):
        with app.app_context():
            onboarding_user = User(
                first_name="Onboard",
                last_name="User",
                email="onboard@test.com",
                username="onboarduser",
                degree="Bachelor of Science",
                major="Computer Science",
                onboarding_completed=False,
                onboarding_step=5,
            )
            onboarding_user.set_password("password123")
            db.session.add(onboarding_user)
            db.session.flush()

            db.session.add(UserSubject(user_id=onboarding_user.id, subject_code="CITS1401"))
            db.session.add(
                UserAvailability(
                    user_id=onboarding_user.id,
                    day_of_week="Monday",
                    start_time="09:00",
                    end_time="11:00",
                )
            )
            db.session.commit()

        self.client.post(
            "/login",
            data={"username": "onboarduser", "password": "password123"},
            follow_redirects=True,
        )

        response = self.client.post(
            "/profile",
            data={
                "form_type": "profile",
                "email": "onboard-updated@test.com",
                "degree": "Bachelor of Science",
                "major": "Computer Science",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        finish_response = self.client.post(
            "/onboarding/advance",
            data={"action": "finish"},
            follow_redirects=True,
        )
        self.assertEqual(finish_response.status_code, 200)
        self.assertIn(b"Onboarding complete", finish_response.data)

        with app.app_context():
            user = User.query.filter_by(username="onboarduser").first()
            self.assertIsNotNone(user)
            self.assertTrue(user.onboarding_completed)
            subjects = UserSubject.query.filter_by(user_id=user.id).all()
            self.assertEqual(len(subjects), 1)
            self.assertEqual(subjects[0].subject_code, "CITS1401")
            avail = UserAvailability.query.filter_by(user_id=user.id).first()
            self.assertIsNotNone(avail)
            self.assertEqual(avail.start_time, "09:00")

    def test_onboarding_next_follows_sidebar_sequence(self):
        with app.app_context():
            ordered_user = User(
                first_name="Order",
                last_name="User",
                email="order@test.com",
                username="orderuser",
                degree="Bachelor of Science",
                major="Computer Science",
                onboarding_completed=False,
                onboarding_step=1,
            )
            ordered_user.set_password("password123")
            db.session.add(ordered_user)
            db.session.commit()

        self.client.post(
            "/login",
            data={"username": "orderuser", "password": "password123"},
            follow_redirects=True,
        )

        expected_locations = [
            "/matches",
            "/people",
            "/messages",
            "/events",
            "/notifications",
            "/profile",
        ]

        for expected in expected_locations:
            response = self.client.post(
                "/onboarding/advance",
                data={"action": "next"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 302)
            self.assertIn(expected, response.headers.get("Location", ""))

    def test_notifications_page_accessible_during_onboarding(self):
        with app.app_context():
            nav_user = User(
                first_name="Nav",
                last_name="User",
                email="nav@test.com",
                username="navuser",
                degree="Bachelor of Science",
                major="Computer Science",
                onboarding_completed=False,
                onboarding_step=6,
            )
            nav_user.set_password("password123")
            db.session.add(nav_user)
            db.session.commit()

        self.client.post(
            "/login",
            data={"username": "navuser", "password": "password123"},
            follow_redirects=True,
        )

        response = self.client.get("/notifications", follow_redirects=False)
        self.assertEqual(response.status_code, 200)

if __name__ == "__main__":
    unittest.main()
