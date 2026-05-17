import unittest
import time
import os
import threading

# Force database URL to a separate test database file for selenium.
# This prevents it from overwriting the main development database.
os.environ["DATABASE_URL"] = "sqlite:///test_selenium.db"
os.environ["TEST_DATABASE_URL"] = "sqlite:///test_selenium.db"

from app import app, db
from app.database import User
from config import TestConfig

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service

from webdriver_manager.chrome import ChromeDriverManager


class AuthPageTests(unittest.TestCase):
    server_thread = None
    server_url = "http://127.0.0.1:5050"

    @classmethod
    def setUpClass(cls):
        # Configure app for testing
        app.config.from_object(TestConfig)

        # Initialize the database
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()

            # Seed a default user for login tests
            user = User(
                first_name="Selenium",
                last_name="Test",
                email="selenium@example.com",
                username="seleniumuser",
                degree="Computer Science",
                major="Computer Science",
            )
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()

        # Start the live server in a background daemon thread
        def run_server():
            # Disable reloader and debugger to avoid process issues in tests
            app.run(port=5050, debug=False, use_reloader=False)

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()

        # Give the server a moment to start up and bind to the port
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        # Clean up database tables
        with app.app_context():
            db.session.remove()
            db.drop_all()

        # Try to delete the test database file
        try:
            if os.path.exists("instance/test_selenium.db"):
                os.remove("instance/test_selenium.db")
            elif os.path.exists("test_selenium.db"):
                os.remove("test_selenium.db")
        except Exception:
            pass

    def setUp(self):
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install())
        )

    def test_register_page_loads(self):
        self.driver.get("http://127.0.0.1:5050/register")
        self.assertIn("Register", self.driver.page_source)

    def test_email_field_exists(self):
        self.driver.get("http://127.0.0.1:5050/register")
        email_input = self.driver.find_element(By.NAME, "email")
        self.assertIsNotNone(email_input)

    def test_username_field_exists(self):
        self.driver.get("http://127.0.0.1:5050/register")
        username_input = self.driver.find_element(By.NAME, "username")
        self.assertIsNotNone(username_input)

    def test_password_field_exists(self):
        self.driver.get("http://127.0.0.1:5050/register")
        password_input = self.driver.find_element(By.NAME, "password")
        self.assertIsNotNone(password_input)

    def test_register_button_exists(self):
        self.driver.get("http://127.0.0.1:5050/register")
        button = self.driver.find_element(By.CLASS_NAME, "register-btn")
        self.assertIsNotNone(button)

    def test_login_page_loads(self):
        self.driver.get("http://127.0.0.1:5050/login")
        self.assertIn("Login", self.driver.page_source)

    def test_login_fields_exist(self):
        self.driver.get("http://127.0.0.1:5050/login")
        username_input = self.driver.find_element(By.NAME, "username")
        password_input = self.driver.find_element(By.NAME, "password")
        self.assertIsNotNone(username_input)
        self.assertIsNotNone(password_input)

    def test_forgot_password_page_loads(self):
        self.driver.get("http://127.0.0.1:5050/forgot_password")
        self.assertIn("Forgot", self.driver.page_source)

    def test_invalid_email_message_on_register(self):
        self.driver.get("http://127.0.0.1:5050/register")
        email_input = self.driver.find_element(By.ID, "email")
        email_input.send_keys("notanemail")
        time.sleep(1)
        self.assertIn(
            "Enter a valid email format.",
            self.driver.page_source
        )

    def test_password_mismatch_message_on_register(self):
        self.driver.get("http://127.0.0.1:5050/register")
        password_input = self.driver.find_element(By.ID, "password")
        confirm_password_input = self.driver.find_element(By.ID, "confirm-password")

        password_input.send_keys("password123")
        confirm_password_input.send_keys("wrongpassword")

        time.sleep(1)

        self.assertIn(
            "Passwords do not match.",
            self.driver.page_source
        )

    def tearDown(self):
        time.sleep(1)
        self.driver.quit()


if __name__ == "__main__":
    unittest.main()
    
    
