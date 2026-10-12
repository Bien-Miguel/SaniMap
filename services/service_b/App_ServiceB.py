"""SaniMap Reporting and Feedback Service."""

import os
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from xml.dom import minidom

import requests
from flask import Flask, Response, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

app = Flask(__name__)
app.config["DATABASE"] = os.environ.get(
    "SANIMAP_REPORTING_DB",
    str(Path(__file__).with_name("reporting.db")),
)
app.config["REGISTRY_URL"] = os.environ.get(
    "SANIMAP_REGISTRY_URL",
    "http://127.0.0.1:5001",
)

VALID_REPORT_TYPES = {
    "UNSANITARY_FACILITY",
    "CLEANLINESS",
    "DAMAGED_FIXTURE",
    "OUT_OF_WATER",
    "CLOSED",
    "OTHER",
}


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
    """Create the reports table and insert the demo report only on first setup."""
    path = database_path or app.config["DATABASE"]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                restroom_id INTEGER NOT NULL,
                restroom_name TEXT NOT NULL,
                report_type TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING', 'RESOLVED', 'REJECTED')),
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reports_restroom_id
            ON reports(restroom_id)
            """
        )
        connection.execute(
            """
            UPDATE reports
            SET restroom_id = 1
            WHERE report_id = 501
              AND restroom_id = 101
              AND restroom_name = 'Rizal Monument Comfort Room'
              AND description = 'Bidet is broken and floor is wet.'
              AND status = 'PENDING'
            """
        )
        count = connection.execute(
            "SELECT COUNT(*) FROM reports"
        ).fetchone()[0]
        if count == 0:
            connection.execute(
                """
                INSERT INTO reports (
                    report_id, restroom_id, restroom_name, report_type,
                    description, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    501,
                    1,
                    "Rizal Monument Comfort Room",
                    "UNSANITARY_FACILITY",
                    "Bidet is broken and floor is wet.",
                    "PENDING",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _row_to_report(row):
    return {
        "reportId": row["report_id"],
        "restroomId": row["restroom_id"],
        "restroomName": row["restroom_name"],
        "reportType": row["report_type"],
        "description": row["description"],
        "status": row["status"],
        "createdAt": row["created_at"],
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
        for item in value:
            _append_xml(element, "item", item)
    elif isinstance(value, bool):
        element.text = str(value).lower()
    elif value is not None:
        element.text = str(value)


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
            root = ET.fromstring(request.data)
        except ET.ParseError:
            return None, make_error("MALFORMED_XML", "Request body is not valid XML."), 400
        payload = {
            child.tag: child.text.strip() if child.text else ""
            for child in root
        }
        for field in ("restroomId", "restroom_id"):
            if field in payload and payload[field].isdigit():
                payload[field] = int(payload[field])
        return payload, None, None

    return None, make_error(
        "UNSUPPORTED_MEDIA_TYPE",
        "Content-Type must be application/json or application/xml.",
    ), 415


def lookup_restroom(restroom_id):
    """Return (restroom, error_status); error_status is None on success."""
    try:
        response = requests.get(
            f"{current_app.config['REGISTRY_URL']}/restrooms/{restroom_id}",
            timeout=5,
        )
    except requests.exceptions.RequestException:
        return None, 503

    if response.status_code == 404:
        return None, 404
    if response.status_code != 200:
        return None, 503
    try:
        restroom = response.json()
    except ValueError:
        return None, 502
    if not isinstance(restroom, dict):
        return None, 502
    return restroom, None


@app.errorhandler(sqlite3.Error)
def handle_database_error(error):
    app.logger.exception("Reporting database operation failed: %s", error)
    return render_payload(
        make_error("DATABASE_ERROR", "Report data could not be processed."),
        500,
        "error",
    )


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "service": "Reporting and Feedback Service (Service B)",
        "status": "UP",
        "port": 5002,
    }), 200


@app.route("/feedback/<int:restroom_id>", methods=["GET"])
def get_feedback_by_restroom(restroom_id):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM reports
            WHERE restroom_id = ?
            ORDER BY report_id
            """,
            (restroom_id,),
        ).fetchall()

    if not rows:
        return render_payload(
            make_error(
                "RESOURCE_NOT_FOUND",
                f"No feedback reports found for restroom ID {restroom_id}.",
            ),
            404,
            "error",
        )
    return render_payload(
        [_row_to_report(row) for row in rows],
        root_tag="reports",
    )


@app.route("/feedback/reports/<int:report_id>", methods=["GET"])
def get_report_status(report_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
    if row is None:
        return render_payload(
            make_error(
                "RESOURCE_NOT_FOUND",
                f"Report {report_id} was not found.",
            ),
            404,
            "error",
        )
    return render_payload(_row_to_report(row), root_tag="report")


@app.route("/feedback", methods=["POST"])
def create_feedback():
    data, error, status_code = parse_request_payload()
    if error:
        return render_payload(error, status_code, "error")

    restroom_id = data.get("restroomId", data.get("restroom_id"))
    if (
        isinstance(restroom_id, bool)
        or not isinstance(restroom_id, int)
        or restroom_id <= 0
    ):
        return render_payload(
            make_error(
                "VALIDATION_ERROR",
                "restroomId must be a positive integer.",
                field="restroomId",
            ),
            400,
            "error",
        )

    report_type = data.get("reportType")
    if not isinstance(report_type, str):
        return render_payload(
            make_error(
                "VALIDATION_ERROR",
                "reportType is required and must be a string.",
                field="reportType",
            ),
            400,
            "error",
        )
    report_type = report_type.strip().upper()
    if report_type not in VALID_REPORT_TYPES:
        return render_payload(
            make_error(
                "VALIDATION_ERROR",
                f"reportType must be one of {sorted(VALID_REPORT_TYPES)}.",
                field="reportType",
            ),
            400,
            "error",
        )

    description = data.get("description", "")
    if not isinstance(description, str):
        return render_payload(
            make_error(
                "VALIDATION_ERROR",
                "description must be a string.",
                field="description",
            ),
            400,
            "error",
        )

    restroom, lookup_error = lookup_restroom(restroom_id)
    if lookup_error == 404:
        return render_payload(
            make_error(
                "RESTROOM_NOT_FOUND",
                f"Restroom {restroom_id} does not exist in the registry.",
            ),
            404,
            "error",
        )
    if lookup_error == 503:
        return render_payload(
            make_error(
                "SERVICE_UNAVAILABLE",
                "Could not reach the Comfort Room Registry Service.",
            ),
            503,
            "error",
        )
    if lookup_error == 502:
        return render_payload(
            make_error(
                "BAD_GATEWAY",
                "Registry Service returned an invalid response.",
            ),
            502,
            "error",
        )

    restroom_name = restroom.get("name")
    if not isinstance(restroom_name, str) or not restroom_name:
        return render_payload(
            make_error(
                "BAD_GATEWAY",
                "Registry Service response did not include a restroom name.",
            ),
            502,
            "error",
        )

    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO reports (
                restroom_id, restroom_name, report_type,
                description, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                restroom_id,
                restroom_name,
                report_type,
                description,
                "PENDING",
                created_at,
            ),
        )
        row = connection.execute(
            "SELECT * FROM reports WHERE report_id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return render_payload(_row_to_report(row), 201, "report")


initialize_database()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
