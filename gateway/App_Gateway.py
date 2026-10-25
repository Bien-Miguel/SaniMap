from flask import Flask, request, Response, jsonify
import requests

app = Flask(__name__)

SERVICE_A_URL = "http://127.0.0.1:5001"
SERVICE_B_URL = "http://127.0.0.1:5002"
TIMEOUT_SECONDS = 5


def forward_request(base_url, path, method="GET"):
    url = f"{base_url}{path}"
    forward_headers = {}
    if "Content-Type" in request.headers:
        forward_headers["Content-Type"] = request.headers["Content-Type"]
    if "Accept" in request.headers:
        forward_headers["Accept"] = request.headers["Accept"]

    try:
        if method == "GET":
            resp = requests.get(url, headers=forward_headers, timeout=TIMEOUT_SECONDS)
        elif method == "POST":
            resp = requests.post(url, headers=forward_headers, data=request.get_data(), timeout=TIMEOUT_SECONDS)
        else:
            return jsonify({"error": "METHOD_NOT_ALLOWED"}), 405

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
    return forward_request(SERVICE_A_URL, "/restrooms", method=request.method)


@app.route("/restrooms/<restroom_id>", methods=["GET"])
def get_restroom(restroom_id):
    return forward_request(SERVICE_A_URL, f"/restrooms/{restroom_id}", method="GET")


@app.route("/feedback", methods=["POST"])
def create_feedback():
    return forward_request(SERVICE_B_URL, "/feedback", method="POST")


@app.route("/feedback/<restroom_id>", methods=["GET"])
def get_feedback(restroom_id):
    return forward_request(SERVICE_B_URL, f"/feedback/{restroom_id}", method="GET")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
