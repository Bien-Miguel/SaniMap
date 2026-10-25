from flask import Flask, jsonify, request, Response
import xmltodict
import dicttoxml
import requests

app = Flask(__name__)

SERVICE_A_URL = "http://127.0.0.1:5001"

feedback_db = [
    {
        "reportId": 501,
        "restroom_id": "cr-001",
        "reportType": "UNSANITARY_FACILITY",
        "description": "Bidet is broken and floor is wet.",
        "status": "PENDING"
    }
]

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "service": "Reporting and Feedback Service (Service B)",
        "status": "UP",
        "port": 5002
    }), 200

@app.route('/feedback/<string:restroom_id>', methods=['GET'])
def get_feedback_by_restroom(restroom_id):
    reports = [r for r in feedback_db if r["restroom_id"] == restroom_id]

    if not reports:
        return jsonify({
            "error": "RESOURCE_NOT_FOUND",
            "message": f"No feedback reports found for restroom ID {restroom_id}"
        }), 404

    # Content Negotiation: XML response if Accept header requests it
    if request.headers.get('Accept') == 'application/xml':
        xml_data = dicttoxml.dicttoxml(reports, custom_root='reports', attr_type=False)
        return Response(xml_data, mimetype='application/xml'), 200

    return jsonify(reports), 200


def get_restroom_from_registry(restroom_id):
    """
    Part 8: Calls Service A, deserializes the JSON response, and
    returns the actual restroom data so Service B can use it in a
    real business decision (not just a yes/no existence check).
    Returns dict  -> restroom data if found
            False -> restroom not found
            None  -> Service A could not be reached
    """
    try:
        response = requests.get(f"{SERVICE_A_URL}/restrooms/{restroom_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
        return False
    except requests.exceptions.ConnectionError:
        return None
    except requests.exceptions.Timeout:
        return None


@app.route('/feedback', methods=['POST'])
def create_feedback():
    content_type = request.headers.get('Content-Type')

    # 1. Parse Input Payload (XML vs JSON)
    if content_type == 'application/xml':
        try:
            parsed = xmltodict.parse(request.data)
            data = parsed.get('feedback') or list(parsed.values())[0]
        except Exception:
            return jsonify({"error": "INVALID_XML", "message": "Malformed XML payload"}), 400
    else:
        data = request.get_json() or {}

    # 2. Validate Required Fields
    if 'restroom_id' not in data or 'reportType' not in data:
        return jsonify({
            "error": "VALIDATION_ERROR",
            "message": "Missing required fields: restroom_id or reportType"
        }), 400

        # 3. Part 8: Service-to-service integration — get and use restroom data from Service A
    restroom = get_restroom_from_registry(data['restroom_id'])

    if restroom is None:
        return jsonify({
            "error": "SERVICE_UNAVAILABLE",
            "message": "Could not reach Comfort Room Registry Service to validate restroom_id."
        }), 503

    if restroom is False:
        return jsonify({
            "error": "RESTROOM_NOT_FOUND",
            "message": f"restroom_id '{data['restroom_id']}' does not exist in the registry."
        }), 404

    new_report = {
        "reportId": len(feedback_db) + 501,
        "restroom_id": data['restroom_id'],
        "restroom_name": restroom.get("name", "Unknown"),
        "reportType": data['reportType'],
        "description": data.get('description', ''),
        "status": "PENDING"
    }
    feedback_db.append(new_report)

    # 4. Respond in XML if specified in Content-Type or Accept headers
    if content_type == 'application/xml' or request.headers.get('Accept') == 'application/xml':
        xml_res = dicttoxml.dicttoxml(new_report, custom_root='report', attr_type=False)
        return Response(xml_res, mimetype='application/xml'), 201

    return jsonify(new_report), 201

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=True)
