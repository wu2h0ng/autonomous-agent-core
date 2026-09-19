"""Quarantine manifest for tests/product_eval (P3 shard, 2026-09-19).

Each entry pairs a bucket reason with the exact test nodeids that cannot run in this
repo's offline CI because they depend on an asset this repo does not materialize (or
are a DESIGN_ONLY research candidate whose binding has drifted and needs a re-freeze).

The conftest hook applies the `quarantine` mark (carrying the reason) to every nodeid
listed here, turning it into a skip that always prints its reason. This is a single,
reviewable list -- never a silent skip.

Quarantine hygiene (founder ruling 6, 2026-09-19): every bucket now carries
  * ``reason``    -- what asset is missing and why it cannot run offline;
  * ``owner``     -- the team/role responsible for lifting it;
  * ``review_by`` -- an ISO date by which the quarantine must be re-adjudicated
                     (lifted, re-hermeticized, or re-dated). A quarantine with no
                     expiry is a silent permanent skip and is rejected.

LIFTED in this shard: the former 83-item ``cross_repo`` runner-contract bucket was
hermeticized -- the pinned sibling runner contract surface is vendored at
``tests/product_eval/fixtures/hermetic_runner/`` (closed TeamEvent schema, public
record builder, and the init/permission/team-event CLI writing the same
``.agent_runs`` ledger layout), wrapped in a clean git repo on the pinned branch
name and wired via the conftest ``hermetic_runner`` fixture. Only the 3 nodeids that
hard-code the *real* sibling repo identity (its ``.git`` common-dir path and a
receipt baked at the exact pinned SHA) remain quarantined -- a hermetic substitute
cannot be that exact external repo.
"""

from __future__ import annotations

QUARANTINE_BUCKETS: dict[str, dict[str, object]] = {
    # 3 nodeids that assert the runner IS the real pinned sibling repo by its exact
    # on-disk identity (common_dir == <sibling>/.git, and a receipt baked at
    # 50eb4d27...). A hermetic fixture cannot reproduce that external identity.
    "cross_repo_identity": {
        "reason": (
            "cross-repo runner identity: this node asserts the runner is the exact "
            "sibling worktree ai-agent-engineering-workflow/.worktrees/team-event-"
            "contract-v1-20260713 pinned at 50eb4d27... by its .git common-dir path "
            "and/or a receipt baked at that SHA. The vendored hermetic_runner fixture "
            "reproduces the runner CONTRACT (schema, record builder, ledger layout) "
            "but cannot be that exact external repo. The consumer-side qualification "
            "logic it guards is covered by the other hermeticized mutation tests. "
            "Lift only when the real pinned worktree is checked out at the exact SHA."
        ),
        "owner": "agent-os/runtime",
        "review_by": "2026-10-19",
        "nodeids": [
            "tests/product_eval/test_runner_contract_qualification.py::test_real_pinned_runner_canary_binds_schema_fixture_sources_and_import",
            "tests/product_eval/test_spine_e2e_4_assets.py::test_combined_receipt_binds_identity_provider_and_runner_contract",
            "tests/product_eval/test_spine_e2e_4_assets.py::test_runner_schema_snapshot_is_exact_live_export_not_a_handwritten_projection",
        ],
    },
    "docker": {
        "reason": (
            "needs a Docker daemon plus the SRL falsifier's allowed immutable worker "
            "image, neither of which ships in this offline repo/CI host. The test "
            "asserts real-container isolation (pid/mem/tmpfs caps, no-network, host-env "
            "absence) and fails closed when the image is unavailable. Lift only in an "
            "environment with Docker + the pinned image, or after the container "
            "isolation surface is hermeticized behind a fake docker subprocess."
        ),
        "owner": "agent-os/srl",
        "review_by": "2026-10-19",
        "nodeids": [
            "tests/product_eval/test_srl_docker_exec.py::test_cleanup_failure_cannot_return_success",
            "tests/product_eval/test_srl_docker_exec.py::test_container_name_change_cannot_redirect_id_lifecycle",
            "tests/product_eval/test_srl_docker_exec.py::test_invalid_cidfile_uses_name_label_fallback_and_leaves_nothing",
            "tests/product_eval/test_srl_docker_exec.py::test_malformed_create_stdout_uses_exact_cidfile_identity",
            "tests/product_eval/test_srl_docker_exec.py::test_nonreading_worker_cannot_block_stdin_or_escape_deadline",
            "tests/product_eval/test_srl_docker_exec.py::test_output_cap_rejects_before_receipt_parse",
            "tests/product_eval/test_srl_docker_exec.py::test_policy_ceiling_is_fixed_and_contains_no_host_authority",
            "tests/product_eval/test_srl_docker_exec.py::test_policy_worker_and_receipt_mutation_fail_closed",
            "tests/product_eval/test_srl_docker_exec.py::test_real_host_workspace_home_and_environment_are_absent",
            "tests/product_eval/test_srl_docker_exec.py::test_real_no_network_blocks_connection_to_live_host_listener",
            "tests/product_eval/test_srl_docker_exec.py::test_real_pid_memory_and_tmpfs_limits_fail_closed",
            "tests/product_eval/test_srl_docker_exec.py::test_real_pure_worker_success_is_exactly_bound_and_container_removed",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_cannot_bypass_seal_controlled_receipt_without_identity_bindings",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_controlled_receipt_carries_docker_execution_cleanup_integrity",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_controlled_receipt_full_identity_binding_is_content_addressed",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_controlled_receipt_rejects_mismatched_image_identity",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_controlled_receipt_rejects_mismatched_policy_digest",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_controlled_receipt_rejects_mismatched_public_state",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_controlled_receipt_rejects_mismatched_worker_digest",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_controlled_receipt_rejects_unbounded_arm_id",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_controlled_receipt_unit_and_arm_digests_are_distinct",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_direct_docker_execution_without_harness_context_is_not_controlled",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_execute_and_seal_ignores_overridden_factory_instance",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_execute_and_seal_propagates_docker_os_failure",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_local_docker_and_controlled_receipts_remain_proposal_only",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_mismatched_receipt_digest_fails_before_scoring",
            "tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py::test_trusted_receipt_ceiling_rejects_raw_identity_drift",
        ],
    },
    "live_provider": {
        "reason": (
            "needs a bound live provider configuration snapshot (AGENT_OS_PROVIDER_"
            "PROFILE + _BASE_URL/_MODEL/_API_KEY) to hit the frozen wire. This repo "
            "has no live key; the test asserts the real provider arm matches a frozen "
            "wire. The offline gating eval arm is the recorded/replay (cassette) arm "
            "in test_terminal_coding_eval_replay.py; this live arm is explicitly "
            "optional and never enters the CI gate. Lift only with a provisioned, "
            "billable provider profile."
        ),
        "owner": "agent-os/provider",
        "review_by": "2026-10-19",
        "nodeids": [
            "tests/product_eval/test_provider_bank.py::test_real_application_provider_wire_matches_frozen_single_case",
            "tests/product_eval/test_provider_bank.py::test_real_openai_compatible_provider_hits_frozen_wire",
            "tests/product_eval/test_spine_protocol.py::test_real_single_case_prepare_interrupt_and_immediate_probe",
        ],
    },
    "drift_research_candidate": {
        "reason": (
            "offline deterministic but a DESIGN_ONLY / CANDIDATE (not accepted, not "
            "frozen, not run-authority) research artifact whose binding has drifted "
            "from product evolution on the child-agent frame-gates branch (WorkflowGraph "
            "now emits dag_v1 and the candidate assumes conditional edges the dag_v1 "
            "model still rejects; fixed_baseline lifecycle + source-byte hash bindings "
            "also moved). Re-bending the literal here would falsify the frozen research "
            "anchor. Lift only after an explicit D1-E/D1-F re-freeze and re-adjudication."
        ),
        "owner": "agent-os/research",
        "review_by": "2026-11-19",
        "nodeids": [
            "tests/product_eval/test_lh1a_combined_d1.py::test_source_bindings_match_current_in_repo_bytes",
            "tests/product_eval/test_lh1a_design.py::test_candidate_initial_and_regime_templates_freeze_only_the_suffix",
            "tests/product_eval/test_lh1a_design.py::test_d1e_source_has_no_early_material_old_identity_or_digest_constants",
            "tests/product_eval/test_lh1a_design.py::test_public_application_accepts_only_same_identity_prefix_preserving_replan",
            "tests/product_eval/test_lh1a_design.py::test_restart_has_identical_information_budget_and_human_charge",
            "tests/product_eval/test_spine_e2e_4_scratch_cli.py::test_scratch_fixture_is_disjoint_from_absent_formal_output_ledgers",
            "tests/product_eval/test_spine_protocol.py::test_harness_rejects_private_product_organs_and_dynamic_reflection",
        ],
    },
}
