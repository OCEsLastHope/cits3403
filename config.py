import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Unsafe fallback for development only; set SECRET_KEY in environment for production.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-unsafe-secret-key")

    SQLALCHEMY_DATABASE_URI = "sqlite:///studysync.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 587
    MAIL_USE_TLS = True

    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")

    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_USERNAME")
    