import unittest
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service

from webdriver_manager.chrome import ChromeDriverManager


class AuthPageTests(unittest.TestCase):

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
    
    
