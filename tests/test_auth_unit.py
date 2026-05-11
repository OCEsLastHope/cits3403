import unittest

from app import app, db
from app.database import User


class AuthUnitTests(unittest.TestCase):

    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

        with app.app_context():
            User.query.filter_by(email="unit@example.com").delete()
            User.query.filter_by(email="duplicate@example.com").delete()
            User.query.filter_by(email="new@example.com").delete()

            User.query.filter_by(username="unituser").delete()
            User.query.filter_by(username="duplicateuser").delete()
            User.query.filter_by(username="newuser123").delete()

            db.session.commit()

    def tearDown(self):
        with app.app_context():
            User.query.filter_by(email="unit@example.com").delete()
            User.query.filter_by(email="duplicate@example.com").delete()
            User.query.filter_by(email="new@example.com").delete()

            User.query.filter_by(username="unituser").delete()
            User.query.filter_by(username="duplicateuser").delete()
            User.query.filter_by(username="newuser123").delete()

            db.session.commit()

    def create_test_user(self, email="unit@example.com", username="unituser"):
        user = User(
            first_name="Unit",
            last_name="Test",
            email=email,
            username=username,
            degree="Computer Science",
            major="Computer Science",
        )

        user.set_password("password123")

        db.session.add(user)
        db.session.commit()

        return user

    def test_password_hashing_works(self):
        user = User(
            first_name="Unit",
            last_name="Test",
            email="unit@example.com",
            username="unituser",
            degree="Computer Science",
            major="Computer Science",
        )

        user.set_password("password123")

        self.assertNotEqual(user.password_hash, "password123")
        self.assertTrue(user.check_password("password123"))
        self.assertFalse(user.check_password("wrongpassword"))

    def test_duplicate_email_registration_is_rejected(self):
        with app.app_context():
            self.create_test_user(
                email="duplicate@example.com",
                username="duplicateuser",
            )

        response = self.client.post(
            "/register",
            data={
                "first_name": "New",
                "last_name": "User",
                "email": "duplicate@example.com",
                "username": "newuser123",
                "degree_type": "other",
                "degree": "Computer Science",
                "major": "Computer Science",
                "password": "password123",
                "confirm_password": "password123",
            },
            follow_redirects=True,
        )

        self.assertIn(b"Email already exists", response.data)

    def test_duplicate_username_registration_is_rejected(self):
        with app.app_context():
            self.create_test_user(
                email="unit@example.com",
                username="duplicateuser",
            )

        response = self.client.post(
            "/register",
            data={
                "first_name": "New",
                "last_name": "User",
                "email": "new@example.com",
                "username": "duplicateuser",
                "degree_type": "other",
                "degree": "Computer Science",
                "major": "Computer Science",
                "password": "password123",
                "confirm_password": "password123",
            },
            follow_redirects=True,
        )

        self.assertIn(b"Username is already taken", response.data)

    def test_password_mismatch_registration_is_rejected(self):
        response = self.client.post(
            "/register",
            data={
                "first_name": "Unit",
                "last_name": "Test",
                "email": "unit@example.com",
                "username": "unituser",
                "degree_type": "other",
                "degree": "Computer Science",
                "major": "Computer Science",
                "password": "password123",
                "confirm_password": "wrongpassword",
            },
            follow_redirects=True,
        )

        self.assertIn(
            b"Password and confirm password must match",
            response.data,
        )

    def test_invalid_login_is_rejected(self):
        response = self.client.post(
            "/login",
            data={
                "username": "fakeuser",
                "password": "wrongpassword",
            },
            follow_redirects=True,
        )

        self.assertIn(b"Invalid username/email or password", response.data)

    def test_invalid_email_format_is_rejected(self):
        response = self.client.post(
            "/register",
            data={
                "first_name": "Unit",
                "last_name": "Test",
                "email": "bademail",
                "username": "unituser",
                "degree_type": "other",
                "degree": "Computer Science",
                "major": "Computer Science",
                "password": "password123",
                "confirm_password": "password123",
            },
            follow_redirects=True,
        )

        self.assertIn(b"Invalid email address", response.data)


if __name__ == "__main__":
    unittest.main()
    
    
    
    
    