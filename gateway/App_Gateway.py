import os

from flask import Flask, request, Response, jsonify
import requests

app = Flask(__name__)

SERVICE_A_URL = "http://127.0.0.1:5001"
SERVICE_B_URL = "http://127.0.0.1:5002"
TIMEOUT_SECONDS = 5

# Methods the gateway is willing to forward to a backend service.
FORWARDED_METHODS = {"GET", "POST", "PUT"}


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


@app.route("/restrooms/<restroom_id>", methods=["GET"])
def get_restroom(restroom_id):
    return forward_request(SERVICE_A_URL, f"/restrooms/{restroom_id}")


@app.route("/restrooms/<restroom_id>/status", methods=["PUT"])
def update_restroom_status(restroom_id):
    return forward_request(SERVICE_A_URL, f"/restrooms/{restroom_id}/status")


@app.route("/feedback", methods=["POST"])
def create_feedback():
    return forward_request(SERVICE_B_URL, "/feedback")


@app.route("/feedback/<restroom_id>", methods=["GET"])
def get_feedback(restroom_id):
    return forward_request(SERVICE_B_URL, f"/feedback/{restroom_id}")


if __name__ == "__main__":
    # Debug mode is OFF unless GATEWAY_DEBUG=1 is set explicitly (local dev only).
    # Host defaults to localhost; set GATEWAY_HOST=0.0.0.0 only when needed.
    app.run(
        host=os.environ.get("GATEWAY_HOST", "127.0.0.1"),
        port=int(os.environ.get("GATEWAY_PORT", "5000")),
        debug=os.environ.get("GATEWAY_DEBUG") == "1",
    )