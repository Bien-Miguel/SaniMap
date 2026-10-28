"""SaniMap Maintenance Work Order Service."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
app.config["DATABASE"] = os.environ.get(
    "SANIMAP_WORK_ORDERS_DB",
    str(Path(__file__).with_name("work_orders.db")),
)
app.config["REPORTING_URL"] = os.environ.get(
    "SANIMAP_REPORTING_URL",
    "http://127.0.0.1:5002",
).rstrip("/")

VALID_STATUSES = {"OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
VALID_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "URGENT"}
MAX_TITLE_LENGTH = 160
MAX_DESCRIPTION_LENGTH = 1000
MAX_ASSIGNEE_LENGTH = 120
MAX_PAGE_SIZE = 200
EDITABLE_FIELDS = {
    "title": ("title", MAX_TITLE_LENGTH),
    "description": ("description", MAX_DESCRIPTION_LENGTH),
    "priority": ("priority", None),
    "status": ("status", None),
    "assignedTo": ("assigned_to", MAX_ASSIGNEE_LENGTH),
}


@contextmanager
def get_connection():
    connection = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(database_path=None):
    path = database_path or app.config["DATABASE"]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS work_orders (
                work_order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL UNIQUE,
                restroom_id INTEGER NOT NULL,
                restroom_name TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL
                    CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')),
                status TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
                assigned_to TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_work_orders_status_created
            ON work_orders(status, created_at DESC)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS work_order_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_order_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                field TEXT,
                old_value TEXT,
                new_value TEXT,
                occurred_at TEXT NOT NULL,
                FOREIGN KEY (work_order_id) REFERENCES work_orders(work_order_id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_work_order_events_order
            ON work_order_events(work_order_id, event_id)
            """
        )
        connection.commit()
    finally:
        connection.close()


def make_error(code, message, field=None):
    payload = {"error": code, "message": message}
    if field:
        payload["field"] = field
    return jsonify(payload)


def row_to_work_order(row):
    return {
        "workOrderId": row["work_order_id"],
        "reportId": row["report_id"],
        "restroomId": row["restroom_id"],
        "restroomName": row["restroom_name"],
        "title": row["title"],
        "description": row["description"],
        "priority": row["priority"],
        "status": row["status"],
        "assignedTo": row["assigned_to"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def parse_json_object():
    if not request.is_json:
        return None, make_error(
            "UNSUPPORTED_MEDIA_TYPE",
            "Content-Type must be application/json.",
        ), 415
    try:
        payload = request.get_json()
    except BadRequest:
        return None, make_error("MALFORMED_JSON", "Request body contains invalid JSON."), 400
    if not isinstance(payload, dict):
        return None, make_error("VALIDATION_ERROR", "Request body must be a JSON object."), 400
    return payload, None, None


def report_for_work_order(report_id):
    try:
        response = requests.get(
            f"{current_app.config['REPORTING_URL']}/feedback/reports/{report_id}",
            timeout=5,
        )
    except requests.exceptions.RequestException:
        return None, make_error(
            "REPORTING_SERVICE_UNAVAILABLE",
            "The Reporting Service is unavailable; the work order was not created.",
        ), 503

    if response.status_code == 404:
        return None, make_error("REPORT_NOT_FOUND", "The visitor report was not found."), 404
    if response.status_code != 200:
        return None, make_error(
            "REPORTING_SERVICE_ERROR",
            "The Reporting Service could not validate the visitor report.",
        ), 502
    try:
        report = response.json()
    except (TypeError, ValueError):
        report = None
    if (
        not isinstance(report, dict)
        or report.get("reportId") != report_id
        or isinstance(report.get("restroomId"), bool)
        or not isinstance(report.get("restroomId"), int)
        or report["restroomId"] <= 0
        or not isinstance(report.get("restroomName"), str)
        or not report["restroomName"].strip()
    ):
        return None, make_error(
            "REPORTING_BAD_RESPONSE",
            "The Reporting Service returned an invalid report.",
        ), 502
    return report, None, None


def validation_error(message, field):
    return make_error("VALIDATION_ERROR", message, field), 400


def parse_integer_query(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        return default, None
    try:
        value = int(raw)
    except ValueError:
        return None, validation_error(f"{name} must be a whole number.", name)
    if value < minimum or (maximum is not None and value > maximum):
        return None, validation_error(f"{name} is outside the allowed range.", name)
    return value, None


@app.errorhandler(sqlite3.Error)
def handle_database_error(error):
    app.logger.exception("Maintenance database operation failed: %s", error)
    return make_error("DATABASE_ERROR", "Work order data could not be processed."), 500


@app.errorhandler(413)
def handle_request_too_large(_error):
    return make_error("REQUEST_TOO_LARGE", "Request body must be 16 KB or smaller."), 413


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "service": "Maintenance Work Order Service (Service C)",
        "status": "UP",
        "port": 5003,
    }), 200


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    clauses, params = [], []
    status = request.args.get("status")
    if status is not None and status.strip():
        status = status.strip().upper()
        if status not in VALID_STATUSES:
            return validation_error(
                f"status must be one of {sorted(VALID_STATUSES)}.", "status"
            )
        clauses.append("status = ?")
        params.append(status)

    for query_name, column in (
        ("reportId", "report_id"),
        ("restroomId", "restroom_id"),
    ):
        value, error = parse_integer_query(query_name, None, 1)
        if error:
            return error
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)

    limit, error = parse_integer_query("limit", 100, 1, MAX_PAGE_SIZE)
    if error:
        return error
    offset, error = parse_integer_query("offset", 0, 0)
    if error:
        return error

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM work_orders
            {where_clause}
            ORDER BY created_at DESC, work_order_id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return jsonify([row_to_work_order(row) for row in rows])


@app.route("/work-orders", methods=["POST"])
def create_work_order():
    data, error, status_code = parse_json_object()
    if error:
        return error, status_code

    report_id = data.get("reportId")
    if isinstance(report_id, bool) or not isinstance(report_id, int) or report_id <= 0:
        return validation_error("reportId must be a positive integer.", "reportId")

    priority = data.get("priority", "MEDIUM")
    if not isinstance(priority, str) or priority.strip().upper() not in VALID_PRIORITIES:
        return validation_error(
            f"priority must be one of {sorted(VALID_PRIORITIES)}.", "priority"
        )
    priority = priority.strip().upper()

    report, error, status_code = report_for_work_order(report_id)
    if error:
        return error, status_code

    title = data.get("title")
    if title is None:
        title = f"Follow up: {report.get('reportType', 'visitor report')}"
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > MAX_TITLE_LENGTH:
        return validation_error(
            f"title must contain 1 to {MAX_TITLE_LENGTH} characters.", "title"
        )

    description = data.get("description", report.get("description", ""))
    if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_LENGTH:
        return validation_error(
            f"description must be at most {MAX_DESCRIPTION_LENGTH} characters.",
            "description",
        )

    assigned_to = data.get("assignedTo")
    if assigned_to is not None and (
        not isinstance(assigned_to, str)
        or not assigned_to.strip()
        or len(assigned_to.strip()) > MAX_ASSIGNEE_LENGTH
    ):
        return validation_error(
            f"assignedTo must be null or contain 1 to {MAX_ASSIGNEE_LENGTH} characters.",
            "assignedTo",
        )

    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO work_orders (
                    report_id, restroom_id, restroom_name, title, description,
                    priority, status, assigned_to, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
                """,
                (
                    report_id,
                    report["restroomId"],
                    report["restroomName"],
                    title.strip(),
                    description.strip(),
                    priority,
                    assigned_to.strip() if isinstance(assigned_to, str) else None,
                    now,
                    now,
                ),
            )
            work_order_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO work_order_events (
                    work_order_id, event_type, field, old_value, new_value, occurred_at
                ) VALUES (?, 'CREATED', NULL, NULL, ?, ?)
                """,
                (work_order_id, f"Report {report_id}", now),
            )
            row = connection.execute(
                "SELECT * FROM work_orders WHERE work_order_id = ?",
                (work_order_id,),
            ).fetchone()
    except sqlite3.IntegrityError:
        return make_error(
            "WORK_ORDER_ALREADY_EXISTS",
            f"A maintenance work order already exists for report {report_id}.",
        ), 409
    return jsonify(row_to_work_order(row)), 201


@app.route("/work-orders/<int:work_order_id>", methods=["GET"])
def get_work_order(work_order_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM work_orders WHERE work_order_id = ?",
            (work_order_id,),
        ).fetchone()
    if row is None:
        return make_error("WORK_ORDER_NOT_FOUND", "The work order was not found."), 404
    return jsonify(row_to_work_order(row))


@app.route("/work-orders/<int:work_order_id>", methods=["PUT"])
def update_work_order(work_order_id):
    data, error, status_code = parse_json_object()
    if error:
        return error, status_code
    if not data:
        return validation_error("At least one work order field is required.", "body")
    unexpected_fields = set(data) - set(EDITABLE_FIELDS)
    if unexpected_fields:
        field = sorted(unexpected_fields)[0]
        return validation_error(f"{field} cannot be updated.", field)

    updates = {}
    for field in EDITABLE_FIELDS:
        if field not in data:
            continue
        value = data[field]
        column, maximum_length = EDITABLE_FIELDS[field]
        if field in {"priority", "status"}:
            allowed = VALID_PRIORITIES if field == "priority" else VALID_STATUSES
            if not isinstance(value, str) or value.strip().upper() not in allowed:
                return validation_error(
                    f"{field} must be one of {sorted(allowed)}.", field
                )
            value = value.strip().upper()
        elif field == "assignedTo" and value is None:
            pass
        elif field == "description":
            if not isinstance(value, str) or len(value) > MAX_DESCRIPTION_LENGTH:
                return validation_error(f"{field} is invalid.", field)
            value = value.strip()
        elif (
            not isinstance(value, str)
            or not value.strip()
            or (maximum_length is not None and len(value.strip()) > maximum_length)
        ):
            return validation_error(f"{field} is invalid.", field)
        elif isinstance(value, str):
            value = value.strip()
        updates[column] = value

    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM work_orders WHERE work_order_id = ?",
            (work_order_id,),
        ).fetchone()
        if row is None:
            return make_error("WORK_ORDER_NOT_FOUND", "The work order was not found."), 404

        changes = []
        for column, new_value in updates.items():
            old_value = row[column]
            if old_value != new_value:
                changes.append((column, old_value, new_value))
        if changes:
            assignments = ", ".join(f"{column} = ?" for column, _, _ in changes)
            values = [value for _, _, value in changes]
            connection.execute(
                f"UPDATE work_orders SET {assignments}, updated_at = ? WHERE work_order_id = ?",
                [*values, now, work_order_id],
            )
            for column, old_value, new_value in changes:
                event_type = {
                    "status": "STATUS_CHANGED",
                    "assigned_to": "ASSIGNMENT_CHANGED",
                    "priority": "PRIORITY_CHANGED",
                }.get(column, "DETAILS_CHANGED")
                connection.execute(
                    """
                    INSERT INTO work_order_events (
                        work_order_id, event_type, field, old_value, new_value, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        work_order_id,
                        event_type,
                        column,
                        old_value,
                        new_value,
                        now,
                    ),
                )
        updated = connection.execute(
            "SELECT * FROM work_orders WHERE work_order_id = ?",
            (work_order_id,),
        ).fetchone()
    return jsonify(row_to_work_order(updated))


@app.route("/work-orders/<int:work_order_id>/history", methods=["GET"])
def get_work_order_history(work_order_id):
    with get_connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM work_orders WHERE work_order_id = ?",
            (work_order_id,),
        ).fetchone()
        if exists is None:
            return make_error("WORK_ORDER_NOT_FOUND", "The work order was not found."), 404
        rows = connection.execute(
            """
            SELECT event_id, event_type, field, old_value, new_value, occurred_at
            FROM work_order_events
            WHERE work_order_id = ?
            ORDER BY event_id
            """,
            (work_order_id,),
        ).fetchall()
    return jsonify([
        {
            "eventId": row["event_id"],
            "eventType": row["event_type"],
            "field": row["field"],
            "oldValue": row["old_value"],
            "newValue": row["new_value"],
            "occurredAt": row["occurred_at"],
        }
        for row in rows
    ])


initialize_database()

if __name__ == "__main__":
    app.run(
        host=os.environ.get("SANIMAP_BIND_HOST", "127.0.0.1"),
        port=int(os.environ.get("SANIMAP_WORK_ORDERS_PORT", "5003")),
        debug=False,
    )
