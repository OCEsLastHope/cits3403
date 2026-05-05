from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect

from config import Config

db = SQLAlchemy()
migrate = Migrate()
app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
migrate.init_app(app, db)


def ensure_test_data():
    from .database import Notification, User

    existing_tables = set(inspect(db.engine).get_table_names())
    required_tables = {"user", "notification"}
    if not required_tables.issubset(existing_tables):
        return

    if User.query.count() == 0:
        test_user = User(
            first_name="Mineth",
            last_name="Perera",
            email="mineth@test.com",
            degree="Bachelor of Engineering",
            major="Software Engineering",
            username="Mineth1"
        )
        db.session.add(test_user)
        db.session.commit()

    if Notification.query.count() == 0:
        db.session.add_all(
            [
                Notification(
                    user_id=1,
                    sender_name="Daniel K.",
                    type="dm",
                    message="Hey, did you review the <strong>design brief</strong>?",
                    channel="Direct message",
                ),
                Notification(
                    user_id=1,
                    sender_name="Marcus S.",
                    type="mention",
                    message="<strong>@you</strong> can you push the deploy before 5pm?",
                    channel="#engineering",
                ),
                Notification(
                    user_id=1,
                    sender_name="Tom N.",
                    type="dm",
                    message="Quick question about the <strong>Q3 report</strong>.",
                    channel="Direct message",
                ),
            ]
        )
        db.session.commit()


from . import routes

with app.app_context():
    ensure_test_data()
