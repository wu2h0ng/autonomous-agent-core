from __future__ import annotations

import pytest

from scripts.spine1.validate_capability_ownership import OwnershipError, validate_matrix


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "capability_id": "P-DATA-SQL",
        "user_need_ref": "U-DATA-TRUSTED-QUERY",
        "source_repo": "ai-native-business-data-agent-os",
        "source_paths": ["packages/os_core/src/sql_safety"],
        "source_sha": "a" * 40,
        "public_entrypoint": "DataAgentRuntime.run_query",
        "contracts": ["SQLSafetyResult"],
        "failure_paths": ["unsafe SQL fails closed"],
        "tests": ["tests.unit.test_sql_safety"],
        "current_evidence": "PASS",
        "target_owner": "domain_packs/data_agent/sql",
        "disposition": "MOVE_TO_DATA_AGENT_PACK",
        "consumer": ["Data Agent query path"],
        "residual_gap": "not yet migrated",
        "semantic_scope": "DATA_DOMAIN",
        "authority_key": "data_sql_semantics",
        "runtime_authority": True,
        "post_migration_runtime_owners": ["domain_packs/data_agent/sql"],
    }
    row.update(overrides)
    return row


def test_valid_matrix_has_one_runtime_owner() -> None:
    validate_matrix({"schema_version": 1, "capabilities": [_row()]})


def test_data_semantics_cannot_target_os_core() -> None:
    with pytest.raises(OwnershipError, match="Data-domain semantics"):
        validate_matrix(
            {
                "schema_version": 1,
                "capabilities": [_row(target_owner="packages/os_core/src/agent_os_core")],
            }
        )


def test_runtime_authority_rejects_two_owners() -> None:
    with pytest.raises(OwnershipError, match="exactly one post-migration runtime owner"):
        validate_matrix(
            {
                "schema_version": 1,
                "capabilities": [
                    _row(
                        post_migration_runtime_owners=[
                            "packages/os_core",
                            "domain_packs/data_agent",
                        ]
                    )
                ],
            }
        )


def test_shared_extraction_requires_two_named_consumers() -> None:
    with pytest.raises(OwnershipError, match="at least two consumers"):
        validate_matrix(
            {
                "schema_version": 1,
                "capabilities": [
                    _row(
                        semantic_scope="GENERIC",
                        disposition="EXTRACT_TO_SHARED_PACKAGE",
                        target_owner="packages/contracts",
                        consumer=["Data Agent only"],
                    )
                ],
            }
        )
