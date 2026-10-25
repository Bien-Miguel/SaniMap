"""Tests for the staff report endpoints, request limits and gateway hardening."""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from services.service_a import App_ServiceA as registry
from services.service_b import App_ServiceB as reporting
from tests.test_gateway import (
    GatewayTestCase,
    bearer,
    fake_backend_response,
    make_token,
)


class ReportingStaffEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "reporting.db")
        reporting.app.config.update(
            TESTING=True,
            DATABASE=self.database_path,
            REGISTRY_URL="http://registry.test",
        )
        reporting.initialize_database(self.database_path)
        self.client = reporting.app.test_client()
        self.registry_response = Mock()
        self.registry_response.status_code = 200
        self.registry_response.json.return_value = {
            "restroomId": 2,
            "name": "Children's Playground Comfort Room",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def submit(self, restroom_id=2, report_type="OTHER", description="test"):
        with patch.object(
            reporting.requests, "get", return_value=self.registry_response
        ):
            return self.client.post(
                "/feedback",
                json={
                    "restroomId": restroom_id,
                    "reportType": report_type,
                    "description": description,
                },
            )

    def test_list_returns_all_reports_newest_first(self):
        first = self.submit(description="first").get_json()
        second = self.submit(description="second").get_json()

        response = self.client.get("/feedback")
        self.assertEqual(response.status_code, 200)
        ids = [item["reportId"] for item in response.get_json()]
        self.assertEqual(ids[:2], [second["reportId"], first["reportId"]])
        self.assertIn(501, ids)  # the seeded demo report is included

    def test_list_filters_by_status_and_restroom(self):
        report = self.submit().get_json()
        self.client.put(
            f"/feedback/reports/{report['reportId']}/status",
            json={"status": "RESOLVED"},
        )

        resolved = self.client.get("/feedback?status=resolved").get_json()
        self.assertEqual(
            [item["reportId"] for item in resolved], [report["reportId"]]
        )

        for_restroom_two = self.client.get(
            "/feedback?restroomId=2"
        ).get_json()
        self.assertTrue(
            all(item["restroomId"] == 2 for item in for_restroom_two)
        )

    def test_list_is_200_with_empty_array_when_nothing_matches(self):
        response = self.client.get("/feedback?restroomId=999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_list_rejects_invalid_filters(self):
        for query in (
            "status=DONE",
            "restroomId=abc",
            "restroomId=0",
            "limit=x",
            "limit=0",
            "limit=201",
            "offset=-1",
        ):
            with self.subTest(query=query):
                response = self.client.get(f"/feedback?{query}")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error"], "VALIDATION_ERROR"
                )

    def test_list_pagination(self):
        for index in range(3):
            self.submit(description=f"r{index}")
        page = self.client.get("/feedback?limit=2&offset=1").get_json()
        self.assertEqual(len(page), 2)

    def test_status_update_round_trip_and_case_insensitive(self):
        report = self.submit().get_json()
        url = f"/feedback/reports/{report['reportId']}/status"

        resolved = self.client.put(url, json={"status": "resolved"})
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.get_json()["status"], "RESOLVED")

        reopened = self.client.put(url, json={"status": "PENDING"})
        self.assertEqual(reopened.get_json()["status"], "PENDING")

        stored = self.client.get(
            f"/feedback/reports/{report['reportId']}"
        ).get_json()
        self.assertEqual(stored["status"], "PENDING")

    def test_status_update_rejects_bad_input(self):
        report = self.submit().get_json()
        url = f"/feedback/reports/{report['reportId']}/status"

        for body in (
            {"status": "DONE"},
            {"status": 5},
            {},
            {"status": None},
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.client.put(url, json=body).status_code, 400
                )

        self.assertEqual(
            self.client.put(
                url, data="not json", content_type="application/json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.put(
                url, data="x", content_type="text/plain"
            ).status_code,
            415,
        )

    def test_status_update_unknown_report_is_404(self):
        response = self.client.put(
            "/feedback/reports/99999/status", json={"status": "RESOLVED"}
        )
        self.assertEqual(response.status_code, 404)

    def test_description_length_is_capped(self):
        ok = self.submit(description="x" * 1000)
        self.assertEqual(ok.status_code, 201)

        too_long = self.submit(description="x" * 1001)
        self.assertEqual(too_long.status_code, 400)
        self.assertEqual(too_long.get_json()["field"], "description")


class RegistryLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "registry.db")
        registry.app.config.update(TESTING=True, DATABASE=self.database_path)
        registry.initialize_database(self.database_path)
        self.client = registry.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def payload(self, **changes):
        data = {
            "name": "Limit Test Comfort Room",
            "latitude": 14.582,
            "longitude": 120.979,
            "operatingHours": "06:00-20:00",
            "pwdAccessible": True,
            "genderType": "Unisex",
            "amenities": ["Soap"],
            "status": "open",
        }
        data.update(changes)
        return data

    def test_normal_record_still_accepted(self):
        self.assertEqual(
            self.client.post("/restrooms", json=self.payload()).status_code, 201
        )

    def test_oversized_fields_are_rejected(self):
        for changes in (
            {"name": "n" * 121},
            {"operatingHours": "h" * 41},
            {"genderType": "g" * 31},
            {"amenities": ["a"] * 21},
            {"amenities": ["a" * 61]},
        ):
            with self.subTest(field=list(changes)[0]):
                response = self.client.post(
                    "/restrooms", json=self.payload(**changes)
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error"], "VALIDATION_ERROR"
                )


class GatewayStaffRouteTests(GatewayTestCase):
    def test_list_reports_requires_staff(self):
        self.assertEqual(self.client.get("/feedback").status_code, 401)
        self.mock_request.assert_not_called()

        visitor = bearer(make_token("visitor"))
        self.assertEqual(
            self.client.get("/feedback", headers=visitor).status_code, 403
        )
        self.mock_request.assert_not_called()

    def test_list_reports_is_forwarded_for_staff_with_query_string(self):
        for headers in (self.admin, self.manager):
            self.mock_request.reset_mock()
            self.mock_request.return_value = fake_backend_response(body=b"[]")
            response = self.client.get(
                "/feedback?status=PENDING&limit=5", headers=headers
            )
            self.assertEqual(response.status_code, 200)
            url = self.mock_request.call_args.args[1]
            self.assertTrue(url.endswith("/feedback?status=PENDING&limit=5"))

    def test_posting_a_report_is_still_public(self):
        response = self.client.post(
            "/feedback", data="{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)  # forwarded (mock backend)

    def test_report_status_update_requires_staff(self):
        url = "/feedback/reports/501/status"
        body = dict(data='{"status": "RESOLVED"}', content_type="application/json")

        self.assertEqual(self.client.put(url, **body).status_code, 401)

        visitor = bearer(make_token("visitor"))
        self.assertEqual(
            self.client.put(url, headers=visitor, **body).status_code, 403
        )
        self.mock_request.assert_not_called()

        for headers in (self.admin, self.manager):
            self.assertEqual(
                self.client.put(url, headers=headers, **body).status_code, 200
            )

    def test_non_numeric_report_id_is_not_forwarded(self):
        response = self.client.put(
            "/feedback/reports/abc/status",
            headers=self.admin,
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.mock_request.assert_not_called()

    def test_oversized_body_is_rejected_before_forwarding(self):
        response = self.client.post(
            "/feedback",
            data="x" * (17 * 1024),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            response.get_json()["error"], "PAYLOAD_TOO_LARGE"
        )
        self.mock_request.assert_not_called()

    def test_unexpected_transport_error_is_a_json_502(self):
        self.mock_request.side_effect = requests.exceptions.ChunkedEncodingError(
            "boom"
        )
        response = self.client.get("/restrooms")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["error"], "BAD_GATEWAY")

    def test_security_headers_are_present(self):
        response = self.client.get("/health")
        self.assertEqual(
            response.headers["X-Content-Type-Options"], "nosniff"
        )
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(
            response.headers["Referrer-Policy"], "no-referrer"
        )


if __name__ == "__main__":
    unittest.main()