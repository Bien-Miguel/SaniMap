import os
import sys

import jwt
import requests
from dotenv import load_dotenv
from flask import Flask, request, Response, jsonify

# Loads the local, git-ignored .env file (JWT_SECRET, ORS_API_KEY, ...).
load_dotenv()

# The gateway serves no static files, so the default /static route is disabled.
app = Flask(__name__, static_folder=None)

SERVICE_A_URL = "http://127.0.0.1:5001"
SERVICE_B_URL = "http://127.0.0.1:5002"
TIMEOUT_SECONDS = 5

# Methods the gateway is willing to forward to a backend service.
FORWARDED_METHODS = {"GET", "POST", "PUT"}

JWT_ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32

# Access policy (default deny): every gateway route must be listed here.
#   None  -> public, no token needed
#   tuple -> a valid Bearer token whose "role" claim is one of these roles
PUBLIC = None
ADMIN = ("admin",)
STAFF = ("admin", "park_manager")

ROUTE_POLICY = {
    ("GET", "/health"): PUBLIC,
    ("GET", "/health/all"): STAFF,
    ("GET", "/restrooms"): PUBLIC,
    ("POST", "/restrooms"): ADMIN,
    ("GET", "/restrooms/<int:restroom_id>"): PUBLIC,
    ("PUT", "/restrooms/<int:restroom_id>/status"): ADMIN,
    ("POST", "/feedback"): PUBLIC,
    ("GET", "/feedback/<int:restroom_id>"): STAFF,
    ("GET", "/feedback/reports/<int:report_id>"): PUBLIC,
}


def jwt_settings():
    return {
        "secret": os.environ.get("JWT_SECRET", ""),
        "issuer": os.environ.get("JWT_ISSUER", ""),
        "audience": os.environ.get("JWT_AUDIENCE", ""),
    }


def config_problems():
    """Return a list of security configuration problems (empty list = OK)."""
    settings = jwt_settings()
    problems = []
    if len(settings["secret"]) < MIN_SECRET_LENGTH:
        problems.append(
            f"JWT_SECRET must be set and at least {MIN_SECRET_LENGTH} characters long."
        )
    if not settings["issuer"]:
        problems.append("JWT_ISSUER must be set.")
    if not settings["audience"]:
        problems.append("JWT_AUDIENCE must be set.")
    return problems


def auth_error(code, message, status):
    response = jsonify({"error": code, "message": message})
    response.status_code = status
    if status == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


def get_bearer_token():
    parts = request.headers.get("Authorization", "").split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    return parts[1]


@app.before_request
def enforce_access_policy():
    # Unknown routes and wrong methods are handled by the JSON 404/405 handlers.
    if request.url_rule is None or request.method == "OPTIONS":
        return None

    method = "GET" if request.method == "HEAD" else request.method
    policy_key = (method, request.url_rule.rule)
    if policy_key not in ROUTE_POLICY:
        return auth_error("FORBIDDEN", "No access policy exists for this route.", 403)

    allowed_roles = ROUTE_POLICY[policy_key]
    if allowed_roles is None:
        return None

    # Protected route: fail closed if security settings are missing.
    if config_problems():
        return auth_error(
            "AUTH_NOT_CONFIGURED", "Authentication is not configured.", 500
        )

    token = get_bearer_token()
    if token is None:
        return auth_error("UNAUTHORIZED", "A valid Bearer token is required.", 401)

    settings = jwt_settings()
    try:
        claims = jwt.decode(
            token,
            settings["secret"],
            algorithms=[JWT_ALGORITHM],
            issuer=settings["issuer"],
            audience=settings["audience"],
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError:
        return auth_error("UNAUTHORIZED", "Token has expired.", 401)
    except jwt.InvalidTokenError:
        return auth_error("UNAUTHORIZED", "Invalid token.", 401)

    # The role comes only from the verified token, never from client headers.
    if claims.get("role") not in allowed_roles:
        return auth_error(
            "FORBIDDEN", "You do not have permission to perform this action.", 403
        )
    return None


def forward_request(base_url, path):
    """Forward the current request (method, query string, body) to a backend."""
    method = request.method
    if method not in FORWARDED_METHODS:
        return jsonify({"error": "METHOD_NOT_ALLOWED"}), 405

    url = f"{base_url}{path}"
    forward_headers = {}
    if "Content-Type" in request.headers:
        forward_headers["Content-Type"] = request.headers["Content-Type"]
    if "Accept" in request.headers:
        forward_headers["Accept"] = request.headers["Accept"]

    # Pass the raw query string through unchanged so encoding, repeated
    # parameters and optional parameters are preserved exactly as received.
    query_string = request.query_string.decode("latin-1")
    if query_string:
        url = f"{url}?{query_string}"

    body = request.get_data() if method in {"POST", "PUT"} else None

    try:
        resp = requests.request(
            method,
            url,
            headers=forward_headers,
            data=body,
            timeout=TIMEOUT_SECONDS,
        )

        return Response(
            resp.content,
            status=resp.status_code,
            content_type=resp.headers.get("Content-Type", "application/json"),
        )

    except requests.exceptions.ConnectionError:
        return jsonify({
            "error": "SERVICE_UNAVAILABLE",
            "message": f"Could not reach backend service at {base_url}."
        }), 503

    except requests.exceptions.Timeout:
        return jsonify({
            "error": "SERVICE_TIMEOUT",
            "message": f"Backend service at {base_url} timed out."
        }), 503


@app.errorhandler(404)
def handle_not_found(_error):
    return jsonify({"error": "NOT_FOUND", "message": "Route not found."}), 404


@app.errorhandler(405)
def handle_method_not_allowed(_error):
    return jsonify({"error": "METHOD_NOT_ALLOWED"}), 405


@app.route("/health", methods=["GET"])
def gateway_health():
    return jsonify({"service": "API Gateway", "status": "UP"}), 200


@app.route("/health/all", methods=["GET"])
def aggregated_health():
    results = {}
    for name, base_url in [("registry_service", SERVICE_A_URL), ("reporting_service", SERVICE_B_URL)]:
        try:
            r = requests.get(f"{base_url}/health", timeout=TIMEOUT_SECONDS)
            results[name] = r.json()
        except requests.exceptions.RequestException:
            results[name] = {"status": "DOWN"}
    return jsonify({"gateway": "UP", "services": results}), 200


@app.route("/restrooms", methods=["GET", "POST"])
def restrooms_root():
    return forward_request(SERVICE_A_URL, "/restrooms")


@app.route("/restrooms/<int:restroom_id>", methods=["GET"])
def get_restroom(restroom_id):
    return forward_request(SERVICE_A_URL, f"/restrooms/{restroom_id}")


@app.route("/restrooms/<int:restroom_id>/status", methods=["PUT"])
def update_restroom_status(restroom_id):
    return forward_request(SERVICE_A_URL, f"/restrooms/{restroom_id}/status")


@app.route("/feedback", methods=["POST"])
def create_feedback():
    return forward_request(SERVICE_B_URL, "/feedback")


@app.route("/feedback/<int:restroom_id>", methods=["GET"])
def get_feedback(restroom_id):
    return forward_request(SERVICE_B_URL, f"/feedback/{restroom_id}")


@app.route("/feedback/reports/<int:report_id>", methods=["GET"])
def get_report_status(report_id):
    return forward_request(SERVICE_B_URL, f"/feedback/reports/{report_id}")


if __name__ == "__main__":
    host = os.environ.get("GATEWAY_HOST", "127.0.0.1")
    debug = os.environ.get("GATEWAY_DEBUG") == "1"

    # Refuse to start with unsafe or incomplete security configuration.
    problems = config_problems()
    if debug and host != "127.0.0.1":
        problems.append("GATEWAY_DEBUG=1 is only allowed when GATEWAY_HOST is 127.0.0.1.")
    if problems:
        for problem in problems:
            print(f"Startup refused: {problem}", file=sys.stderr)
        sys.exit(1)

    # Debug mode is OFF unless GATEWAY_DEBUG=1 is set explicitly (local dev only).
    app.run(host=host, port=int(os.environ.get("GATEWAY_PORT", "5000")), debug=debug)