from flask import Blueprint, request, jsonify, render_template
from app.services.user_services import *
from app.extensions import limiter
import app.errors as errors

user = Blueprint("user", __name__, url_prefix="/user")

@user.route("/")
def route_index():
    return "User's index route"


@user.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
def route_register():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    new_user = register(data)
    return jsonify(new_user), 201


@user.route("/verify-email", methods=["POST"])
@limiter.limit("5 per minute")
def route_verify_email():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    result = verify_email(data)
    return jsonify(result)


@user.route("/resend-verification", methods=["POST"])
@limiter.limit("1 per minute")
def route_resend_verification():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    result = resend_verification(data)
    return jsonify(result)


@user.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def route_login():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    result = login(data)
    return jsonify(result)


@user.route("/reset-password-request", methods=["POST"])
@limiter.limit("5 per minute")
def route_reset_password_request():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    result = reset_password_request(data)
    return jsonify(result)


@user.route("/reset-password", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def route_reset_password():
    if request.method == "GET":
        token = request.args.get("token")
        username = request.args.get("username")
        if not token or not username:
            raise errors.BadRequest("Missing query parameters.")
        return render_template("reset_password.html", token=token, username=username)

    data = request.get_json(silent=True) or request.form.to_dict()
    if not data:
        raise errors.BadRequest("Invalid request format.")
    result = reset_password(data)
    return jsonify(result)


@user.route("/refresh-token", methods=["POST"])
@limiter.limit("10 per minute")
def route_refresh_token():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    result = refresh_token(data)
    return jsonify(result)


@user.route("/profile", methods=["POST"])
@limiter.limit("10 per minute")
def route_profile():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    result = profile(data)
    return jsonify(result)


@user.route("/submit-profile", methods=["POST"])
@limiter.limit("10 per minute")
def route_submit_profile():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    result = submit_profile(data)
    return jsonify(result)


@user.route("/change-password", methods=["POST"])
@limiter.limit("5 per minute")
def route_change_password():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    result = change_password(data)
    return jsonify(result)

@user.route("/logout", methods=["POST"])
@limiter.limit("5 per minute")
def route_logout():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    result = logout(data)
    return jsonify(result)

@user.route("/logout-all", methods=["POST"])
@limiter.limit("5 per minute")
def route_logout_all():
    data = request.get_json(silent=True)
    if not data:
        raise errors.BadRequest("Invalid JSON format.")
    result = logout_all(data)
    return jsonify(result)
