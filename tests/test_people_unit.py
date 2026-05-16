import os
import unittest

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")

from app import app, db
from app.database import FriendRequest, User
from config import TestConfig


class PeopleUnitTests(unittest.TestCase):
    def setUp(self):
        app.config.from_object(TestConfig)
        self.client = app.test_client()

        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()

            self.user_a = self._create_user("alice", "alice@example.com")
            self.user_b = self._create_user("albert", "albert@example.com")
            self.user_c = self._create_user("bob", "bob@example.com")
            self.user_d = self._create_user("alex", "alex@example.com")
            db.session.commit()
            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id
            self.user_c_id = self.user_c.id
            self.user_d_id = self.user_d.id

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def _create_user(self, username, email):
        user = User(
            first_name=username.capitalize(),
            last_name="User",
            email=email,
            username=username,
            degree="Computer Science",
            major="Computer Science",
            onboarding_completed=True,
        )
        user.set_password("password123")
        db.session.add(user)
        return user

    def _login(self, username="alice", password="password123"):
        return self.client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=True,
        )

    def test_people_route_requires_authentication(self):
        response = self.client.get("/people", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_username_search_prefix_case_insensitive_and_excludes_self(self):
        self._login("alice")
        response = self.client.get("/people?tab=discover&q=Al", follow_redirects=True)
        body = response.get_data(as_text=True)

        self.assertIn("albert", body)
        self.assertIn("alex", body)
        self.assertNotIn('<h5 class="mb-1">alice</h5>', body)
        self.assertNotIn("bob", body)

    def test_username_search_requires_two_characters(self):
        self._login("alice")
        response = self.client.get("/people?tab=discover&q=a", follow_redirects=True)
        self.assertIn("Enter at least 2 characters to search.", response.get_data(as_text=True))

    def test_send_friend_request_creates_pending(self):
        self._login("alice")
        response = self.client.post(f"/friends/request/{self.user_b_id}", follow_redirects=True)
        self.assertIn("Friend request sent.", response.get_data(as_text=True))

        with app.app_context():
            relation = FriendRequest.query.one()
            self.assertEqual(relation.status, "pending")
            self.assertEqual(relation.requested_by_id, self.user_a_id)

    def test_duplicate_pending_request_is_blocked(self):
        self._login("alice")
        self.client.post(f"/friends/request/{self.user_b_id}", follow_redirects=True)
        response = self.client.post(f"/friends/request/{self.user_b_id}", follow_redirects=True)

        self.assertIn("already pending", response.get_data(as_text=True))
        with app.app_context():
            self.assertEqual(FriendRequest.query.count(), 1)

    def test_accept_incoming_friend_request(self):
        self._login("alice")
        self.client.post(f"/friends/request/{self.user_b_id}", follow_redirects=True)

        self.client.get("/logout", follow_redirects=True)
        self._login("albert")

        with app.app_context():
            relation = FriendRequest.query.one()
            relation_id = relation.id

        self.client.post(f"/friends/{relation_id}/accept", follow_redirects=True)

        with app.app_context():
            relation = FriendRequest.query.one()
            self.assertEqual(relation.status, "accepted")

    def test_reject_then_rerequest_allowed(self):
        self._login("alice")
        self.client.post(f"/friends/request/{self.user_b_id}", follow_redirects=True)

        self.client.get("/logout", follow_redirects=True)
        self._login("albert")

        with app.app_context():
            relation = FriendRequest.query.one()
            relation_id = relation.id

        self.client.post(f"/friends/{relation_id}/reject", follow_redirects=True)
        self.client.get("/logout", follow_redirects=True)

        self._login("alice")
        self.client.post(f"/friends/request/{self.user_b.id}", follow_redirects=True)

        with app.app_context():
            relation = FriendRequest.query.one()
            self.assertEqual(relation.status, "pending")
            self.assertEqual(relation.requested_by_id, self.user_a_id)

    def test_cancel_outgoing_friend_request(self):
        self._login("alice")
        self.client.post(f"/friends/request/{self.user_b_id}", follow_redirects=True)

        with app.app_context():
            relation = FriendRequest.query.one()
            relation_id = relation.id

        self.client.post(f"/friends/{relation_id}/cancel", follow_redirects=True)

        with app.app_context():
            relation = FriendRequest.query.one()
            self.assertEqual(relation.status, "cancelled")


if __name__ == "__main__":
    unittest.main()
