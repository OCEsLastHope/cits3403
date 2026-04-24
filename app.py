from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
<<<<<<< HEAD
def landing():
    return render_template("landing.html")


@app.route("/dashboard")
=======
>>>>>>> e9009b485ef4edf9eec4fabc15a4c58dce6defa1
def dashboard():
    return render_template("dashboard.html")


@app.route("/profile")
def profile():
    return render_template("userpages.html")


if __name__ == "__main__":
    app.run(debug=True)