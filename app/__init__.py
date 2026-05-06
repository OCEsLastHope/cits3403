from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import inspect
from flask_socketio import SocketIO

from config import Config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
migrate.init_app(app, db)
login_manager.init_app(app)
login_manager.login_view = "login"
csrf.init_app(app)
socketio = SocketIO(app)


@login_manager.user_loader
def load_user(user_id):
    from .database import User

    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def ensure_test_data():
    from .database import DegreeCategory, DegreeOption, Notification, User

    existing_tables = set(inspect(db.engine).get_table_names())
    required_tables = {"user", "notification", "degree_category", "degree_option"}

    if not required_tables.issubset(existing_tables):
        return

    degree_seed = {
        "bachelors": {
            "label": "Bachelor's degree",
            "options": [
                "Bachelor of Agribusiness [BP020]",
                "Bachelor of Agricultural Science [BP019]",
                "Bachelor of Art History and Curatorial Studies [BP070]",
                "Bachelor of Arts [BP001]",
                "Bachelor of Arts (Integrated Professional) [BW001]",
                "Bachelor of Biological Science [BP025]",
                "Bachelor of Biomedical Science [BP006]",
                "Bachelor of Biomedicine (Specialised) [BP056]",
                "Bachelor of Business [BP009]",
                "Bachelor of Commerce [BP002]",
                "Bachelor of Commerce (Integrated Professional) [BW002]",
                "Bachelor of Criminology and Criminal Justice [BP050]",
                "Bachelor of Earth Sciences [BP029]",
                "Bachelor of Economics [BP013]",
                "Bachelor of Environmental Design [BP011]",
                "Bachelor of Environmental Science [BP022]",
                "Bachelor of Geographical and Spatial Science [BP055]",
                "Bachelor of Human Rights [BP034]",
                "Bachelor of Human Sciences [BP031]",
                "Bachelor of International Relations [BP058]",
                "Bachelor of Letters [BP501]",
                "Bachelor of Marine Science [BP023]",
                "Bachelor of Mathematics [BP059]",
                "Bachelor of Media and Communication [BP069]",
                "Bachelor of Modern Languages [BP054]",
                "Bachelor of Molecular Sciences [BP028]",
                "Bachelor of Music [BP008]",
                "Bachelor of Philosophy, Politics and Economics [BP012]",
                "Bachelor of Psychological Studies [BP503]",
                "Bachelor of Psychology [BP030]",
                "Bachelor of Science [BP004]",
                "Bachelor of Science (Integrated Professional) [BW004]",
                "Bachelor of Science and Technology [BP502]",
                "Bachelor of Social and Environmental Sustainability [BP062]",
                "Bachelor of Sport and Exercise Sciences [BP026]",
            ],
        },
        "honours": {
            "label": "Honours",
            "options": [
                "Bachelor of Advanced Computer Science [Honours] [BH008]",
                "Bachelor of Arts (Honours) [BH001]",
                "Bachelor of Biological Science (Honours) [BH024]",
                "Bachelor of Biomedical Science (Honours) [BH006]",
                "Bachelor of Business (Honours) [BH021]",
                "Bachelor of Commerce (Honours) [BH002]",
                "Bachelor of Criminology and Criminal Justice (Honours) [BH018]",
                "Bachelor of Earth Sciences (Honours) [BH026]",
                "Bachelor of Economics (Honours) [BH013]",
                "Bachelor of Education (Primary) (Honours) [BH020]",
                "Bachelor of Engineering (Honours) [BH011]",
                "Bachelor of Environmental Design (Honours) [BH040]",
                "Bachelor of Human Rights Honours [BH019]",
                "Bachelor of Landscape Architecture (Honours) [BH039]",
                "Bachelor of Marine Science (Honours) [BH025]",
                "Bachelor of Mathematics (Honours) [BH035]",
                "Bachelor of Modern Languages Honours [BH016]",
                "Bachelor of Music (Honours) [BH009]",
                "Bachelor of Nursing (Honours) [BH028]",
                "Bachelor of Philosophy (Honours) [BH005]",
                "Bachelor of Philosophy, Politics, and Economics (Honours) [BH015]",
                "Bachelor of Psychology (Honours) [BH014]",
                "Bachelor of Science (Honours) [BH004]",
                "Bachelor of Social Work (Honours) [BH017]",
                "Bachelor of Sport and Exercise Sciences (Honours) [BH032]",
            ],
        },
        "combined_bachelors": {
            "label": "Combined Bachelor's + Bachelor's",
            "options": [
                "Bachelor of Agribusiness and Bachelor of Science [CB001]",
                "Bachelor of Agricultural Science and Bachelor of Arts [CB009]",
                "Bachelor of Agricultural Science and Bachelor of Commerce [CB010]",
                "Bachelor of Agricultural Science and Bachelor of Science [CB003]",
                "Bachelor of Art History and Curatorial Studies and Bachelor of Arts [CB049]",
                "Bachelor of Art History and Curatorial Studies and Bachelor of Commerce [CB052]",
                "Bachelor of Criminology and Criminal Justice and Bachelor of Arts [CB047]",
                "Bachelor of Criminology and Criminal Justice and Bachelor of Science [CB053]",
                "Bachelor of Economics / Bachelor of Commerce [CB020]",
                "Bachelor of Engineering (Honours) and Bachelor of Modern Languages [CB030]",
                "Bachelor of Engineering (Honours)/ Bachelor of Arts [CB034]",
                "Bachelor of Engineering (Honours)/ Bachelor of Commerce [CB006]",
                "Bachelor of Engineering (Honours)/ Bachelor of Philosophy (Honours) [CB014]",
                "Bachelor of Engineering (Honours)/ Bachelor of Science [CB004]",
                "Bachelor of Environmental Science and Bachelor of Arts [CB008]",
                "Bachelor of Environmental Science and Bachelor of Commerce [CB007]",
                "Bachelor of Environmental Science and Bachelor of Science [CB002]",
                "Bachelor of Human Rights and Bachelor of Arts [CB022]",
                "Bachelor of Human Rights and Bachelor of Commerce [CB023]",
                "Bachelor of International Relations and Bachelor of Arts [CB046]",
                "Bachelor of International Relations and Bachelor of Commerce [CB054]",
                "Bachelor of Mathematics and Bachelor of Arts [CB044]",
                "Bachelor of Media and Communication and Bachelor of Arts [CB021]",
                "Bachelor of Media and Communication and Bachelor of Commerce [CB048]",
                "Bachelor of Modern Languages and Bachelor of Arts [CB026]",
                "Bachelor of Modern Languages and Bachelor of Biomedical Science [CB032]",
                "Bachelor of Modern Languages and Bachelor of Business [CB028]",
                "Bachelor of Modern Languages and Bachelor of Commerce [CB027]",
                "Bachelor of Modern Languages and Bachelor of Science [CB029]",
                "Bachelor of Music and Bachelor of Arts [CB038]",
                "Bachelor of Music and Bachelor of Biomedical Science [CB042]",
                "Bachelor of Music and Bachelor of Business [CB041]",
                "Bachelor of Music and Bachelor of Science [CB039]",
                "Bachelor of Philosophy (Honours)/Bachelor of Modern Languages [CB031]",
                "Bachelor of Philosophy, Politics and Economics and Bachelor of Arts [CB012]",
                "Bachelor of Philosophy, Politics and Economics and Bachelor of Commerce [CB017]",
                "Bachelor of Psychology and Bachelor of Arts [CB011]",
                "Bachelor of Psychology and Bachelor of Commerce [CB013]",
                "Bachelor of Psychology and Bachelor of Science [CB043]",
                "Bachelor of Social and Environmental Sustainability and Bachelor of Arts [CB045]",
            ],
        },
        "combined_masters": {
            "label": "Combined Bachelor's + Master's",
            "options": [
                "Bachelor of Biological Science and Master of Biotechnology [CM029]",
                "Bachelor of Marine Science and Master of Environmental Science [CM011]",
                "Bachelor of Sport and Exercise Sciences and Master of Public Health [CM017]",
                "Bachelor of Agribusiness and Master of Agricultural Economics [CM014]",
                "Bachelor of Agricultural Science and Master of Agricultural Science [CM013]",
                "Bachelor of Biological Science and Master of Biological Science [CM005]",
                "Bachelor of Earth Sciences and Master of Geoscience [CM009]",
                "Bachelor of Earth Sciences and Master of Oceanography [CM012]",
                "Bachelor of Economics and Master of Economics [CM002]",
                "Bachelor of Environmental Science and Master of Environmental Science [CM008]",
                "Bachelor of Geographical and Spatial Science and Master of Environmental Science [CM032]",
                "Bachelor of Human Sciences (Pharmaceutical Health) and Doctor of Pharmacy [CM039]",
                "Bachelor of Human Sciences and Master of Bioinformatics [CM021]",
                "Bachelor of Human Sciences and Master of Biomedical Science [CM030]",
                "Bachelor of Marine Science and Master of Marine Biology [CM010]",
                "Bachelor of Marine Sciences and Master of Oceanography [CM038]",
                "Bachelor of Molecular Sciences and Master of Biomedical Science [CM004]",
                "Bachelor of Molecular Sciences and Master of Biotechnology [CM007]",
                "Bachelor of Molecular Sciences and Master of Bioinformatics [CM024]",
                "Bachelor of Science Frontier Physics and Master of Physics [CM015]",
                "Bachelor of Science Frontier Physics and Master of Physics - Medical Physics [CM040]",
                "Bachelor of Sport and Exercise Sciences and Master of Clinical Exercise Physiology [CM018]",
                "Bachelor of Sport and Exercise Sciences and Master of Applied Human Performance Science [CM019]",
            ],
        },
    }

    # Seed degree categories and options first
    for key, payload in degree_seed.items():
        category = DegreeCategory.query.filter_by(key=key).first()

        if category is None:
            category = DegreeCategory(key=key, label=payload["label"])
            db.session.add(category)
            db.session.flush()
        else:
            category.label = payload["label"]

        for option_name in payload["options"]:
            exists = DegreeOption.query.filter_by(
                category_id=category.id,
                name=option_name
            ).first()

            if exists is None:
                db.session.add(
                    DegreeOption(
                        category_id=category.id,
                        name=option_name,
                        is_active=True
                    )
                )

    db.session.commit()

    # Only seed test users/notifications if the user table has password_hash
    user_columns = {column["name"] for column in inspect(db.engine).get_columns("user")}

    if "password_hash" not in user_columns:
        return

    engineering_degree = DegreeOption.query.filter(
        DegreeOption.name.ilike("%Bachelor of Engineering%")
    ).first()

    if User.query.count() == 0:
        test_user = User(
            first_name="Mineth",
            last_name="Perera",
            email="mineth@test.com",
            degree=engineering_degree.name if engineering_degree else "Bachelor of Engineering",
            degree_option_id=engineering_degree.id if engineering_degree else None,
            major="Software Engineering",
            username="Mineth1",
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


if __name__ == "__main__":
    socketio.run(app, debug=True)
    
    
    
    
    
    
