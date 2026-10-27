"""SaniMap Comfort Room Registry Service."""

import json
import math
import os
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from xml.dom import minidom

from flask import Flask, Response, current_app, jsonify, request
from dotenv import load_dotenv
from werkzeug.exceptions import BadRequest

load_dotenv()

app = Flask(__name__)
app.config["DATABASE"] = os.environ.get(
    "SANIMAP_REGISTRY_DB",
    str(Path(__file__).with_name("registry.db")),
)

VALID_STATUS = {"open", "closed", "under_maintenance"}
REQUIRED_FIELDS = (
    "name",
    "latitude",
    "longitude",
    "operatingHours",
    "pwdAccessible",
    "genderType",
    "amenities",
    "status",
)

SEED_RESTROOMS = (
    {
        "name": "Rizal Monument Comfort Room",
        "latitude": 14.5826,
        "longitude": 120.9787,
        "operatingHours": "06:00-20:00",
        "pwdAccessible": True,
        "genderType": "Unisex",
        "amenities": ["Handwashing Station", "Soap", "Bidet"],
        "status": "open",
    },
    {
        "name": "Children's Playground Comfort Room",
        "latitude": 14.5810,
        "longitude": 120.9795,
        "operatingHours": "07:00-19:00",
        "pwdAccessible": False,
        "genderType": "Male/Female",
        "amenities": ["Handwashing Station"],
        "status": "under_maintenance",
    },
    {
        "name": "Manila Ocean Park Restroom",
        "latitude": 14.5791,
        "longitude": 120.9723,
        "operatingHours": "10:00 - 20:00",
        "pwdAccessible": True,
        "genderType": "Unisex",
        "amenities": [
            "Air-conditioned",
            "Handwashing Station",
            "Soap",
            "Toilet Paper",
            "Bidet",
            "Flush Toilet",
        ],
        "status": "open",
    },
    {
        "name": "Quirino Grandstand Comfort Room",
        "latitude": 14.5800,
        "longitude": 120.9739,
        "operatingHours": "06:00 - 22:00",
        "pwdAccessible": True,
        "genderType": "Unisex",
        "amenities": [
            "Handwashing Station",
            "Soap",
            "Toilet Paper",
            "Flush Toilet",
            "Wheelchair Ramp",
        ],
        "status": "open",
    },
    {
        "name": "Relief Map Comfort Room",
        "latitude": 14.5835,
        "longitude": 120.9798,
        "operatingHours": "06:00 - 20:00",
        "pwdAccessible": True,
        "genderType": "Unisex",
        "amenities": ["Handwashing Station", "Soap", "Flush Toilet"],
        "status": "open",
    },
)


@contextmanager
def get_connection():
    connection = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(database_path=None):
    """Create the registry table and ensure canonical seed facilities exist."""
    path = database_path or app.config["DATABASE"]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS restrooms (
                restroom_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                operating_hours TEXT NOT NULL,
                pwd_accessible INTEGER NOT NULL CHECK (pwd_accessible IN (0, 1)),
                gender_type TEXT NOT NULL,
                amenities_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('open', 'closed', 'under_maintenance')
                )
            )
            """
        )
        legacy_names = {
            "Manila Ocean Park Comfort Room": "Manila Ocean Park Restroom",
        }
        for old_name, seed_name in legacy_names.items():
            seed_exists = connection.execute(
                "SELECT 1 FROM restrooms WHERE name = ? LIMIT 1",
                (seed_name,),
            ).fetchone()
            if not seed_exists:
                connection.execute(
                    "UPDATE restrooms SET name = ? WHERE name = ?",
                    (seed_name, old_name),
                )
        for restroom in SEED_RESTROOMS:
            values = (
                restroom["latitude"],
                restroom["longitude"],
                restroom["operatingHours"],
                int(restroom["pwdAccessible"]),
                restroom["genderType"],
                json.dumps(restroom["amenities"]),
            )
            existing = connection.execute(
                "SELECT restroom_id FROM restrooms WHERE name = ? LIMIT 1",
                (restroom["name"],),
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE restrooms
                    SET latitude = ?, longitude = ?, operating_hours = ?,
                        pwd_accessible = ?, gender_type = ?, amenities_json = ?
                    WHERE name = ?
                    """,
                    (*values, restroom["name"]),
                )
                continue
            connection.execute(
                """
                INSERT INTO restrooms (
                    name, latitude, longitude, operating_hours,
                    pwd_accessible, gender_type, amenities_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    restroom["name"],
                    *values,
                    restroom["status"],
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _row_to_restroom(row):
    return {
        "restroomId": row["restroom_id"],
        "name": row["name"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "operatingHours": row["operating_hours"],
        "pwdAccessible": bool(row["pwd_accessible"]),
        "genderType": row["gender_type"],
        "amenities": json.loads(row["amenities_json"]),
        "status": row["status"],
    }


def make_error(code, message, field=None):
    error = {"error": code, "message": message}
    if field:
        error["field"] = field
    return error


def wants_xml():
    best = request.accept_mimetypes.best_match(
        ["application/json", "application/xml"]
    )
    return best == "application/xml"


def _append_xml(parent, key, value):
    element = ET.SubElement(parent, key)
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _append_xml(element, child_key, child_value)
    elif isinstance(value, (list, tuple)):
        item_key = "item"
        if key == "amenities":
            item_key = "amenity"
        for item in value:
            _append_xml(element, item_key, item)
    elif isinstance(value, bool):
        element.text = str(value).lower()
    elif value is not None:
        element.text = str(value)
    return element


def dict_to_xml(payload, root_tag):
    root = ET.Element(root_tag)
    if isinstance(payload, list):
        item_tag = root_tag[:-1] if root_tag.endswith("s") else "item"
        for value in payload:
            _append_xml(root, item_tag, value)
    else:
        for key, value in payload.items():
            _append_xml(root, key, value)
    return minidom.parseString(
        ET.tostring(root, encoding="unicode")
    ).toprettyxml(indent="    ")


def render_payload(payload, status_code=200, root_tag="response"):
    if wants_xml():
        return Response(
            dict_to_xml(payload, root_tag),
            status=status_code,
            mimetype="application/xml",
        )
    return jsonify(payload), status_code


def _to_number(value):
    try:
        if value is None:
            return None
        return float(value) if "." in value else int(value)
    except (BadRequest, ValueError, TypeError):
        return value


def parse_xml_payload(xml_bytes):
    root = ET.fromstring(xml_bytes)
    data = {}

    def text_of(tag):
        element = root.find(tag)
        return element.text.strip() if element is not None and element.text else None

    for field in ("name", "operatingHours", "genderType", "status"):
        if root.find(field) is not None:
            data[field] = text_of(field)

    for field in ("latitude", "longitude", "restroomId"):
        if root.find(field) is not None:
            data[field] = _to_number(text_of(field))

    if root.find("pwdAccessible") is not None:
        raw_value = text_of("pwdAccessible")
        if raw_value is not None and raw_value.lower() in {"true", "false"}:
            data["pwdAccessible"] = raw_value.lower() == "true"
        else:
            data["pwdAccessible"] = raw_value

    amenities = root.find("amenities")
    if amenities is not None:
        data["amenities"] = [
            element.text.strip()
            for element in amenities.findall("amenity")
            if element.text and element.text.strip()
        ]

    return data


def parse_request_payload():
    if request.mimetype == "application/json":
        try:
            payload = request.get_json(silent=False)
        except (BadRequest, ValueError, TypeError):
            return None, make_error("MALFORMED_JSON", "Request body is not valid JSON."), 400
        if not isinstance(payload, dict):
            return None, make_error(
                "MALFORMED_JSON", "Request body must be a JSON object."
            ), 400
        return payload, None, None

    if request.mimetype in {"application/xml", "text/xml"}:
        try:
            payload = parse_xml_payload(request.data)
        except ET.ParseError:
            return None, make_error("MALFORMED_XML", "Request body is not valid XML."), 400
        return payload, None, None

    return None, make_error(
        "UNSUPPORTED_MEDIA_TYPE",
        "Content-Type must be application/json or application/xml.",
    ), 415


def validate_restroom(data):
    for field in REQUIRED_FIELDS:
        if field not in data or data[field] in (None, ""):
            return make_error(
                "VALIDATION_ERROR",
                f"{field} is required.",
                field=field,
            )

    for field in ("name", "operatingHours", "genderType"):
        if not isinstance(data[field], str) or not data[field].strip():
            return make_error(
                "VALIDATION_ERROR",
                f"{field} must be a non-empty string.",
                field=field,
            )

    for field, lower, upper in (
        ("latitude", -90, 90),
        ("longitude", -180, 180),
    ):
        value = data[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not lower <= value <= upper
        ):
            return make_error(
                "VALIDATION_ERROR",
                f"{field} must be a valid coordinate.",
                field=field,
            )

    if not isinstance(data["pwdAccessible"], bool):
        return make_error(
            "VALIDATION_ERROR",
            "pwdAccessible must be a boolean.",
            field="pwdAccessible",
        )

    if (
        not isinstance(data["amenities"], list)
        or not data["amenities"]
        or any(not isinstance(item, str) or not item.strip() for item in data["amenities"])
    ):
        return make_error(
            "VALIDATION_ERROR",
            "amenities must be a non-empty list of strings.",
            field="amenities",
        )

    # Length limits keep one request from storing oversized text.
    for field, limit in (("name", 120), ("operatingHours", 40), ("genderType", 30)):
        if len(data[field].strip()) > limit:
            return make_error(
                "VALIDATION_ERROR",
                f"{field} must be at most {limit} characters.",
                field=field,
            )

    if len(data["amenities"]) > 20 or any(len(item.strip()) > 60 for item in data["amenities"]):
        return make_error(
            "VALIDATION_ERROR",
            "amenities allows at most 20 items of 60 characters each.",
            field="amenities",
        )

    if not isinstance(data["status"], str) or data["status"] not in VALID_STATUS:
        return make_error(
            "VALIDATION_ERROR",
            f"status must be one of {sorted(VALID_STATUS)}.",
            field="status",
        )

    if "restroomId" in data and (
        isinstance(data["restroomId"], bool)
        or not isinstance(data["restroomId"], int)
        or data["restroomId"] <= 0
    ):
        return make_error(
            "VALIDATION_ERROR",
            "restroomId must be a positive integer.",
            field="restroomId",
        )
    return None


@app.errorhandler(sqlite3.Error)
def handle_database_error(error):
    app.logger.exception("Registry database operation failed: %s", error)
    return render_payload(
        make_error("DATABASE_ERROR", "Registry data could not be processed."),
        500,
        "error",
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="UP", service="Comfort Room Registry Service"), 200


@app.route("/restrooms", methods=["GET"])
def get_restrooms():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM restrooms ORDER BY restroom_id"
        ).fetchall()
    return render_payload([_row_to_restroom(row) for row in rows], root_tag="restrooms")


@app.route("/restrooms/<int:restroom_id>", methods=["GET"])
def get_restroom(restroom_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM restrooms WHERE restroom_id = ?",
            (restroom_id,),
        ).fetchone()
    if row is None:
        return render_payload(
            make_error(
                "RESOURCE_NOT_FOUND",
                f"Restroom {restroom_id} does not exist.",
            ),
            404,
            "error",
        )
    return render_payload(_row_to_restroom(row), root_tag="restroom")


@app.route("/restrooms", methods=["POST"])
def create_restroom():
    data, error, status_code = parse_request_payload()
    if error:
        return render_payload(error, status_code, "error")

    validation_error = validate_restroom(data)
    if validation_error:
        return render_payload(validation_error, 400, "error")

    requested_id = data.get("restroomId")
    values = (
        data["name"].strip(),
        data["latitude"],
        data["longitude"],
        data["operatingHours"].strip(),
        int(data["pwdAccessible"]),
        data["genderType"].strip(),
        json.dumps(data["amenities"]),
        data["status"],
    )
    with get_connection() as connection:
        if requested_id is not None:
            exists = connection.execute(
                "SELECT 1 FROM restrooms WHERE restroom_id = ?",
                (requested_id,),
            ).fetchone()
            if exists:
                return render_payload(
                    make_error(
                        "CONFLICT",
                        f"Restroom {requested_id} already exists.",
                    ),
                    409,
                    "error",
                )
            cursor = connection.execute(
                """
                INSERT INTO restrooms (
                    restroom_id, name, latitude, longitude, operating_hours,
                    pwd_accessible, gender_type, amenities_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (requested_id, *values),
            )
            new_id = requested_id
        else:
            cursor = connection.execute(
                """
                INSERT INTO restrooms (
                    name, latitude, longitude, operating_hours,
                    pwd_accessible, gender_type, amenities_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            new_id = cursor.lastrowid

        row = connection.execute(
            "SELECT * FROM restrooms WHERE restroom_id = ?",
            (new_id,),
        ).fetchone()
    return render_payload(_row_to_restroom(row), 201, "restroom")


@app.route("/restrooms/<int:restroom_id>/status", methods=["PUT"])
def update_restroom_status(restroom_id):
    data, error, status_code = parse_request_payload()
    if error:
        return render_payload(error, status_code, "error")

    new_status = data.get("status")
    if not isinstance(new_status, str) or new_status not in VALID_STATUS:
        return render_payload(
            make_error(
                "VALIDATION_ERROR",
                f"status must be one of {sorted(VALID_STATUS)}.",
                field="status",
            ),
            400,
            "error",
        )

    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE restrooms SET status = ? WHERE restroom_id = ?",
            (new_status, restroom_id),
        )
        if cursor.rowcount == 0:
            return render_payload(
                make_error(
                    "RESOURCE_NOT_FOUND",
                    f"Restroom {restroom_id} does not exist.",
                ),
                404,
                "error",
            )
        row = connection.execute(
            "SELECT * FROM restrooms WHERE restroom_id = ?",
            (restroom_id,),
        ).fetchone()
    return render_payload(_row_to_restroom(row), root_tag="restroom")


initialize_database()

if __name__ == "__main__":
    # Backend services are not authenticated: only the gateway may reach them,
    # so bind to loopback unless a deployment explicitly overrides it.
    app.run(
        host=os.environ.get("SANIMAP_BIND_HOST", "127.0.0.1"),
        port=5001,
        debug=False,
    )