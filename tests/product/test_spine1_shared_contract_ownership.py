from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import DomainPackManifest


def test_generic_domain_manifest_has_no_data_or_execution_authority_fields() -> None:
    assert set(DomainPackManifest.model_fields).isdisjoint(
        {
            "sql",
            "metric",
            "semantic_object",
            "data_product",
            "provider_runtime",
            "policy_kernel",
            "approval_authority",
            "credential_value",
        }
    )


def test_generic_domain_manifest_rejects_data_specific_extension_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DomainPackManifest(
            pack_id="invalid-data-pack",
            version="1",
            namespace="invalid",
            capabilities=("data.query.safe",),
            created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
            metric="gmv",
        )
