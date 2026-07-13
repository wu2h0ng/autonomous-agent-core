"""Derived identity for fresh SPINE evaluation successors."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class SpineEvaluationIdentity:
    """One source for every correlated successor identity value."""

    sequence: int
    run_date: str

    @classmethod
    def create(cls, *, sequence: int, run_date: str) -> SpineEvaluationIdentity:
        if type(sequence) is not int or sequence <= 0:
            raise ValueError("sequence must be a positive integer")
        if not isinstance(run_date, str) or len(run_date) != 8:
            raise ValueError("run_date must be YYYYMMDD")
        try:
            parsed = datetime.strptime(run_date, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("run_date must be YYYYMMDD") from exc
        if parsed.strftime("%Y%m%d") != run_date:
            raise ValueError("run_date must be canonical YYYYMMDD")
        return cls(sequence=sequence, run_date=run_date)

    @property
    def slug(self) -> str:
        return f"spine-e2e-{self.sequence}"

    @property
    def experiment_id(self) -> str:
        return f"SPINE-E2E-{self.sequence}"

    @property
    def run_id(self) -> str:
        return f"{self.slug}-{self.run_date}"

    @property
    def module_slug(self) -> str:
        return self.slug.replace("-", "_")

    @property
    def provider_model(self) -> str:
        return f"{self.slug}-frozen"

    @property
    def provider_api_key_env(self) -> str:
        return f"SPINE_E2E_{self.sequence}_PROVIDER_KEY"

    @property
    def provider_bearer(self) -> str:
        return f"{self.slug}-local-dummy"

    @property
    def bank_schema_version(self) -> str:
        return f"{self.slug}-provider-bank-v1"

    @property
    def generator_version(self) -> str:
        return "spine-bank-generator-v1"

    @property
    def qualification_schema_version(self) -> str:
        return "spine-instrument-qualification-v1"

    @property
    def identity_sha256(self) -> str:
        payload = {
            **asdict(self),
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "module_slug": self.module_slug,
            "provider_model": self.provider_model,
            "provider_api_key_env": self.provider_api_key_env,
            "provider_bearer_sha256": hashlib.sha256(
                self.provider_bearer.encode("utf-8")
            ).hexdigest(),
            "bank_schema_version": self.bank_schema_version,
            "generator_version": self.generator_version,
            "qualification_schema_version": self.qualification_schema_version,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def provider_environment(self, base_url: str) -> dict[str, str]:
        if (
            not isinstance(base_url, str)
            or not base_url.startswith("http://127.0.0.1:")
            or not base_url.endswith("/v1")
        ):
            raise ValueError("provider must be a loopback /v1 endpoint")
        return {
            "AGENT_OS_PROVIDER_BASE_URL": base_url,
            "AGENT_OS_PROVIDER_MODEL": self.provider_model,
            "AGENT_OS_PROVIDER_TEMPERATURE": "0",
            "AGENT_OS_PROVIDER_API_KEY_ENV": self.provider_api_key_env,
            self.provider_api_key_env: self.provider_bearer,
        }

    def expected_provider_status(self) -> dict[str, object]:
        return {
            "configured": True,
            "provider_id": "openai-compatible",
            "model_id": self.provider_model,
            "endpoint_class": "openai-compatible",
            "credential_ref_id": "credential:default",
        }

    def schema(self, name: str) -> str:
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", name) is None
        ):
            raise ValueError("invalid schema name")
        return f"{self.slug}-{name}-v1"
