
## SaniMap - Comfort Room (CR) Registry Service
=============================================
This service implements Laboratory Parts 4, 7, and 10:

  Part 4  - Data Contract
            Defines the Comfort Room resource and its equivalent
            JSON / XML representations (see docs/examples/resource.json
            and docs/examples/resource.xml).

  Part 7  - Content Negotiation
            GET /restrooms/<id> inspects the Accept header and returns
            either application/json or application/xml for the SAME
            resource.

  Part 10 - Validation & Error Handling
            POST /restrooms and GET /restrooms/<id> return structured,
            content-negotiated error bodies for (at least) these
            scenarios:
              1. Missing required field         -> 400 VALIDATION_ERROR
              2. Invalid data (wrong type/value) -> 400 VALIDATION_ERROR
              3. Malformed JSON                  -> 400 MALFORMED_JSON
              4. Malformed XML                   -> 400 MALFORMED_XML
              5. Resource does not exist         -> 404 RESOURCE_NOT_FOUND
              6. Duplicate/conflicting operation -> 409 CONFLICT
              7. Unsupported request media type  -> 415 UNSUPPORTED_MEDIA_TYPE

Run:
    pip install -r requirements.txt
    python app.py
Service listens on http://localhost:5001
"""

from flask import Flask, request, Response, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory "database" of Comfort Room (CR) records  (Part 4 - Data Contract)
# ---------------------------------------------------------------------------
restrooms = {
    101: {
        "restroomId": 101,
        "name": "Rizal Monument Comfort Room",
        "latitude": 14.5826,
        "longitude": 120.9787,
        "operatingHours": "06:00-20:00",
        "pwdAccessible": True,
        "genderType": "Unisex",
        "amenities": ["Handwashing Station", "Soap", "Bidet"],
        "status": "open"
    },
    102: {
        "restroomId": 102,
        "name": "Children's Playground Comfort Room",
        "latitude": 14.5810,
        "longitude": 120.9795,
        "operatingHours": "07:00-19:00",
        "pwdAccessible": False,
        "genderType": "Male/Female",
        "amenities": ["Handwashing Station"],
        "status": "under_maintenance"
    }
}
_next_id = 103

REQUIRED_FIELDS = [
    "name", "latitude", "longitude", "operatingHours",
    "pwdAccessible", "genderType", "amenities", "status"
]
VALID_STATUS = {"open", "closed", "under_maintenance"}


# ---------------------------------------------------------------------------
# Serialization / Deserialization helpers  (support for Part 4 & 6)
# ---------------------------------------------------------------------------
def restroom_to_xml_string(restroom):
    """Serialize a restroom dict into a well-formed, pretty-printed XML string."""
    root = ET.Element("restroom")

    def add(tag, value):
        el = ET.SubElement(root, tag)
        el.text = str(value).lower() if isinstance(value, bool) else str(value)

    add("restroomId", restroom["restroomId"])
    add("name", restroom["name"])
    add("latitude", restroom["latitude"])
    add("longitude", restroom["longitude"])
    add("operatingHours", restroom["operatingHours"])
    add("pwdAccessible", restroom["pwdAccessible"])
    add("genderType", restroom["genderType"])

    amenities_el = ET.SubElement(root, "amenities")
    for amenity in restroom["amenities"]:
        a = ET.SubElement(amenities_el, "amenity")
        a.text = amenity

    add("status", restroom["status"])

    rough = ET.tostring(root, encoding="unicode")
    return minidom.parseString(rough).toprettyxml(indent="    ")


def xml_string_to_restroom(xml_bytes):
    """
    Deserialize an XML request body into a restroom dict.
    Raises ET.ParseError on malformed XML (caught by the caller).
    """
    root = ET.fromstring(xml_bytes)
    data = {}

    def text_of(tag):
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else None

    if root.find("name") is not None:
        data["name"] = text_of("name")
    if root.find("latitude") is not None:
        data["latitude"] = _to_number(text_of("latitude"))
    if root.find("longitude") is not None:
        data["longitude"] = _to_number(text_of("longitude"))
    if root.find("operatingHours") is not None:
        data["operatingHours"] = text_of("operatingHours")
    if root.find("pwdAccessible") is not None:
        data["pwdAccessible"] = text_of("pwdAccessible").lower() == "true"
    if root.find("genderType") is not None:
        data["genderType"] = text_of("genderType")
    amenities_el = root.find("amenities")
    if amenities_el is not None:
        data["amenities"] = [a.text for a in amenities_el.findall("amenity") if a.text]
    if root.find("status") is not None:
        data["status"] = text_of("status")
    if root.find("restroomId") is not None:
        data["restroomId"] = _to_number(text_of("restroomId"))

    return data


def _to_number(value):
    try:
        if value is None:
            return None
        return float(value) if "." in value else int(value)
    except (ValueError, TypeError):
        return value  # let validation catch the type error


# ---------------------------------------------------------------------------
# Error helpers  (Part 10 - Validation & Error Handling)
# ---------------------------------------------------------------------------
def make_error(code, message, field=None):
    error = {"error": code, "message": message}
    if field:
        error["field"] = field
    return error


def wants_xml(accept_header):
    """Very small content-negotiation rule: XML only if explicitly asked for."""
    accept_header = (accept_header or "").lower()
    return "application/xml" in accept_header and "application/json" not in accept_header


def render_resource(payload_dict, accept_header, status_code=200, root_builder=None):
    """Render either a restroom or an error dict as JSON or XML."""
    if wants_xml(accept_header):
        if root_builder:
            body = root_builder(payload_dict)
        else:
            body = _dict_to_generic_xml(payload_dict)
        return Response(body, status=status_code, mimetype="application/xml")
    return jsonify(payload_dict), status_code


def _dict_to_generic_xml(d, root_tag="error"):
    root = ET.Element(root_tag)
    for k, v in d.items():
        el = ET.SubElement(root, k)
        el.text = str(v)
    rough = ET.tostring(root, encoding="unicode")
    return minidom.parseString(rough).toprettyxml(indent="    ")


def validate_restroom(data):
    """Returns an error dict (Part 10) if invalid, otherwise None."""
    for field in REQUIRED_FIELDS:
        if field not in data or data[field] in (None, ""):
            return make_error(
                "VALIDATION_ERROR",
                f"{field} is required.",
                field=field
            )

    if not isinstance(data["latitude"], (int, float)) or not isinstance(data["longitude"], (int, float)):
        return make_error(
            "VALIDATION_ERROR",
            "latitude and longitude must be numeric.",
            field="latitude/longitude"
        )

    if not isinstance(data["pwdAccessible"], bool):
        return make_error(
            "VALIDATION_ERROR",
            "pwdAccessible must be a boolean (true/false).",
            field="pwdAccessible"
        )

    if not isinstance(data["amenities"], list) or not data["amenities"]:
        return make_error(
            "VALIDATION_ERROR",
            "amenities must be a non-empty list.",
            field="amenities"
        )

    if data["status"] not in VALID_STATUS:
        return make_error(
            "VALIDATION_ERROR",
            f"status must be one of {sorted(VALID_STATUS)}.",
            field="status"
        )

    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="UP", service="Comfort Room Registry Service"), 200


@app.route("/restrooms/<int:restroom_id>", methods=["GET"])
def get_restroom(restroom_id):
    """Part 7 - Content Negotiation on a single resource."""
    accept_header = request.headers.get("Accept", "application/json")
    restroom = restrooms.get(restroom_id)

    # Part 10 - Resource does not exist -> 404
    if restroom is None:
        error = make_error("RESOURCE_NOT_FOUND", f"Restroom {restroom_id} does not exist.")
        return render_resource(error, accept_header, 404)

    if wants_xml(accept_header):
        return Response(restroom_to_xml_string(restroom), status=200, mimetype="application/xml")
    return jsonify(restroom), 200


@app.route("/restrooms", methods=["POST"])
def create_restroom():
    """Part 6/7 input side + Part 10 - Validation & Error Handling."""
    global _next_id
    content_type = request.headers.get("Content-Type", "")
    accept_header = request.headers.get("Accept", "application/json")

    # --- Deserialize based on Content-Type ---
    if "application/json" in content_type:
        try:
            data = request.get_json(force=False, silent=False)
            if data is None:
                raise ValueError("empty body")
        except Exception:
            error = make_error("MALFORMED_JSON", "Request body is not valid JSON.")
            return render_resource(error, accept_header, 400)

    elif "application/xml" in content_type or "text/xml" in content_type:
        try:
            data = xml_string_to_restroom(request.data)
        except ET.ParseError as e:
            error = make_error("MALFORMED_XML", f"Request body is not valid XML: {e}")
            return render_resource(error, accept_header, 400)

    else:
        # Part 10 - Unsupported request media type -> 415
        error = make_error(
            "UNSUPPORTED_MEDIA_TYPE",
            "Content-Type must be application/json or application/xml."
        )
        return render_resource(error, accept_header, 415)

    # --- Part 10 - Duplicate / conflicting operation -> 409 ---
    if "restroomId" in data and data["restroomId"] in restrooms:
        error = make_error(
            "CONFLICT",
            f"Restroom {data['restroomId']} already exists."
        )
        return render_resource(error, accept_header, 409)

    # --- Part 10 - Validation (missing field / invalid data) -> 400 ---
    error = validate_restroom(data)
    if error:
        return render_resource(error, accept_header, 400)

    # --- Business processing: assign id and store ---
    new_id = data.get("restroomId") or _next_id
    if new_id == _next_id:
        _next_id += 1
    data["restroomId"] = new_id
    restrooms[new_id] = data

    if wants_xml(accept_header):
        return Response(restroom_to_xml_string(data), status=201, mimetype="application/xml")
    return jsonify(data), 201


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
