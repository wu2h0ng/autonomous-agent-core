from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
from uuid import uuid4

from ...domain_contracts import OperationContract, StateSnapshot

from ...action_connectors.base import ActionConnector


class EmailActionConnector(ActionConnector):
    """Action connector that sends emails via SMTP.

    Sends an email to the specified recipients with the given subject and body.
    Supports both plain-text and HTML content. The connector uses a real SMTP
    connection; external dependencies (the SMTP server) are injected via
    constructor configuration so tests can mock them.

    This connector does NOT support rollback — once an email is sent it cannot
    be unsent. ``take_snapshot`` returns ``None`` and ``can_rollback`` returns
    ``False``.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        sender: str = "noreply@agent-os.local",
        use_tls: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._use_tls = use_tls
        self._timeout = timeout

    @property
    def connector_name(self) -> str:
        return "email"

    def take_snapshot(self, operation: OperationContract) -> StateSnapshot | None:
        """Email cannot be pre-snapshotted (side effect is external and irreversible)."""
        return None

    def dry_run(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """Preview the email that would be sent without actually sending."""
        recipients = parameters.get("recipients")
        if not recipients or not isinstance(recipients, list) or len(recipients) == 0:
            return {
                "status": "dry_run_failed",
                "error": "recipients must be a non-empty list",
            }
        subject = parameters.get("subject", "")
        return {
            "status": "dry_run",
            "connector_name": self.connector_name,
            "operation_id": operation.operation_id,
            "recipients": list(recipients),
            "subject": subject,
            "sender": self._sender,
            "would_send": True,
        }

    def execute(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """Send an email to the specified recipients.

        Expected ``parameters`` keys:
            recipients (list[str]): One or more email addresses.
            subject (str): The email subject line.
            body (str): The email body content.
            content_type (str): ``"plain"`` (default) or ``"html"``.

        Returns:
            A dict with ``status`` (``success`` or ``failure``), a human-readable
            ``message``, and an ``artifact_id`` for traceability.
        """
        artifact_id = f"email-{uuid4().hex[:12]}"

        # --- Validate recipients ---
        recipients = parameters.get("recipients")
        if not recipients or not isinstance(recipients, list) or len(recipients) == 0:
            return {
                "status": "failure",
                "message": "recipients must be a non-empty list",
                "artifact_id": artifact_id,
            }

        subject = parameters.get("subject", "")
        body = parameters.get("body", "")
        content_type = parameters.get("content_type", "plain")

        if content_type not in ("plain", "html"):
            return {
                "status": "failure",
                "message": f"unsupported content_type: {content_type!r}; expected 'plain' or 'html'",
                "artifact_id": artifact_id,
            }

        # --- Build the message ---
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._sender
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body, content_type, "utf-8"))

        # --- Send via SMTP ---
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as server:
                if self._use_tls:
                    server.starttls(context=context)
                if self._username and self._password:
                    server.login(self._username, self._password)
                server.sendmail(self._sender, recipients, msg.as_string())
        except smtplib.SMTPAuthenticationError as exc:
            return {
                "status": "failure",
                "message": f"SMTP authentication failed: {exc.smtp_error.decode('utf-8', errors='replace')}",
                "artifact_id": artifact_id,
                "error_type": "authentication_error",
            }
        except smtplib.SMTPException as exc:
            return {
                "status": "failure",
                "message": f"SMTP error: {type(exc).__name__}: {exc}",
                "artifact_id": artifact_id,
                "error_type": "smtp_error",
            }
        except OSError as exc:
            return {
                "status": "failure",
                "message": f"connection error: {exc}",
                "artifact_id": artifact_id,
                "error_type": "connection_error",
            }

        return {
            "status": "success",
            "message": f"email sent to {len(recipients)} recipient(s)",
            "artifact_id": artifact_id,
            "recipients": list(recipients),
            "subject": subject,
        }

    def rollback(self, snapshot: StateSnapshot) -> dict[str, Any]:
        """Email cannot be rolled back once sent."""
        return {
            "status": "not_applicable",
            "reason": "email cannot be unsent after delivery",
        }

    def can_rollback(self) -> bool:
        return False

    def compensating_action(self) -> str | None:
        """No compensating action — emails are irreversible."""
        return None
