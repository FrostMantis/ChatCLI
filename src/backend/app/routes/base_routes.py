from flask import Blueprint, request, jsonify, render_template
from app.services.base_services import verify_connection, subscribe
from app.errors import BadRequest

base = Blueprint("base", __name__)

@base.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@base.route("/verify-connection", methods=["GET", "POST"])
def route_verify_connection():
    # Parse JSON only for POST
    if request.method == "POST":
        data = request.get_json(silent=True)
        if data is None:
            raise BadRequest("Invalid JSON format.")
    else:
        data = {}

    result = verify_connection(data)
    return jsonify(result)

@base.route("/subscribe", methods=["GET", "POST"])
def route_subscribe():
    # Parse JSON only for POST
    if request.method == "POST":
        data = request.get_json(silent=True)
        if data is None:
            raise BadRequest("Invalid JSON format.")
    else:
        data = {}

    result = subscribe(data)
    return jsonify(result)
