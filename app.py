from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/profile")
def profile():
    return render_template("userpages.html")


if __name__ == "__main__":
    app.run(debug=True)