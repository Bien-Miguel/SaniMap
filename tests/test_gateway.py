import os
import secrets
import time
import unittest
from unittest.mock import Mock, patch

import jwt
import requests

from gateway import App_Gateway as gateway

TEST_SECRET = secrets.token_urlsafe(48)  # random per run, never committed
TEST_ISSUER = "sanimap-test-issuer"
TEST_AUDIENCE = "sanimap-test-audience"
TEST_ENV = {
    "JWT_SECRET": TEST_SECRET,
    "JWT_ISSUER": TEST_ISSUER,
    "JWT_AUDIENCE": TEST_AUDIENCE,
}


def make_token(role="admin", secret=None, issuer=None, audience=None,
               expires_in=300, algorithm="HS256", extra=None, omit=()):
    now = int(time.time())
    claims = {
        "sub": "tester",
        "role": role,
        "iss": issuer or TEST_ISSUER,
        "aud": audience or TEST_AUDIENCE,
        "iat": now,
        "exp": now + expires_in,
    }
    if extra:
        claims.update(extra)
    for key in omit:
        claims.pop(key, None)
    return jwt.encode(claims, secret or TEST_SECRET, algorithm=algorithm)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def fake_backend_response(status=200, body=b'{"ok": true}', content_type="application/json"):
    resp = Mock()
    resp.status_code = status
    resp.content = body
    resp.headers = {"Content-Type": content_type}
    return resp


class GatewayTestCase(unittest.TestCase):
    def setUp(self):
        gateway.app.config["TESTING"] = True
        self.client = gateway.app.test_client()
        env_patch = patch.dict(os.environ, TEST_ENV)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        request_patch = patch("gateway.App_Gateway.requests.request")
        self.mock_request = request_patch.start()
        self.addCleanup(request_patch.stop)
        self.mock_request.return_value = fake_backend_response()
        self.admin = bearer(make_token("admin"))
        self.manager = bearer(make_token("park_manager"))


class GatewayForwardingTests(GatewayTestCase):
    def test_feedback_idempotency_key_is_forwarded_to_reporting(self):
        response = self.client.post(
            "/feedback",
            json={"restroomId": 1, "reportType": "OTHER"},
            headers={"Idempotency-Key": "report-attempt-123"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.mock_request.call_args.kwargs["headers"]["Idempotency-Key"],
            "report-attempt-123",
        )

    def test_put_status_reaches_registry_with_body_and_content_type(self):
        response = self.client.put(
            "/restrooms/1/status",
            data='{"status": "closed"}',
            content_type="application/json",
            headers=self.admin,
        )

        self.assertEqual(response.status_code, 200)
        args, kwargs = self.mock_request.call_args
        self.assertEqual(args[0], "PUT")
        self.assertEqual(args[1], "http://127.0.0.1:5001/restrooms/1/status")
        self.assertEqual(kwargs["data"], b'{"status": "closed"}')
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")

    def test_query_string_is_forwarded_unchanged(self):
        self.client.get("/restrooms?name=Rizal%20Monument&tag=a&tag=b&empty=")

        self.assertEqual(
            self.mock_request.call_args[0][1],
            "http://127.0.0.1:5001/restrooms?name=Rizal%20Monument&tag=a&tag=b&empty=",
        )

    def test_no_query_string_leaves_url_clean(self):
        self.client.get("/restrooms")

        self.assertEqual(
            self.mock_request.call_args[0][1], "http://127.0.0.1:5001/restrooms"
        )

    def test_backend_status_and_body_are_preserved(self):
        self.mock_request.return_value = fake_backend_response(
            404, b'{"error": "RESOURCE_NOT_FOUND"}'
        )

        response = self.client.put(
            "/restrooms/999/status",
            data='{"status": "open"}',
            content_type="application/json",
            headers=self.admin,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "RESOURCE_NOT_FOUND")

    def test_accept_header_is_forwarded(self):
        self.mock_request.return_value = fake_backend_response(
            body=b"<restrooms/>", content_type="application/xml"
        )

        response = self.client.get("/restrooms", headers={"Accept": "application/xml"})

        self.assertEqual(
            self.mock_request.call_args[1]["headers"]["Accept"], "application/xml"
        )
        self.assertEqual(response.content_type, "application/xml")

    def test_unsupported_methods_are_rejected_without_forwarding(self):
        response = self.client.delete("/restrooms/1/status", headers=self.admin)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.get_json()["error"], "METHOD_NOT_ALLOWED")
        self.mock_request.assert_not_called()

    def test_unknown_route_returns_json_404(self):
        response = self.client.get("/does-not-exist")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "NOT_FOUND")
        self.mock_request.assert_not_called()

    def test_non_numeric_ids_are_not_forwarded(self):
        response = self.client.get("/restrooms/abc")

        self.assertEqual(response.status_code, 404)
        self.mock_request.assert_not_called()

    def test_report_status_route_is_forwarded_to_reporting(self):
        self.client.get("/feedback/reports/7")

        self.assertEqual(
            self.mock_request.call_args[0][1], "http://127.0.0.1:5002/feedback/reports/7"
        )

    def test_backend_down_returns_503_json(self):
        self.mock_request.side_effect = requests.exceptions.ConnectionError()

        response = self.client.put(
            "/restrooms/1/status",
            data='{"status": "closed"}',
            content_type="application/json",
            headers=self.admin,
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "SERVICE_UNAVAILABLE")


class GatewayAuthenticationTests(GatewayTestCase):
    def put_status(self, headers=None):
        return self.client.put(
            "/restrooms/1/status",
            data='{"status": "closed"}',
            content_type="application/json",
            headers=headers or {},
        )

    def assert_rejected(self, response, status, error):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.get_json()["error"], error)
        self.mock_request.assert_not_called()

    def test_missing_token_is_401(self):
        response = self.put_status()
        self.assert_rejected(response, 401, "UNAUTHORIZED")
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_malformed_authorization_headers_are_401(self):
        for value in ["Bearer", "Bearer ", "Token abc", "abc", "Bearer a b"]:
            with self.subTest(header=value):
                self.mock_request.reset_mock()
                response = self.put_status({"Authorization": value})
                self.assert_rejected(response, 401, "UNAUTHORIZED")

    def test_garbage_token_is_401(self):
        self.assert_rejected(self.put_status(bearer("not-a-jwt")), 401, "UNAUTHORIZED")

    def test_wrong_signature_is_401(self):
        token = make_token("admin", secret=secrets.token_urlsafe(48))
        self.assert_rejected(self.put_status(bearer(token)), 401, "UNAUTHORIZED")

    def test_expired_token_is_401(self):
        token = make_token("admin", expires_in=-60)
        response = self.put_status(bearer(token))
        self.assert_rejected(response, 401, "UNAUTHORIZED")
        self.assertIn("expired", response.get_json()["message"].lower())

    def test_wrong_issuer_is_401(self):
        token = make_token("admin", issuer="someone-else")
        self.assert_rejected(self.put_status(bearer(token)), 401, "UNAUTHORIZED")

    def test_wrong_audience_is_401(self):
        token = make_token("admin", audience="another-api")
        self.assert_rejected(self.put_status(bearer(token)), 401, "UNAUTHORIZED")

    def test_token_without_expiry_is_401(self):
        token = make_token("admin", omit=("exp",))
        self.assert_rejected(self.put_status(bearer(token)), 401, "UNAUTHORIZED")

    def test_unsigned_alg_none_token_is_401(self):
        now = int(time.time())
        token = jwt.encode(
            {"role": "admin", "iss": TEST_ISSUER, "aud": TEST_AUDIENCE, "exp": now + 300},
            key=None,
            algorithm="none",
        )
        self.assert_rejected(self.put_status(bearer(token)), 401, "UNAUTHORIZED")

    def test_token_signed_with_other_hmac_algorithm_is_401(self):
        token = make_token("admin", algorithm="HS512")
        self.assert_rejected(self.put_status(bearer(token)), 401, "UNAUTHORIZED")

    def test_valid_admin_token_is_forwarded(self):
        response = self.put_status(self.admin)

        self.assertEqual(response.status_code, 200)
        self.mock_request.assert_called_once()

    def test_authorization_header_is_not_forwarded_to_backend(self):
        self.put_status(self.admin)

        forwarded = self.mock_request.call_args[1]["headers"]
        self.assertNotIn("Authorization", forwarded)

    def test_not_before_in_the_future_is_401(self):
        token = make_token("admin", extra={"nbf": int(time.time()) + 600})
        self.assert_rejected(self.put_status(bearer(token)), 401, "UNAUTHORIZED")


class GatewayAuthorizationTests(GatewayTestCase):
    def test_park_manager_cannot_update_status(self):
        response = self.client.put(
            "/restrooms/1/status",
            data='{"status": "closed"}',
            content_type="application/json",
            headers=self.manager,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "FORBIDDEN")
        self.mock_request.assert_not_called()

    def test_park_manager_cannot_create_restroom(self):
        response = self.client.post(
            "/restrooms", data="{}", content_type="application/json",
            headers=self.manager,
        )

        self.assertEqual(response.status_code, 403)
        self.mock_request.assert_not_called()

    def test_admin_can_create_restroom(self):
        response = self.client.post(
            "/restrooms", data="{}", content_type="application/json",
            headers=self.admin,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.mock_request.call_args[0][0], "POST")

    def test_feedback_history_requires_staff_role(self):
        self.assertEqual(self.client.get("/feedback/1").status_code, 401)
        self.assertEqual(self.client.get("/feedback/1", headers=self.manager).status_code, 200)
        self.assertEqual(self.client.get("/feedback/1", headers=self.admin).status_code, 200)

    def test_unknown_or_missing_role_is_403(self):
        for token in [make_token("superuser"), make_token(omit=("role",)),
                      make_token(extra={"role": ["admin"]})]:
            with self.subTest():
                self.mock_request.reset_mock()
                response = self.client.put(
                    "/restrooms/1/status",
                    data='{"status": "closed"}',
                    content_type="application/json",
                    headers=bearer(token),
                )
                self.assertEqual(response.status_code, 403)
                self.mock_request.assert_not_called()

    def test_client_supplied_role_headers_cannot_escalate(self):
        spoof = {"X-Role": "admin", "X-User-Role": "admin", "Role": "admin"}

        no_token = self.client.put(
            "/restrooms/1/status", data="{}", content_type="application/json",
            headers=spoof,
        )
        manager = self.client.put(
            "/restrooms/1/status", data="{}", content_type="application/json",
            headers={**spoof, **self.manager},
        )

        self.assertEqual(no_token.status_code, 401)
        self.assertEqual(manager.status_code, 403)
        self.mock_request.assert_not_called()

    def test_health_all_requires_staff_but_health_is_public(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/health/all").status_code, 401)

    def test_auth_verify_requires_staff_and_returns_gateway_verified_role(self):
        self.assertEqual(self.client.get("/auth/verify").status_code, 401)

        response = self.client.get("/auth/verify", headers=self.manager)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"role": "park_manager"})
        self.mock_request.assert_not_called()

    def test_auth_verify_rejects_non_staff_roles(self):
        visitor = bearer(make_token("visitor"))

        response = self.client.get("/auth/verify", headers=visitor)

        self.assertEqual(response.status_code, 403)
        self.mock_request.assert_not_called()

    def test_invalid_signature_logs_failure_type_without_changing_response(self):
        invalid_signature = bearer(make_token(secret="different-test-secret"))

        with self.assertLogs("gateway.App_Gateway", level="WARNING") as logs:
            response = self.client.get(
                "/auth/verify",
                headers=invalid_signature,
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["message"], "Invalid token.")
        self.assertIn("InvalidSignatureError", logs.output[0])
        self.assertNotIn("different-test-secret", logs.output[0])

    def test_health_all_returns_503_when_a_backend_is_down(self):
        healthy = Mock(status_code=200)
        healthy.json.return_value = {"service": "Registry", "status": "UP"}
        unavailable = Mock(status_code=503)
        unavailable.json.return_value = {"status": "DOWN"}
        with patch(
            "gateway.App_Gateway.requests.get",
            side_effect=[healthy, unavailable],
        ):
            response = self.client.get("/health/all", headers=self.manager)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["services"]["reporting_service"]["status"],
            "DOWN",
        )

    def test_health_all_returns_503_for_invalid_backend_health_json(self):
        healthy = Mock(status_code=200)
        healthy.json.return_value = {"status": "UP"}
        invalid = Mock(status_code=200)
        invalid.json.side_effect = ValueError("invalid JSON")
        with patch(
            "gateway.App_Gateway.requests.get",
            side_effect=[healthy, invalid],
        ):
            response = self.client.get("/health/all", headers=self.admin)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["services"]["reporting_service"]["status"],
            "DOWN",
        )

    def test_public_endpoints_need_no_token(self):
        self.assertEqual(self.client.get("/restrooms").status_code, 200)
        self.assertEqual(self.client.get("/restrooms/1").status_code, 200)
        self.assertEqual(
            self.client.post("/feedback", data="{}", content_type="application/json").status_code,
            200,
        )
        self.assertEqual(self.client.get("/feedback/reports/1").status_code, 200)

    def test_every_gateway_route_has_an_access_policy(self):
        for rule in gateway.app.url_map.iter_rules():
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                with self.subTest(route=rule.rule, method=method):
                    self.assertIn((method, rule.rule), gateway.ROUTE_POLICY)

    def test_no_static_route_is_exposed(self):
        self.assertEqual(self.client.get("/static/anything").status_code, 404)


class GatewayFailClosedTests(GatewayTestCase):
    def test_protected_route_fails_closed_when_secret_missing(self):
        with patch.dict(os.environ, {"JWT_SECRET": ""}):
            response = self.client.put(
                "/restrooms/1/status",
                data='{"status": "closed"}',
                content_type="application/json",
                headers=self.admin,
            )
            public = self.client.get("/restrooms")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"], "AUTH_NOT_CONFIGURED")
        self.assertEqual(public.status_code, 200)
        self.mock_request.assert_called_once()  # only the public call

    def test_short_secret_is_reported_as_a_config_problem(self):
        with patch.dict(os.environ, {"JWT_SECRET": "short"}):
            self.assertTrue(any("JWT_SECRET" in p for p in gateway.config_problems()))

    def test_complete_configuration_has_no_problems(self):
        self.assertEqual(gateway.config_problems(), [])

    def test_missing_issuer_and_audience_are_config_problems(self):
        with patch.dict(os.environ, {"JWT_ISSUER": "", "JWT_AUDIENCE": ""}):
            problems = gateway.config_problems()
        self.assertTrue(any("JWT_ISSUER" in p for p in problems))
        self.assertTrue(any("JWT_AUDIENCE" in p for p in problems))


class GatewayCorsTests(GatewayTestCase):
    def test_configured_origin_receives_cors_headers(self):
        with patch.dict(
            os.environ,
            {"SANIMAP_CORS_ORIGINS": "https://map.example, https://staging.example"},
        ):
            response = self.client.get(
                "/restrooms", headers={"Origin": "https://map.example"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"], "https://map.example"
        )
        self.assertIn("Origin", response.vary)
        self.assertIn("GET", response.headers["Access-Control-Allow-Methods"])
        self.assertIn(
            "Authorization", response.headers["Access-Control-Allow-Headers"]
        )
        self.assertIn(
            "Idempotency-Key", response.headers["Access-Control-Allow-Headers"]
        )

    def test_unconfigured_origin_does_not_receive_cors_permission(self):
        with patch.dict(
            os.environ, {"SANIMAP_CORS_ORIGINS": "https://map.example"}
        ):
            response = self.client.get(
                "/restrooms", headers={"Origin": "https://attacker.example"}
            )

        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_preflight_from_configured_origin_is_allowed(self):
        with patch.dict(
            os.environ, {"SANIMAP_CORS_ORIGINS": "https://map.example"}
        ):
            response = self.client.options(
                "/restrooms",
                headers={
                    "Origin": "https://map.example",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"], "https://map.example"
        )
        self.assertIn("OPTIONS", response.headers["Access-Control-Allow-Methods"])


if __name__ == "__main__":
    unittest.main()