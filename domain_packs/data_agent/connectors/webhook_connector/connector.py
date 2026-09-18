from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from ...domain_contracts import OperationContract, StateSnapshot

from ...action_connectors.base import ActionConnector

# Maximum number of bytes from the response body retained in the result.
_RESPONSE_BODY_TRUNCATE = 1024


class WebhookActionConnector(ActionConnector):
    """Action connector that delivers a JSON payload via HTTP POST to a webhook URL.

    Security is enforced through a URL whitelist: only URLs whose base
    (scheme + netloc) appears in ``allowed_urls`` are accepted. The connector
    retries on server-side (5xx) errors with exponential back-off and returns
    a structured result for every outcome (success, retry exhaustion, timeout,
    connection error, whitelist rejection).

    This connector does NOT support rollback — an HTTP POST cannot be undone.
    """

    def __init__(
        self,
        *,
        allowed_urls: list[str] | tuple[str, ...],
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ) -> None:
        if not allowed_urls:
            raise ValueError("allowed_urls must contain at least one entry")
        self._allowed_bases: frozenset[str] = frozenset(self._url_base(u) for u in allowed_urls)
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    # ------------------------------------------------------------------
    # ActionConnector interface
    # ------------------------------------------------------------------

    @property
    def connector_name(self) -> str:
        return "webhook"

    def take_snapshot(self, operation: OperationContract) -> StateSnapshot | None:
        """Webhook POST is irreversible; no snapshot is taken."""
        return None

    def dry_run(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """Preview the webhook call without dispatching it."""
        url = parameters.get("url", "")
        whitelist_error = self._validate_url(url)
        if whitelist_error is not None:
            return {
                "status": "dry_run_failed",
                "error": whitelist_error,
            }
        payload = parameters.get("payload", {})
        return {
            "status": "dry_run",
            "connector_name": self.connector_name,
            "operation_id": operation.operation_id,
            "url": url,
            "payload_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
            "would_send": True,
        }

    def execute(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """POST a JSON payload to the specified webhook URL.

        Expected ``parameters`` keys:
            url (str): The webhook endpoint (must pass whitelist check).
            payload (dict): The JSON-serialisable body.
            headers (dict[str, str], optional): Extra HTTP headers.

        Returns:
            A dict with ``status``, ``http_status``, ``response_body`` (truncated),
            and ``artifact_id``.
        """
        artifact_id = f"webhook-{uuid4().hex[:12]}"
        url = parameters.get("url", "")
        payload = parameters.get("payload", {})
        extra_headers = parameters.get("headers", {})

        # --- URL whitelist validation ---
        whitelist_error = self._validate_url(url)
        if whitelist_error is not None:
            return {
                "status": "failure",
                "message": whitelist_error,
                "artifact_id": artifact_id,
                "error_type": "url_not_allowed",
            }

        # --- Build the request ---
        body_bytes = json.dumps(payload, default=str).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body_bytes,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                **extra_headers,
            },
        )

        # --- Send with retry on 5xx ---
        last_error: str | None = None
        last_error_type: str = "unknown"
        attempts = 0
        while attempts <= self._max_retries:
            attempts += 1
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    resp_body = resp.read(_RESPONSE_BODY_TRUNCATE).decode("utf-8", errors="replace")
                    return {
                        "status": "success",
                        "message": f"webhook delivered (HTTP {resp.status})",
                        "artifact_id": artifact_id,
                        "http_status": resp.status,
                        "response_body": resp_body,
                        "attempts": attempts,
                    }

            except urllib.error.HTTPError as exc:
                resp_body = ""
                try:
                    resp_body = exc.read(_RESPONSE_BODY_TRUNCATE).decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    pass

                if exc.code >= 500 and attempts <= self._max_retries:
                    # Retry with exponential back-off
                    delay = self._backoff_base * (2 ** (attempts - 1))
                    time.sleep(delay)
                    last_error = f"HTTP {exc.code}: {resp_body[:200]}"
                    last_error_type = "server_error"
                    continue

                return {
                    "status": "failure",
                    "message": f"HTTP {exc.code}: {resp_body[:200]}",
                    "artifact_id": artifact_id,
                    "http_status": exc.code,
                    "response_body": resp_body[:_RESPONSE_BODY_TRUNCATE],
                    "attempts": attempts,
                    "error_type": "server_error" if exc.code >= 500 else "client_error",
                }

            except urllib.error.URLError as exc:
                reason = str(exc.reason)
                if "timed out" in reason.lower() or "timeout" in reason.lower():
                    last_error = f"timeout after {self._timeout}s"
                    last_error_type = "timeout"
                else:
                    last_error = f"connection error: {reason}"
                    last_error_type = "connection_error"
                # Retry on transient network errors
                if attempts <= self._max_retries:
                    delay = self._backoff_base * (2 ** (attempts - 1))
                    time.sleep(delay)
                    continue

                return {
                    "status": "failure",
                    "message": last_error,
                    "artifact_id": artifact_id,
                    "attempts": attempts,
                    "error_type": last_error_type,
                }

            except OSError as exc:
                last_error = f"connection error: {exc}"
                last_error_type = "connection_error"
                if attempts <= self._max_retries:
                    delay = self._backoff_base * (2 ** (attempts - 1))
                    time.sleep(delay)
                    continue

                return {
                    "status": "failure",
                    "message": last_error,
                    "artifact_id": artifact_id,
                    "attempts": attempts,
                    "error_type": last_error_type,
                }

        # All retries exhausted
        return {
            "status": "failure",
            "message": f"retries exhausted after {attempts} attempt(s): {last_error}",
            "artifact_id": artifact_id,
            "attempts": attempts,
            "error_type": last_error_type,
        }

    def rollback(self, snapshot: StateSnapshot) -> dict[str, Any]:
        """Webhook POST cannot be rolled back."""
        return {
            "status": "not_applicable",
            "reason": "webhook HTTP POST cannot be undone after delivery",
        }

    def can_rollback(self) -> bool:
        return False

    def compensating_action(self) -> str | None:
        """No compensating action — webhook calls are irreversible."""
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _url_base(url: str) -> str:
        """Extract the scheme + netloc base from a URL for whitelist matching."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _validate_url(self, url: str) -> str | None:
        """Return an error message if the URL fails the whitelist, else None."""
        if not url:
            return "url must not be empty"
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"unsupported URL scheme: {parsed.scheme!r}; only http and https are allowed"
        base = self._url_base(url)
        if base not in self._allowed_bases:
            return f"URL {url!r} is not in the allowed whitelist"
        return None
