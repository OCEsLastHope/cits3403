from flask import render_template

from ..blueprints import main_bp


@main_bp.route("/")
def landing():
    return render_template("landing.html")
