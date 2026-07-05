from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import OperationContract  # noqa: E402

from webhook_connector import WebhookActionConnector  # noqa: E402

ALLOWED_URLS = ["https://hooks.example.com", "https://api.partner.com"]


def _make_operation(op_id: str = "op-wh-1") -> OperationContract:
    return OperationContract(
        operation_id=op_id,
        name="notify_external",
        target_connector="webhook",
        risk_level="R2",
        approval_required=False,
        connector_name="webhook",
        action_type="webhook_post",
    )


def _make_connector(**kwargs: object) -> WebhookActionConnector:
    defaults: dict[str, object] = {
        "allowed_urls": ALLOWED_URLS,
        "timeout": 5.0,
        "max_retries": 3,
        "backoff_base": 0.01,  # tiny backoff for tests
    }
    defaults.update(kwargs)
    return WebhookActionConnector(**defaults)  # type: ignore[arg-type]


def _success_response(status: int = 200, body: str = '{"ok":true}') -> MagicMock:
    """Build a mock context manager that behaves like urllib.request.urlopen."""
    resp = MagicMock()
    resp.status = status
    resp.read = MagicMock(return_value=body.encode("utf-8"))
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class WebhookConnectorPostsSuccessfullyTest(unittest.TestCase):
    @patch("webhook_connector.connector.urllib.request.urlopen")
    def test_webhook_connector_posts_successfully(self, mock_urlopen: MagicMock) -> None:
        """A 200 response from a whitelisted URL returns success."""
        mock_urlopen.return_value = _success_response(200, '{"received":true}')

        connector = _make_connector()
        result = connector.execute(
            _make_operation(),
            {
                "url": "https://hooks.example.com/incoming",
                "payload": {"event": "order.created", "order_id": "ORD-123"},
            },
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["http_status"], 200)
        self.assertIn("received", result["response_body"])
        self.assertEqual(result["attempts"], 1)
        self.assertTrue(result["artifact_id"].startswith("webhook-"))

        # Verify the actual HTTP request was constructed correctly
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertIsInstance(req, urllib.request.Request)
        self.assertEqual(req.full_url, "https://hooks.example.com/incoming")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        sent_body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(sent_body["event"], "order.created")
        self.assertEqual(sent_body["order_id"], "ORD-123")


class WebhookConnectorWhitelistTest(unittest.TestCase):
    def test_webhook_connector_rejects_url_not_in_whitelist(self) -> None:
        """A URL whose base is not in the whitelist is rejected before any HTTP call."""
        connector = _make_connector()
        result = connector.execute(
            _make_operation(),
            {
                "url": "https://evil.attacker.com/steal",
                "payload": {"data": "secret"},
            },
        )

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error_type"], "url_not_allowed")
        self.assertIn("whitelist", result["message"].lower())
        self.assertTrue(result["artifact_id"].startswith("webhook-"))

    def test_webhook_connector_rejects_empty_url(self) -> None:
        connector = _make_connector()
        result = connector.execute(_make_operation(), {"url": "", "payload": {}})
        self.assertEqual(result["status"], "failure")
        self.assertIn("empty", result["message"].lower())

    def test_webhook_connector_rejects_non_http_scheme(self) -> None:
        connector = _make_connector()
        result = connector.execute(
            _make_operation(),
            {"url": "ftp://hooks.example.com/file", "payload": {}},
        )
        self.assertEqual(result["status"], "failure")
        self.assertIn("scheme", result["message"].lower())


class WebhookConnectorRetryTest(unittest.TestCase):
    @patch("webhook_connector.connector.time.sleep")
    @patch("webhook_connector.connector.urllib.request.urlopen")
    def test_webhook_connector_retries_on_5xx(
        self, mock_urlopen: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """5xx errors trigger exponential-backoff retries; eventual success is returned."""

        def side_effect(req, **kwargs):  # noqa: ANN001, ARG001
            if mock_urlopen.call_count <= 2:
                raise urllib.error.HTTPError(
                    url="https://hooks.example.com/incoming",
                    code=503,
                    msg="Service Unavailable",
                    hdrs=MagicMock(),
                    fp=io.BytesIO(b"temporary outage"),
                )
            return _success_response(200, '{"ok":true}')

        mock_urlopen.side_effect = side_effect

        connector = _make_connector(max_retries=3, backoff_base=0.01)
        result = connector.execute(
            _make_operation(),
            {
                "url": "https://hooks.example.com/incoming",
                "payload": {"event": "test"},
            },
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["attempts"], 3)
        # Verify sleep was called with exponential backoff
        self.assertEqual(mock_sleep.call_count, 2)
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        self.assertAlmostEqual(sleep_calls[0], 0.01, places=4)
        self.assertAlmostEqual(sleep_calls[1], 0.02, places=4)

    @patch("webhook_connector.connector.time.sleep")
    @patch("webhook_connector.connector.urllib.request.urlopen")
    def test_webhook_connector_exhausts_retries_on_persistent_5xx(
        self, mock_urlopen: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Persistent 5xx errors exhaust retries and return failure."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://hooks.example.com/incoming",
            code=500,
            msg="Internal Server Error",
            hdrs=MagicMock(),
            fp=io.BytesIO(b"server down"),
        )

        connector = _make_connector(max_retries=2, backoff_base=0.01)
        result = connector.execute(
            _make_operation(),
            {
                "url": "https://hooks.example.com/incoming",
                "payload": {"event": "test"},
            },
        )

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error_type"], "server_error")
        self.assertEqual(result["http_status"], 500)
        # 1 initial + 2 retries = 3 attempts total
        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("webhook_connector.connector.time.sleep")
    @patch("webhook_connector.connector.urllib.request.urlopen")
    def test_webhook_connector_does_not_retry_4xx(
        self, mock_urlopen: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """4xx client errors are NOT retried — they are returned immediately."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://hooks.example.com/incoming",
            code=400,
            msg="Bad Request",
            hdrs=MagicMock(),
            fp=io.BytesIO(b"invalid payload"),
        )

        connector = _make_connector()
        result = connector.execute(
            _make_operation(),
            {
                "url": "https://hooks.example.com/incoming",
                "payload": {"bad": "data"},
            },
        )

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error_type"], "client_error")
        self.assertEqual(result["http_status"], 400)
        self.assertEqual(mock_urlopen.call_count, 1)
        mock_sleep.assert_not_called()


class WebhookConnectorTimeoutTest(unittest.TestCase):
    @patch("webhook_connector.connector.time.sleep")
    @patch("webhook_connector.connector.urllib.request.urlopen")
    def test_webhook_connector_handles_timeout(
        self, mock_urlopen: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Socket timeout errors are retried, then reported as timeout failure."""
        mock_urlopen.side_effect = urllib.error.URLError(reason="timed out")

        connector = _make_connector(timeout=1.0, max_retries=1, backoff_base=0.01)
        result = connector.execute(
            _make_operation(),
            {
                "url": "https://hooks.example.com/slow",
                "payload": {"event": "test"},
            },
        )

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error_type"], "timeout")
        self.assertIn("timeout", result["message"].lower())
        # 1 initial + 1 retry = 2
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("webhook_connector.connector.time.sleep")
    @patch("webhook_connector.connector.urllib.request.urlopen")
    def test_webhook_connector_handles_connection_error(
        self, mock_urlopen: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Non-timeout URLError (e.g. DNS failure) surfaces as connection_error."""
        mock_urlopen.side_effect = urllib.error.URLError(reason="Name or service not known")

        connector = _make_connector(max_retries=0, backoff_base=0.01)
        result = connector.execute(
            _make_operation(),
            {
                "url": "https://hooks.example.com/incoming",
                "payload": {"event": "test"},
            },
        )

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error_type"], "connection_error")
        self.assertIn("connection error", result["message"].lower())


class WebhookConnectorRollbackTest(unittest.TestCase):
    def test_webhook_connector_does_not_support_rollback(self) -> None:
        connector = _make_connector()
        self.assertFalse(connector.can_rollback())

    def test_webhook_connector_compensating_action_is_none(self) -> None:
        connector = _make_connector()
        self.assertIsNone(connector.compensating_action())

    def test_webhook_connector_snapshot_returns_none(self) -> None:
        connector = _make_connector()
        self.assertIsNone(connector.take_snapshot(_make_operation()))

    def test_webhook_connector_rollback_returns_not_applicable(self) -> None:
        from agent_os_contracts import StateSnapshot

        connector = _make_connector()
        snapshot = StateSnapshot(
            snapshot_id="snap-1",
            operation_id="op-1",
            connector_name="webhook",
            snapshot_type="full",
            state_payload={},
            created_at="2026-01-01T00:00:00Z",
        )
        result = connector.rollback(snapshot)
        self.assertEqual(result["status"], "not_applicable")


class WebhookConnectorDryRunTest(unittest.TestCase):
    def test_dry_run_previews_without_sending(self) -> None:
        connector = _make_connector()
        result = connector.dry_run(
            _make_operation(),
            {
                "url": "https://hooks.example.com/incoming",
                "payload": {"event": "test", "value": 42},
            },
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertTrue(result["would_send"])
        self.assertEqual(result["payload_keys"], ["event", "value"])

    def test_dry_run_rejects_non_whitelisted_url(self) -> None:
        connector = _make_connector()
        result = connector.dry_run(
            _make_operation(),
            {"url": "https://evil.com/hook", "payload": {}},
        )
        self.assertEqual(result["status"], "dry_run_failed")


class WebhookConnectorConstructorValidationTest(unittest.TestCase):
    def test_empty_allowed_urls_raises(self) -> None:
        with self.assertRaises(ValueError):
            WebhookActionConnector(allowed_urls=[])

    def test_connector_name(self) -> None:
        connector = _make_connector()
        self.assertEqual(connector.connector_name, "webhook")


class WebhookConnectorExtraHeadersTest(unittest.TestCase):
    @patch("webhook_connector.connector.urllib.request.urlopen")
    def test_extra_headers_are_included(self, mock_urlopen: MagicMock) -> None:
        """Custom headers passed via parameters are forwarded to the HTTP request."""
        mock_urlopen.return_value = _success_response(200, "{}")

        connector = _make_connector()
        connector.execute(
            _make_operation(),
            {
                "url": "https://hooks.example.com/incoming",
                "payload": {"test": True},
                "headers": {"Authorization": "Bearer token-abc", "X-Custom": "value"},
            },
        )

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_header("Authorization"), "Bearer token-abc")
        self.assertEqual(req.get_header("X-custom"), "value")


if __name__ == "__main__":
    unittest.main()
