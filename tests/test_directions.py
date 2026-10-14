import copy
import logging
import os
import secrets
import unittest
from unittest.mock import Mock, patch

import requests

from gateway import App_Gateway as gateway

TEST_ORS_KEY = "test-ors-key-" + secrets.token_hex(16)  # random per run, never committed
TEST_BASE_URL = "https://ors.example.test/openrouteservice/v2"

ORS_SAMPLE = {
    "type": "FeatureCollection",
    "metadata": {"attribution": "openrouteservice.org | OpenStreetMap contributors"},
    "bbox": [120.9787, 14.5826, 120.9795, 14.5838],
    "features": [{
        "type": "Feature",
        "properties": {
            "segments": [{
                "distance": 320.5,
                "duration": 230.8,
                "steps": [
                    {"distance": 200.0, "duration": 144.0, "instruction": "Head north"},
                    {"distance": 120.5, "duration": 86.8, "instruction": "Arrive at your destination"},
                ],
            }],
            "way_points": [0, 3],
            "summary": {"distance": 320.5, "duration": 230.8},
        },
        # ORS order is [longitude, latitude]
        "geometry": {
            "type": "LineString",
            "coordinates": [[120.9787, 14.5826], [120.9789, 14.5830],
                            [120.9791, 14.5834], [120.9795, 14.5838]],
        },
    }],
}

VALID_QUERY = "start_lat=14.5826&start_lng=120.9787&end_lat=14.5838&end_lng=120.9795"


def ors_response(status=200, payload=None, bad_json=False):
    resp = Mock()
    resp.status_code = status
    if bad_json:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = copy.deepcopy(ORS_SAMPLE if payload is None else payload)
    return resp


def backend_ok():
    """A plain backend response, for the routes that are forwarded rather than transformed."""
    resp = Mock()
    resp.status_code = 200
    resp.content = b'{"ok": true}'
    resp.headers = {"Content-Type": "application/json"}
    return resp


class DirectionsTestCase(unittest.TestCase):
    def setUp(self):
        gateway.app.config["TESTING"] = True
        self.client = gateway.app.test_client()
        env = patch.dict(os.environ, {"ORS_API_KEY": TEST_ORS_KEY, "ORS_BASE_URL": TEST_BASE_URL})
        env.start()
        self.addCleanup(env.stop)
        req = patch("gateway.App_Gateway.requests.request")
        self.mock_request = req.start()
        self.addCleanup(req.stop)
        self.mock_request.return_value = ors_response()
        gateway.reset_rate_limits()
        self.addCleanup(gateway.reset_rate_limits)
        # Keep expected warning messages out of the test output.
        for quiet in (patch.object(gateway.app.logger, "handlers", [logging.NullHandler()]),
                      patch.object(gateway.app.logger, "propagate", False)):
            quiet.start()
            self.addCleanup(quiet.stop)

    def get(self, query=VALID_QUERY, **kwargs):
        return self.client.get(f"/directions?{query}", **kwargs)

    def assert_clean(self, response):
        """No secret or internal detail may ever reach the client."""
        text = response.get_data(as_text=True) + str(dict(response.headers))
        self.assertNotIn(TEST_ORS_KEY, text)
        self.assertNotIn("ors.example.test", text)


class DirectionsSuccessTests(DirectionsTestCase):
    def test_valid_request_returns_leaflet_ready_schema(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["profile"], "foot-walking")
        self.assertEqual(body["distance_meters"], 320.5)
        self.assertEqual(body["duration_seconds"], 230.8)
        self.assertEqual(body["start"], {"lat": 14.5826, "lng": 120.9787})
        self.assertEqual(body["end"], {"lat": 14.5838, "lng": 120.9795})
        self.assertEqual(body["attribution"], "openrouteservice.org | OpenStreetMap contributors")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assert_clean(response)

    def test_path_is_flipped_from_lng_lat_to_lat_lng_exactly_once(self):
        body = self.get().get_json()

        self.assertEqual(body["path"][0], [14.5826, 120.9787])
        self.assertEqual(body["path"][-1], [14.5838, 120.9795])
        self.assertEqual(len(body["path"]), 4)
        for lat, lng in body["path"]:
            self.assertTrue(-90 <= lat <= 90)
        self.assertEqual(body["bounds"], [[14.5826, 120.9787], [14.5838, 120.9795]])

    def test_upstream_request_uses_lng_lat_order_header_auth_and_walking_profile(self):
        self.get()

        args, kwargs = self.mock_request.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(
            args[1],
            f"{TEST_BASE_URL}/directions/foot-walking"
            "?start=120.978700,14.582600&end=120.979500,14.583800",
        )
        self.assertEqual(kwargs["headers"]["Authorization"], TEST_ORS_KEY)
        self.assertNotIn(TEST_ORS_KEY, args[1])  # key never goes in the URL
        self.assertEqual(kwargs["timeout"], gateway.ORS_TIMEOUT_SECONDS)

    def test_steps_are_mapped(self):
        steps = self.get().get_json()["steps"]

        self.assertEqual(steps[0], {
            "instruction": "Head north", "distance_meters": 200.0, "duration_seconds": 144.0,
        })
        self.assertEqual(len(steps), 2)

    def test_elevation_values_and_missing_steps_are_tolerated(self):
        payload = copy.deepcopy(ORS_SAMPLE)
        payload["features"][0]["geometry"]["coordinates"] = [
            [120.9787, 14.5826, 5.0], [120.9795, 14.5838, 6.0]]
        del payload["features"][0]["properties"]["segments"]
        self.mock_request.return_value = ors_response(payload=payload)

        body = self.get().get_json()

        self.assertEqual(body["path"], [[14.5826, 120.9787], [14.5838, 120.9795]])
        self.assertEqual(body["steps"], [])

    def test_profile_defaults_to_walking_and_accepts_explicit_walking(self):
        self.get(VALID_QUERY + "&profile=foot-walking")
        self.assertIn("/directions/foot-walking?", self.mock_request.call_args[0][1])

    def test_directions_is_public_and_ignores_unverified_tokens(self):
        self.assertEqual(self.get().status_code, 200)
        self.assertEqual(
            self.get(headers={"Authorization": "Bearer garbage"}).status_code, 200)


class DirectionsValidationTests(DirectionsTestCase):
    def assert_validation_error(self, query, field):
        self.mock_request.reset_mock()
        response = self.get(query)
        self.assertEqual(response.status_code, 400, query)
        body = response.get_json()
        self.assertEqual(body["error"], "VALIDATION_ERROR")
        self.assertEqual(body["field"], field)
        self.mock_request.assert_not_called()

    def test_each_required_parameter_is_enforced(self):
        full = {"start_lat": "14.5826", "start_lng": "120.9787",
                "end_lat": "14.5838", "end_lng": "120.9795"}
        for missing in full:
            with self.subTest(missing=missing):
                query = "&".join(f"{k}={v}" for k, v in full.items() if k != missing)
                self.assert_validation_error(query, missing)

    def test_non_numeric_and_non_finite_values_are_rejected(self):
        for bad in ["abc", "14.58abc", "nan", "inf", "-inf", "", "1e999"]:
            with self.subTest(value=bad):
                self.assert_validation_error(
                    f"start_lat={bad}&start_lng=120.9787&end_lat=14.5838&end_lng=120.9795",
                    "start_lat")

    def test_out_of_range_coordinates_are_rejected(self):
        self.assert_validation_error(
            "start_lat=91&start_lng=120.9787&end_lat=14.5838&end_lng=120.9795", "start_lat")
        self.assert_validation_error(
            "start_lat=14.5826&start_lng=181&end_lat=14.5838&end_lng=120.9795", "start_lng")
        self.assert_validation_error(
            "start_lat=14.5826&start_lng=120.9787&end_lat=-90.5&end_lng=120.9795", "end_lat")

    def test_swapped_latitude_and_longitude_are_caught(self):
        # Longitude (120.98) sent in the latitude field is impossible and must not reach ORS.
        self.assert_validation_error(
            "start_lat=120.9787&start_lng=14.5826&end_lat=120.9795&end_lng=14.5838", "start_lat")

    def test_unsupported_profiles_are_rejected(self):
        for profile in ["driving-car", "cycling-regular", "wheelchair", "../admin", ""]:
            with self.subTest(profile=profile):
                self.assert_validation_error(VALID_QUERY + f"&profile={profile}", "profile")


class DirectionsUpstreamFailureTests(DirectionsTestCase):
    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.get_json()["error"], code)
        self.assert_clean(response)

    def test_unroutable_points_return_422(self):
        for upstream in (400, 404):
            with self.subTest(upstream=upstream):
                self.mock_request.return_value = ors_response(upstream)
                self.assert_error(self.get(), 422, "ROUTE_NOT_FOUND")

    def test_auth_failures_are_hidden_behind_a_generic_502(self):
        for upstream in (401, 403):
            with self.subTest(upstream=upstream):
                self.mock_request.return_value = ors_response(upstream)
                self.assert_error(self.get(), 502, "ROUTING_SERVICE_ERROR")

    def test_upstream_server_errors_return_502(self):
        for upstream in (500, 502, 503):
            with self.subTest(upstream=upstream):
                self.mock_request.return_value = ors_response(upstream)
                self.assert_error(self.get(), 502, "ROUTING_SERVICE_ERROR")

    def test_upstream_rate_limit_returns_503_with_retry_after(self):
        self.mock_request.return_value = ors_response(429)

        response = self.get()

        self.assert_error(response, 503, "ROUTING_BUSY")
        self.assertEqual(response.headers["Retry-After"], "60")

    def test_timeout_returns_504(self):
        self.mock_request.side_effect = requests.exceptions.Timeout()
        self.assert_error(self.get(), 504, "ROUTING_TIMEOUT")

    def test_connect_timeout_is_treated_as_a_timeout(self):
        self.mock_request.side_effect = requests.exceptions.ConnectTimeout()
        self.assert_error(self.get(), 504, "ROUTING_TIMEOUT")

    def test_connection_error_returns_502(self):
        self.mock_request.side_effect = requests.exceptions.ConnectionError(
            f"could not connect to {TEST_BASE_URL}?start=120.9787,14.5826")
        self.assert_error(self.get(), 502, "ROUTING_SERVICE_ERROR")

    def test_malformed_json_returns_502(self):
        self.mock_request.return_value = ors_response(bad_json=True)
        self.assert_error(self.get(), 502, "ROUTING_BAD_RESPONSE")

    def test_unexpected_structures_return_502(self):
        broken = {}
        no_features = copy.deepcopy(ORS_SAMPLE); no_features["features"] = []
        broken["no_features"] = no_features
        no_summary = copy.deepcopy(ORS_SAMPLE)
        del no_summary["features"][0]["properties"]["summary"]
        broken["no_summary"] = no_summary
        null_distance = copy.deepcopy(ORS_SAMPLE)
        null_distance["features"][0]["properties"]["summary"]["distance"] = None
        broken["null_distance"] = null_distance
        negative = copy.deepcopy(ORS_SAMPLE)
        negative["features"][0]["properties"]["summary"]["duration"] = -5
        broken["negative_duration"] = negative
        one_point = copy.deepcopy(ORS_SAMPLE)
        one_point["features"][0]["geometry"]["coordinates"] = [[120.9787, 14.5826]]
        broken["one_point"] = one_point
        out_of_range = copy.deepcopy(ORS_SAMPLE)
        out_of_range["features"][0]["geometry"]["coordinates"] = [[14.5826, 120.9787], [14.5838, 120.9795]]
        broken["swapped_upstream_coordinates"] = out_of_range
        bad_point = copy.deepcopy(ORS_SAMPLE)
        bad_point["features"][0]["geometry"]["coordinates"] = [None, [1, 2]]
        broken["null_point"] = bad_point
        broken["list_payload"] = []
        broken["null_payload"] = None

        for name, payload in broken.items():
            with self.subTest(case=name):
                self.mock_request.return_value = ors_response(payload=payload)
                if payload is None:
                    self.mock_request.return_value.json.return_value = None
                self.assert_error(self.get(), 502, "ROUTING_BAD_RESPONSE")

    def test_failures_are_logged_without_key_url_or_coordinates(self):
        self.mock_request.side_effect = requests.exceptions.ConnectionError(
            f"failed {TEST_BASE_URL}/directions?start=120.9787,14.5826 key={TEST_ORS_KEY}")

        with self.assertLogs(gateway.app.logger, level="WARNING") as logs:
            self.get()

        output = "\n".join(logs.output)
        self.assertIn("ConnectionError", output)
        for secret in (TEST_ORS_KEY, "120.9787", "14.5826", "ors.example.test"):
            self.assertNotIn(secret, output)


class DirectionsConfigurationTests(DirectionsTestCase):
    def test_missing_key_fails_closed_without_calling_ors(self):
        with patch.dict(os.environ, {"ORS_API_KEY": ""}):
            response = self.get()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "ROUTING_NOT_CONFIGURED")
        self.mock_request.assert_not_called()

    def test_key_is_never_sent_over_plain_http(self):
        with patch.dict(os.environ, {"ORS_BASE_URL": "http://api.example.com/v2"}):
            response = self.get()

        self.assertEqual(response.status_code, 503)
        self.mock_request.assert_not_called()

    def test_local_test_server_is_allowed_over_http(self):
        with patch.dict(os.environ, {"ORS_BASE_URL": "http://127.0.0.1:5999/v2"}):
            self.assertEqual(self.get().status_code, 200)

    def test_default_base_url_is_the_current_heigit_host(self):
        with patch.dict(os.environ):
            os.environ.pop("ORS_BASE_URL", None)
            self.get()

        self.assertTrue(self.mock_request.call_args[0][1].startswith(
            "https://api.heigit.org/openrouteservice/v2/directions/foot-walking?"))


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RateLimitTests(DirectionsTestCase):
    def test_directions_per_client_limit_returns_429_with_retry_after(self):
        per_client = gateway.RATE_LIMITS["directions"][0]
        for _ in range(per_client):
            self.assertEqual(self.get().status_code, 200)

        response = self.get()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()["error"], "RATE_LIMITED")
        self.assertGreaterEqual(int(response.headers["Retry-After"]), 1)
        self.assertEqual(self.mock_request.call_count, per_client)  # blocked call never reached ORS

    def test_directions_global_limit_protects_the_ors_quota(self):
        overall = gateway.RATE_LIMITS["directions"][1]
        for index in range(overall):
            client_ip = f"10.0.{index // 10}.{index % 10}"  # 10 requests per client IP
            response = self.get(environ_overrides={"REMOTE_ADDR": client_ip})
            self.assertEqual(response.status_code, 200)

        response = self.get(environ_overrides={"REMOTE_ADDR": "10.9.9.9"})

        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.mock_request.call_count, overall)

    def test_one_client_cannot_block_another(self):
        for _ in range(gateway.RATE_LIMITS["directions"][0] + 1):
            self.get(environ_overrides={"REMOTE_ADDR": "10.1.1.1"})

        self.assertEqual(self.get(environ_overrides={"REMOTE_ADDR": "10.2.2.2"}).status_code, 200)

    def test_feedback_submissions_are_rate_limited(self):
        self.mock_request.return_value = backend_ok()
        limit = gateway.RATE_LIMITS["feedback"][0]
        for _ in range(limit):
            self.assertEqual(
                self.client.post("/feedback", data="{}", content_type="application/json").status_code,
                200)

        response = self.client.post("/feedback", data="{}", content_type="application/json")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.mock_request.call_count, limit)

    def test_window_expiry_allows_requests_again(self):
        clock = FakeClock()
        with patch.object(gateway.limiter, "clock", clock):
            for _ in range(gateway.RATE_LIMITS["directions"][0]):
                self.get()
            self.assertEqual(self.get().status_code, 429)

            clock.now += gateway.RATE_LIMIT_WINDOW_SECONDS + 1

            self.assertEqual(self.get().status_code, 200)

    def test_invalid_requests_still_count_toward_the_limit(self):
        for _ in range(gateway.RATE_LIMITS["directions"][0]):
            self.get("start_lat=abc")

        self.assertEqual(self.get().status_code, 429)

    def test_unlisted_routes_are_not_rate_limited(self):
        self.mock_request.return_value = backend_ok()
        for _ in range(50):
            self.assertEqual(self.client.get("/restrooms").status_code, 200)

    def test_forwarded_for_header_is_ignored_unless_proxies_are_trusted(self):
        for _ in range(gateway.RATE_LIMITS["directions"][0]):
            self.get(headers={"X-Forwarded-For": "1.2.3.4"})

        # A spoofed different address must NOT reset the limit.
        response = self.get(headers={"X-Forwarded-For": "5.6.7.8"})

        self.assertEqual(response.status_code, 429)


class LogPrivacyTests(unittest.TestCase):
    def log_line(self, line):
        with self.assertLogs("werkzeug", level="INFO") as logs:
            logging.getLogger("werkzeug").info(line)
        return logs.output[0]

    def test_access_logs_hide_query_strings(self):
        output = self.log_line(
            '127.0.0.1 - - [14/Oct/2026 10:22:24] '
            '"GET /directions?start_lat=14.5826&start_lng=120.9787&end_lat=14.5838 HTTP/1.1" 200 -')

        self.assertIn("GET /directions?[redacted] HTTP/1.1", output)
        for secret in ("14.5826", "120.9787", "start_lat"):
            self.assertNotIn(secret, output)
        self.assertIn("200", output)

    def test_paths_without_query_strings_are_unchanged(self):
        output = self.log_line('127.0.0.1 - - [x] "PUT /restrooms/1/status HTTP/1.1" 200 -')

        self.assertIn('"PUT /restrooms/1/status HTTP/1.1" 200', output)

    def test_other_routes_are_redacted_too(self):
        output = self.log_line('127.0.0.1 - - [x] "GET /restrooms?name=secret HTTP/1.1" 200 -')

        self.assertNotIn("secret", output)


class LimiterUnitTests(unittest.TestCase):
    def test_rejected_requests_do_not_consume_capacity(self):
        limiter = gateway.SlidingWindowLimiter(60, clock=FakeClock())

        self.assertEqual(limiter.allow([("client", 1), ("global", 5)]), (True, 0))
        allowed, retry_after = limiter.allow([("client", 1), ("global", 5)])

        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)
        # The blocked attempt must not have used up shared "global" capacity.
        self.assertEqual(len(limiter._hits["global"]), 1)

    def test_stale_keys_are_swept(self):
        clock = FakeClock()
        limiter = gateway.SlidingWindowLimiter(60, clock=clock)
        for index in range(100):
            limiter.allow([(f"client-{index}", 1)])
        clock.now += 120
        limiter._calls = 499  # next call triggers the periodic sweep

        limiter.allow([("fresh", 1)])

        self.assertEqual(list(limiter._hits), ["fresh"])


if __name__ == "__main__":
    unittest.main()