import os


class Config:
    # Unsafe fallback for development only; set SECRET_KEY in environment for production.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-unsafe-secret-key")
    SQLALCHEMY_DATABASE_URI = "sqlite:///studysync.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
