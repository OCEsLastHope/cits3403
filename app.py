from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///studysync.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    degree = db.Column(db.String(100), nullable=False)
    major = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f'<User {self.email}>'

with app.app_context():
    db.create_all()

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/profile")
def profile():
    return render_template("userpages.html")


if __name__ == "__main__":
    app.run(debug=True)