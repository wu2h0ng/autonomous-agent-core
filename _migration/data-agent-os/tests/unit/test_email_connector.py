from __future__ import annotations

import smtplib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import OperationContract  # noqa: E402

from email_connector import EmailActionConnector  # noqa: E402


def _make_operation(op_id: str = "op-email-1") -> OperationContract:
    return OperationContract(
        operation_id=op_id,
        name="send_notification",
        target_connector="email",
        risk_level="R1",
        approval_required=False,
        connector_name="email",
        action_type="notify",
    )


def _make_connector(**kwargs: object) -> EmailActionConnector:
    defaults = {
        "host": "smtp.test.local",
        "port": 587,
        "username": "user@test.local",
        "password": "secret",
        "sender": "noreply@test.local",
    }
    defaults.update(kwargs)
    return EmailActionConnector(**defaults)  # type: ignore[arg-type]


class EmailConnectorSendsSuccessfullyTest(unittest.TestCase):
    @patch("email_connector.connector.smtplib.SMTP")
    def test_email_connector_sends_successfully(self, mock_smtp_cls: MagicMock) -> None:
        """A well-formed call with a reachable SMTP server returns success."""
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        connector = _make_connector()
        operation = _make_operation()
        result = connector.execute(
            operation,
            {
                "recipients": ["alice@example.com", "bob@example.com"],
                "subject": "Test Subject",
                "body": "<h1>Hello</h1>",
                "content_type": "html",
            },
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["recipients"], ["alice@example.com", "bob@example.com"])
        self.assertEqual(result["subject"], "Test Subject")
        self.assertTrue(result["artifact_id"].startswith("email-"))
        # Verify the SMTP interaction happened
        mock_server.sendmail.assert_called_once()
        call_args = mock_server.sendmail.call_args
        self.assertEqual(call_args[0][0], "noreply@test.local")
        self.assertEqual(call_args[0][1], ["alice@example.com", "bob@example.com"])
        # Verify TLS was started
        mock_server.starttls.assert_called_once()
        # Verify login was called
        mock_server.login.assert_called_once_with("user@test.local", "secret")


class EmailConnectorAuthFailureTest(unittest.TestCase):
    @patch("email_connector.connector.smtplib.SMTP")
    def test_email_connector_handles_auth_failure(self, mock_smtp_cls: MagicMock) -> None:
        """SMTP authentication errors surface as a failure with error_type."""
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"5.7.8 Username and Password not accepted"
        )
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        connector = _make_connector()
        result = connector.execute(
            _make_operation(),
            {
                "recipients": ["alice@example.com"],
                "subject": "Test",
                "body": "Hello",
            },
        )

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error_type"], "authentication_error")
        self.assertIn("authentication failed", result["message"].lower())
        self.assertTrue(result["artifact_id"].startswith("email-"))


class EmailConnectorConnectionErrorTest(unittest.TestCase):
    @patch("email_connector.connector.smtplib.SMTP")
    def test_email_connector_handles_connection_error(self, mock_smtp_cls: MagicMock) -> None:
        """Network-level errors (e.g. refused connection) surface as connection_error."""
        mock_smtp_cls.side_effect = OSError("Connection refused")

        connector = _make_connector()
        result = connector.execute(
            _make_operation(),
            {
                "recipients": ["alice@example.com"],
                "subject": "Test",
                "body": "Hello",
            },
        )

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error_type"], "connection_error")
        self.assertIn("connection error", result["message"].lower())
        self.assertTrue(result["artifact_id"].startswith("email-"))


class EmailConnectorRejectsEmptyRecipientsTest(unittest.TestCase):
    def test_email_connector_rejects_empty_recipients(self) -> None:
        """An empty recipient list must be rejected before any SMTP call."""
        connector = _make_connector()

        for recipients_value in ([], None, ""):
            with self.subTest(recipients=recipients_value):
                result = connector.execute(
                    _make_operation(),
                    {
                        "recipients": recipients_value,
                        "subject": "Test",
                        "body": "Hello",
                    },
                )
                self.assertEqual(result["status"], "failure")
                self.assertIn("recipients", result["message"].lower())

    def test_email_connector_rejects_missing_recipients_key(self) -> None:
        """Missing 'recipients' key must produce a failure result."""
        connector = _make_connector()
        result = connector.execute(_make_operation(), {"subject": "Test", "body": "Hello"})
        self.assertEqual(result["status"], "failure")
        self.assertIn("recipients", result["message"].lower())


class EmailConnectorRollbackTest(unittest.TestCase):
    def test_email_connector_does_not_support_rollback(self) -> None:
        connector = _make_connector()
        self.assertFalse(connector.can_rollback())

    def test_email_connector_compensating_action_is_none(self) -> None:
        connector = _make_connector()
        self.assertIsNone(connector.compensating_action())

    def test_email_connector_snapshot_returns_none(self) -> None:
        connector = _make_connector()
        self.assertIsNone(connector.take_snapshot(_make_operation()))

    def test_email_connector_rollback_returns_not_applicable(self) -> None:
        from agent_os_contracts import StateSnapshot

        connector = _make_connector()
        snapshot = StateSnapshot(
            snapshot_id="snap-1",
            operation_id="op-1",
            connector_name="email",
            snapshot_type="full",
            state_payload={},
            created_at="2026-01-01T00:00:00Z",
        )
        result = connector.rollback(snapshot)
        self.assertEqual(result["status"], "not_applicable")


class EmailConnectorDryRunTest(unittest.TestCase):
    def test_dry_run_previews_without_sending(self) -> None:
        connector = _make_connector()
        result = connector.dry_run(
            _make_operation(),
            {
                "recipients": ["alice@example.com"],
                "subject": "Preview",
                "body": "Test",
            },
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertTrue(result["would_send"])
        self.assertEqual(result["recipients"], ["alice@example.com"])

    def test_dry_run_rejects_empty_recipients(self) -> None:
        connector = _make_connector()
        result = connector.dry_run(_make_operation(), {"recipients": [], "subject": "X"})
        self.assertEqual(result["status"], "dry_run_failed")


class EmailConnectorContentTypeValidationTest(unittest.TestCase):
    @patch("email_connector.connector.smtplib.SMTP")
    def test_rejects_unsupported_content_type(self, mock_smtp_cls: MagicMock) -> None:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        connector = _make_connector()
        result = connector.execute(
            _make_operation(),
            {
                "recipients": ["alice@example.com"],
                "subject": "Test",
                "body": "data",
                "content_type": "xml",
            },
        )
        self.assertEqual(result["status"], "failure")
        self.assertIn("content_type", result["message"])
        # sendmail must NOT have been called
        mock_server.sendmail.assert_not_called()


class EmailConnectorSmtpExceptionTest(unittest.TestCase):
    @patch("email_connector.connector.smtplib.SMTP")
    def test_handles_generic_smtp_exception(self, mock_smtp_cls: MagicMock) -> None:
        """Non-auth SMTP exceptions (e.g. recipient rejected) surface as smtp_error."""
        mock_server = MagicMock()
        mock_server.sendmail.side_effect = smtplib.SMTPRecipientsRefused(
            {"bad@example.com": (550, b"User unknown")}
        )
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        connector = _make_connector()
        result = connector.execute(
            _make_operation(),
            {
                "recipients": ["bad@example.com"],
                "subject": "Test",
                "body": "Hello",
            },
        )
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error_type"], "smtp_error")


class EmailConnectorConnectorNameTest(unittest.TestCase):
    def test_connector_name(self) -> None:
        connector = _make_connector()
        self.assertEqual(connector.connector_name, "email")


if __name__ == "__main__":
    unittest.main()
