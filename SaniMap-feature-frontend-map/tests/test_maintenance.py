import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from services.service_c import App_ServiceC as maintenance


class MaintenanceServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "work_orders.db")
        maintenance.app.config.update(
            TESTING=True,
            DATABASE=self.database_path,
            REPORTING_URL="http://reporting.test",
        )
        maintenance.initialize_database(self.database_path)
        self.client = maintenance.app.test_client()
        self.report_response = Mock(status_code=200)
        self.report_response.json.return_value = {
            "reportId": 501,
            "restroomId": 1,
            "restroomName": "Rizal Monument Comfort Room",
            "reportType": "DAMAGED_FIXTURE",
            "description": "Broken tap",
            "status": "PENDING",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_work_order(self, payload=None):
        with patch.object(
            maintenance.requests,
            "get",
            return_value=self.report_response,
        ) as reporting_get:
            response = self.client.post(
                "/work-orders",
                json=payload or {"reportId": 501},
            )
        return response, reporting_get

    def test_create_work_order_validates_report_and_persists_creation_event(self):
        response, reporting_get = self.create_work_order(
            {"reportId": 501, "priority": "high", "assignedTo": "Facilities team"}
        )
        self.assertEqual(response.status_code, 201)
        work_order = response.get_json()
        self.assertEqual(work_order["reportId"], 501)
        self.assertEqual(work_order["restroomId"], 1)
        self.assertEqual(work_order["priority"], "HIGH")
        self.assertEqual(work_order["status"], "OPEN")
        self.assertEqual(work_order["assignedTo"], "Facilities team")
        self.assertEqual(work_order["description"], "Broken tap")
        reporting_get.assert_called_once_with(
            "http://reporting.test/feedback/reports/501",
            timeout=5,
        )

        history = self.client.get(
            f"/work-orders/{work_order['workOrderId']}/history"
        ).get_json()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["eventType"], "CREATED")

    def test_duplicate_report_cannot_create_a_second_work_order(self):
        first, _ = self.create_work_order()
        second, _ = self.create_work_order()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.get_json()["error"], "WORK_ORDER_ALREADY_EXISTS")

    def test_work_order_changes_are_recorded_in_history(self):
        created, _ = self.create_work_order()
        work_order_id = created.get_json()["workOrderId"]

        response = self.client.put(
            f"/work-orders/{work_order_id}",
            json={"status": "in_progress", "assignedTo": "Alex"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "IN_PROGRESS")
        self.assertEqual(response.get_json()["assignedTo"], "Alex")

        history = self.client.get(
            f"/work-orders/{work_order_id}/history"
        ).get_json()
        self.assertEqual(
            [event["eventType"] for event in history],
            ["CREATED", "STATUS_CHANGED", "ASSIGNMENT_CHANGED"],
        )
        self.assertEqual(history[1]["oldValue"], "OPEN")
        self.assertEqual(history[1]["newValue"], "IN_PROGRESS")

    def test_list_filters_and_not_found_responses(self):
        created, _ = self.create_work_order()
        work_order_id = created.get_json()["workOrderId"]

        self.client.put(f"/work-orders/{work_order_id}", json={"status": "COMPLETED"})
        completed = self.client.get("/work-orders?status=completed&restroomId=1")
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(len(completed.get_json()), 1)
        self.assertEqual(
            self.client.get("/work-orders?status=UNKNOWN").status_code,
            400,
        )
        self.assertEqual(self.client.get("/work-orders/999").status_code, 404)
        self.assertEqual(
            self.client.get("/work-orders/999/history").status_code,
            404,
        )

    def test_invalid_payloads_and_fields_are_rejected(self):
        bad_report_id = self.client.post("/work-orders", json={"reportId": True})
        bad_media_type = self.client.post(
            "/work-orders",
            data="{}",
            content_type="text/plain",
        )
        malformed_json = self.client.post(
            "/work-orders",
            data="{",
            content_type="application/json",
        )
        self.assertEqual(bad_report_id.status_code, 400)
        self.assertEqual(bad_media_type.status_code, 415)
        self.assertEqual(malformed_json.get_json()["error"], "MALFORMED_JSON")

        created, _ = self.create_work_order()
        update = self.client.put(
            f"/work-orders/{created.get_json()['workOrderId']}",
            json={"restroomId": 900},
        )
        self.assertEqual(update.status_code, 400)

    def test_unknown_or_unavailable_reporting_does_not_create_work_order(self):
        missing_report = Mock(status_code=404)
        with patch.object(
            maintenance.requests,
            "get",
            return_value=missing_report,
        ):
            missing = self.client.post("/work-orders", json={"reportId": 999})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json()["error"], "REPORT_NOT_FOUND")

        with patch.object(
            maintenance.requests,
            "get",
            side_effect=maintenance.requests.exceptions.ConnectionError,
        ):
            unavailable = self.client.post("/work-orders", json={"reportId": 501})
        self.assertEqual(unavailable.status_code, 503)

        with maintenance.app.test_request_context():
            with maintenance.get_connection() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM work_orders"
                ).fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
