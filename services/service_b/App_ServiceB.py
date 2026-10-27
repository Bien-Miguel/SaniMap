"""SaniMap Reporting and Feedback Service."""

import hashlib
import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from xml.dom import minidom

import requests
from dotenv import load_dotenv
from flask import Flask, Response, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

load_dotenv()

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

VALID_REPORT_STATUSES = {"PENDING", "RESOLVED", "REJECTED"}
MAX_DESCRIPTION_LENGTH = 1000  # matches the frontend textarea limit
MAX_PAGE_SIZE = 200

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
    connection.row_factory = sqlite3.Row
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
                created_at TEXT NOT NULL,
                idempotency_key TEXT,
                request_hash TEXT
            )
            """
        )
        report_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(reports)").fetchall()
        }
        if "idempotency_key" not in report_columns:
            connection.execute("ALTER TABLE reports ADD COLUMN idempotency_key TEXT")
        if "request_hash" not in report_columns:
            connection.execute("ALTER TABLE reports ADD COLUMN request_hash TEXT")
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reports_restroom_id
            ON reports(restroom_id)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_idempotency_key
            ON reports(idempotency_key)
            WHERE idempotency_key IS NOT NULL
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

def validation_response(message, field):
    return render_payload(
        make_error("VALIDATION_ERROR", message, field=field), 400, "error"
    )

def parse_int_arg(name, default, minimum, maximum=None):
    """Return (value, None) or (None, error_response) for an optional integer query arg."""
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        return default, None
    try:
        value = int(raw)
    except ValueError:
        return None, validation_response(f"{name} must be a whole number.", name)
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"between {minimum} and {maximum}" if maximum else f"at least {minimum}"
        return None, validation_response(f"{name} must be {bound}.", name)
    return value, None

@app.route("/feedback", methods=["GET"])
def list_feedback():
    """List reports across all restrooms (staff view). Always 200, even when empty."""
    clauses, params = [], []
    status = request.args.get("status")
    if status is not None and status.strip() != "":
        status = status.strip().upper()
        if status not in VALID_REPORT_STATUSES:
            return validation_response(
                f"status must be one of {sorted(VALID_REPORT_STATUSES)}.", "status"
            )
        clauses.append("status = ?")
        params.append(status)
    restroom_id, error = parse_int_arg("restroomId", None, 1)
    if error:
        return error
    if restroom_id is not None:
        clauses.append("restroom_id = ?")
        params.append(restroom_id)
    limit, error = parse_int_arg("limit", 100, 1, MAX_PAGE_SIZE)
    if error:
        return error
    offset, error = parse_int_arg("offset", 0, 0)
    if error:
        return error
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM reports {where} ORDER BY created_at DESC, report_id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return render_payload([_row_to_report(row) for row in rows], root_tag="reports")


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
    description = description.strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return validation_response(
            f"description must be at most {MAX_DESCRIPTION_LENGTH} characters.",
            "description",
        )

    idempotency_key = request.headers.get("Idempotency-Key")
    request_hash = None
    if idempotency_key:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key):
            return render_payload(
                make_error(
                    "VALIDATION_ERROR",
                    "Idempotency-Key must be 1 to 128 safe characters.",
                    field="Idempotency-Key",
                ),
                400,
                "error",
            )
        request_hash = hashlib.sha256(
            json.dumps(
                [restroom_id, report_type, description],
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with get_connection() as connection:
            existing = connection.execute(
                "SELECT * FROM reports WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                return render_payload(
                    make_error(
                        "IDEMPOTENCY_CONFLICT",
                        "This idempotency key was already used for a different report.",
                    ),
                    409,
                    "error",
                )
            return render_payload(_row_to_report(existing), 201, "report")

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
                description, status, created_at, idempotency_key, request_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                restroom_id,
                restroom_name,
                report_type,
                description,
                "PENDING",
                created_at,
                idempotency_key,
                request_hash,
            ),
        )
        row = connection.execute(
            "SELECT * FROM reports WHERE report_id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return render_payload(_row_to_report(row), 201, "report")


@app.route("/feedback/reports/<int:report_id>/status", methods=["PUT"])
def update_report_status(report_id):
    """Staff action: mark a report PENDING, RESOLVED or REJECTED."""
    data, error, status_code = parse_request_payload()
    if error:
        return render_payload(error, status_code, "error")
    new_status = data.get("status")
    if not isinstance(new_status, str) or new_status.strip().upper() not in VALID_REPORT_STATUSES:
        return validation_response(
            f"status must be one of {sorted(VALID_REPORT_STATUSES)}.", "status"
        )
    new_status = new_status.strip().upper()
    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE reports SET status = ? WHERE report_id = ?",
            (new_status, report_id),
        )
        if cursor.rowcount == 0:
            return render_payload(
                make_error("RESOURCE_NOT_FOUND", f"Report {report_id} was not found."),
                404,
                "error",
            )
        row = connection.execute(
            "SELECT * FROM reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
    return render_payload(_row_to_report(row), root_tag="report")

initialize_database()
if __name__ == "__main__":
    # Backend services are not authenticated: only the gateway may reach them,
    # so bind to loopback unless a deployment explicitly overrides it.
    app.run(
        host=os.environ.get("SANIMAP_BIND_HOST", "127.0.0.1"),
        port=5002,
        debug=False,
    )