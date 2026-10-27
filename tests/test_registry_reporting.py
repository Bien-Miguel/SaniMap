import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from services.service_a import App_ServiceA as registry
from services.service_b import App_ServiceB as reporting


class RegistryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "registry.db")
        registry.app.config.update(TESTING=True, DATABASE=self.database_path)
        registry.initialize_database(self.database_path)
        self.client = registry.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seed_data_uses_luneta_coordinates_and_integer_ids(self):
        response = self.client.get("/restrooms")
        self.assertEqual(response.status_code, 200)
        records = response.get_json()
        self.assertEqual([item["restroomId"] for item in records], [1, 2, 3, 4, 5])
        self.assertEqual(records[0]["latitude"], 14.5826)
        self.assertEqual(records[0]["longitude"], 120.9787)
        ocean_park, quirino, relief_map = records[2:]
        self.assertEqual(ocean_park["name"], "Manila Ocean Park Restroom")
        self.assertEqual(
            (ocean_park["latitude"], ocean_park["longitude"]), (14.5791, 120.9723)
        )
        self.assertEqual(ocean_park["operatingHours"], "10:00 - 20:00")
        self.assertTrue(ocean_park["pwdAccessible"])
        self.assertEqual(ocean_park["genderType"], "Unisex")
        self.assertEqual(
            ocean_park["amenities"],
            [
                "Air-conditioned",
                "Handwashing Station",
                "Soap",
                "Toilet Paper",
                "Bidet",
                "Flush Toilet",
            ],
        )
        self.assertEqual(quirino["name"], "Quirino Grandstand Comfort Room")
        self.assertEqual(
            (quirino["latitude"], quirino["longitude"]), (14.58, 120.9739)
        )
        self.assertEqual(quirino["operatingHours"], "06:00 - 22:00")
        self.assertTrue(quirino["pwdAccessible"])
        self.assertEqual(quirino["genderType"], "Unisex")
        self.assertEqual(quirino["status"], "open")
        self.assertEqual(
            quirino["amenities"],
            [
                "Handwashing Station",
                "Soap",
                "Toilet Paper",
                "Flush Toilet",
                "Wheelchair Ramp",
            ],
        )
        self.assertEqual(relief_map["name"], "Relief Map Comfort Room")
        self.assertEqual(
            (relief_map["latitude"], relief_map["longitude"]), (14.5835, 120.9798)
        )
        self.assertEqual(relief_map["operatingHours"], "06:00 - 20:00")
        self.assertTrue(relief_map["pwdAccessible"])
        self.assertEqual(relief_map["genderType"], "Unisex")
        self.assertEqual(relief_map["status"], "open")
        self.assertEqual(
            relief_map["amenities"],
            ["Handwashing Station", "Soap", "Flush Toilet"],
        )

    def test_seed_adds_missing_facilities_and_preserves_existing_status(self):
        with registry.app.app_context():
            with registry.get_connection() as connection:
                connection.execute(
                    """
                    UPDATE restrooms
                    SET latitude = ?, longitude = ?, pwd_accessible = ?, status = ?
                    WHERE name = ?
                    """,
                    (
                        14.5831,
                        120.9761,
                        0,
                        "closed",
                        "Quirino Grandstand Comfort Room",
                    ),
                )

        registry.initialize_database(self.database_path)
        records = self.client.get("/restrooms").get_json()
        quirino = next(
            item
            for item in records
            if item["name"] == "Quirino Grandstand Comfort Room"
        )
        self.assertEqual(
            (quirino["latitude"], quirino["longitude"]), (14.58, 120.9739)
        )
        self.assertTrue(quirino["pwdAccessible"])
        self.assertEqual(quirino["status"], "closed")
        self.assertEqual(len(records), 5)

    def test_seed_renames_legacy_ocean_park_entry_without_duplicating_it(self):
        with registry.app.app_context():
            with registry.get_connection() as connection:
                connection.execute(
                    """
                    UPDATE restrooms
                    SET name = ?, latitude = ?, longitude = ?
                    WHERE name = ?
                    """,
                    (
                        "Manila Ocean Park Comfort Room",
                        14.5794,
                        120.9732,
                        "Manila Ocean Park Restroom",
                    ),
                )

        registry.initialize_database(self.database_path)
        records = self.client.get("/restrooms").get_json()
        ocean_park = [
            item for item in records if item["name"] == "Manila Ocean Park Restroom"
        ]
        self.assertEqual(len(ocean_park), 1)
        self.assertEqual(
            (ocean_park[0]["latitude"], ocean_park[0]["longitude"]),
            (14.5791, 120.9723),
        )
        self.assertFalse(
            any(item["name"] == "Manila Ocean Park Comfort Room" for item in records)
        )
        self.assertEqual(len(records), 5)

    def test_records_remain_after_database_reinitialization(self):
        created = self.client.post(
            "/restrooms",
            json={
                "name": "Persistent Test Restroom",
                "latitude": 14.582,
                "longitude": 120.979,
                "operatingHours": "24/7",
                "pwdAccessible": True,
                "genderType": "Unisex",
                "amenities": ["Soap"],
                "status": "open",
            },
        )
        restroom_id = created.get_json()["restroomId"]

        registry.initialize_database(self.database_path)
        response = self.client.get(f"/restrooms/{restroom_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["name"], "Persistent Test Restroom")

    def test_get_restroom_supports_xml_and_accept_parameters(self):
        response = self.client.get(
            "/restrooms/1",
            headers={"Accept": "application/xml, application/json;q=0.5"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/xml")
        self.assertIn(b"<restroomId>1</restroomId>", response.data)

    def test_create_restroom_persists_and_rejects_invalid_input(self):
        payload = {
            "name": "Test Restroom",
            "latitude": 14.582,
            "longitude": 120.979,
            "operatingHours": "24/7",
            "pwdAccessible": True,
            "genderType": "Unisex",
            "amenities": ["Soap"],
            "status": "open",
        }
        response = self.client.post("/restrooms", json=payload)
        self.assertEqual(response.status_code, 201)
        restroom_id = response.get_json()["restroomId"]

        with registry.app.test_request_context():
            with registry.get_connection() as connection:
                saved = connection.execute(
                    "SELECT name FROM restrooms WHERE restroom_id = ?",
                    (restroom_id,),
                ).fetchone()
        self.assertEqual(saved["name"], "Test Restroom")

        payload["latitude"] = 120
        invalid = self.client.post("/restrooms", json=payload)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()["error"], "VALIDATION_ERROR")

    def test_status_update_and_structured_not_found(self):
        updated = self.client.put(
            "/restrooms/1/status",
            json={"status": "closed"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["status"], "closed")

        invalid = self.client.put(
            "/restrooms/1/status",
            json={"status": "available"},
        )
        self.assertEqual(invalid.status_code, 400)

        missing = self.client.put(
            "/restrooms/999/status",
            json={"status": "closed"},
        )
        self.assertEqual(missing.status_code, 404)

    def test_malformed_json_and_xml_are_structured_errors(self):
        malformed_json = self.client.post(
            "/restrooms",
            data="{",
            content_type="application/json",
        )
        malformed_xml = self.client.post(
            "/restrooms",
            data="<restroom>",
            content_type="application/xml",
        )
        self.assertEqual(malformed_json.status_code, 400)
        self.assertEqual(malformed_json.get_json()["error"], "MALFORMED_JSON")
        self.assertEqual(malformed_xml.status_code, 400)
        self.assertEqual(malformed_xml.get_json()["error"], "MALFORMED_XML")


class ReportingServiceTests(unittest.TestCase):
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
            "restroomId": 1,
            "name": "Rizal Monument Comfort Room",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_report_validates_registry_and_persists_timestamp(self):
        payload = {
            "restroomId": 1,
            "reportType": "damaged_fixture",
            "description": "Broken tap",
        }
        with patch.object(
            reporting.requests,
            "get",
            return_value=self.registry_response,
        ) as registry_get:
            response = self.client.post("/feedback", json=payload)

        self.assertEqual(response.status_code, 201)
        report = response.get_json()
        self.assertEqual(report["reportType"], "DAMAGED_FIXTURE")
        self.assertTrue(report["createdAt"].endswith("+00:00"))
        registry_get.assert_called_once()

        status_response = self.client.get(
            f"/feedback/reports/{report['reportId']}"
        )
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.get_json()["reportId"], report["reportId"])

        reporting.initialize_database(self.database_path)
        persisted = self.client.get(
            f"/feedback/reports/{report['reportId']}"
        )
        self.assertEqual(persisted.status_code, 200)
        self.assertEqual(persisted.get_json()["description"], "Broken tap")

    def test_invalid_report_type_and_malformed_payload_are_rejected(self):
        invalid_type = self.client.post(
            "/feedback",
            json={"restroomId": 1, "reportType": "not-a-type"},
        )
        malformed_json = self.client.post(
            "/feedback",
            data="{",
            content_type="application/json",
        )
        malformed_xml = self.client.post(
            "/feedback",
            data="<feedback>",
            content_type="application/xml",
        )
        self.assertEqual(invalid_type.status_code, 400)
        self.assertEqual(malformed_json.get_json()["error"], "MALFORMED_JSON")
        self.assertEqual(malformed_xml.get_json()["error"], "MALFORMED_XML")

    def test_unknown_restroom_and_unavailable_registry_do_not_create_reports(self):
        not_found = Mock()
        not_found.status_code = 404
        with patch.object(reporting.requests, "get", return_value=not_found):
            response = self.client.post(
                "/feedback",
                json={"restroomId": 999, "reportType": "OTHER"},
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "RESTROOM_NOT_FOUND")

        with patch.object(
            reporting.requests,
            "get",
            side_effect=reporting.requests.exceptions.ConnectionError,
        ):
            unavailable = self.client.post(
                "/feedback",
                json={"restroomId": 1, "reportType": "OTHER"},
            )
        self.assertEqual(unavailable.status_code, 503)

        with reporting.app.test_request_context():
            with reporting.get_connection() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM reports WHERE report_id != 501"
                ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_report_list_supports_xml_and_status_lookup_not_found(self):
        response = self.client.get(
            "/feedback/1",
            headers={"Accept": "application/xml, application/json;q=0.5"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/xml")
        self.assertIn(b"<reportId>501</reportId>", response.data)

        missing = self.client.get("/feedback/reports/99999")
        self.assertEqual(missing.status_code, 404)

    def test_demo_report_uses_an_integer_registry_id(self):
        with reporting.app.test_request_context():
            with reporting.get_connection() as connection:
                row = connection.execute(
                    "SELECT restroom_id FROM reports WHERE report_id = 501"
                ).fetchone()
        self.assertEqual(row["restroom_id"], 1)


if __name__ == "__main__":
    unittest.main()
