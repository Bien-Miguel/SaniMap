import unittest
from unittest.mock import Mock, patch

import requests

from gateway import App_Gateway as gateway


def fake_backend_response(status=200, body=b'{"ok": true}', content_type="application/json"):
    resp = Mock()
    resp.status_code = status
    resp.content = body
    resp.headers = {"Content-Type": content_type}
    return resp


class GatewayForwardingTests(unittest.TestCase):
    def setUp(self):
        gateway.app.config["TESTING"] = True
        self.client = gateway.app.test_client()

    @patch("gateway.App_Gateway.requests.request")
    def test_put_status_reaches_registry_with_body_and_content_type(self, mock_request):
        mock_request.return_value = fake_backend_response()

        response = self.client.put(
            "/restrooms/1/status",
            data='{"status": "closed"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "PUT")
        self.assertEqual(args[1], "http://127.0.0.1:5001/restrooms/1/status")
        self.assertEqual(kwargs["data"], b'{"status": "closed"}')
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")

    @patch("gateway.App_Gateway.requests.request")
    def test_query_string_is_forwarded_unchanged(self, mock_request):
        mock_request.return_value = fake_backend_response()

        self.client.get("/restrooms?name=Rizal%20Monument&tag=a&tag=b&empty=")

        url = mock_request.call_args[0][1]
        self.assertEqual(
            url,
            "http://127.0.0.1:5001/restrooms?name=Rizal%20Monument&tag=a&tag=b&empty=",
        )

    @patch("gateway.App_Gateway.requests.request")
    def test_no_query_string_leaves_url_clean(self, mock_request):
        mock_request.return_value = fake_backend_response()

        self.client.get("/restrooms")

        self.assertEqual(
            mock_request.call_args[0][1], "http://127.0.0.1:5001/restrooms"
        )

    @patch("gateway.App_Gateway.requests.request")
    def test_backend_status_and_body_are_preserved(self, mock_request):
        mock_request.return_value = fake_backend_response(
            404, b'{"error": "RESOURCE_NOT_FOUND"}'
        )

        response = self.client.put(
            "/restrooms/999/status",
            data='{"status": "open"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "RESOURCE_NOT_FOUND")

    @patch("gateway.App_Gateway.requests.request")
    def test_accept_header_is_forwarded(self, mock_request):
        mock_request.return_value = fake_backend_response(
            body=b"<restrooms/>", content_type="application/xml"
        )

        response = self.client.get("/restrooms", headers={"Accept": "application/xml"})

        self.assertEqual(mock_request.call_args[1]["headers"]["Accept"], "application/xml")
        self.assertEqual(response.content_type, "application/xml")

    @patch("gateway.App_Gateway.requests.request")
    def test_unsupported_methods_are_rejected_without_forwarding(self, mock_request):
        response = self.client.delete("/restrooms/1/status")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.get_json()["error"], "METHOD_NOT_ALLOWED")
        mock_request.assert_not_called()

    @patch("gateway.App_Gateway.requests.request")
    def test_unknown_route_returns_json_404(self, mock_request):
        response = self.client.get("/does-not-exist")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "NOT_FOUND")
        mock_request.assert_not_called()

    @patch("gateway.App_Gateway.requests.request")
    def test_backend_down_returns_503_json(self, mock_request):
        mock_request.side_effect = requests.exceptions.ConnectionError()

        response = self.client.put(
            "/restrooms/1/status",
            data='{"status": "closed"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "SERVICE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()