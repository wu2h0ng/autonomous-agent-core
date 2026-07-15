"""R-STATE-CREDIT-1 typed runner/prereg contracts and fail-closed execution."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from experiments.r_state_credit_1.contracts import (
    ArmId,
    ContractViolation,
    ProbeAction,
    ScenarioFamily,
)
from experiments.r_state_credit_1.run_contracts import (
    ArmAssessment,
    ActorBinding,
    ActorClient,
    ActorRequest,
    ActorResponse,
    ActorTransport,
    ArtifactHash,
    AuthorityBinding,
    BindingArtifactPaths,
    C7AbortSignal,
    CheckpointCase,
    CheckpointId,
    CheckpointLoss,
    CorpusBinding,
    HELD_OUT_SEEDS,
    NativeFreezeViolation,
    RFinalBatch,
    RunBindings,
    ScorerClient,
    ScorerBinding,
    VerifiedNativeFreeze,
    verify_binding_artifacts,
    verify_native_freeze,
)
from experiments.r_state_credit_1.result_runner import (
    RFinalRunReceipt,
    RunnerViolation,
    execute_r_final_once,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def _actor_binding() -> ActorBinding:
    return ActorBinding(
        transport=ActorTransport.API_ONLY,
        provider="provider.example",
        model_id="model-family",
        model_revision_or_snapshot="snapshot-2026-07-15",
        temperature=0.0,
        top_p=1.0,
        max_output_tokens=256,
        system_prompt_sha256=SHA_A,
        tool_schema_sha256=SHA_B,
    )


def _run_bindings() -> RunBindings:
    return RunBindings(
        actor=_actor_binding(),
        corpus=CorpusBinding(
            scenario_generator_sha256=SHA_C,
            public_case_manifest_sha256=SHA_D,
            sealed_referee_manifest_sha256=SHA_E,
            case_files=(ArtifactHash(path="cases/held-out-01.json", sha256=SHA_F),),
        ),
        scorer=ScorerBinding(
            scorer_source_sha256=SHA_A,
            metric_test_sha256=SHA_B,
            verdict_grammar_test_sha256=SHA_C,
        ),
        authority=AuthorityBinding(
            builder_id="codex-r-state-credit-runner",
            independent_reviewer_id="independent-reviewer",
            c7_owner_id="founder-c7-owner",
            candidate_sha256=SHA_D,
            exact_content_manifest_sha256=SHA_E,
            founder_or_cto_run_authorization_ref="decision:r-state-credit-stage-a:1",
        ),
    )


def test_actor_binding_is_api_only_closed_and_immutable() -> None:
    binding = _actor_binding()
    assert binding.transport is ActorTransport.API_ONLY
    with pytest.raises(FrozenInstanceError):
        binding.model_id = "changed"  # type: ignore[misc]
    with pytest.raises(ContractViolation, match="unknown field"):
        ActorBinding.from_mapping(
            {
                **binding.to_mapping(),
                "api_key": "secret-must-never-enter-binding",
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("transport", "CLI", "transport must be ActorTransport.API_ONLY"),
        ("provider", "", "provider must be non-empty text"),
        (
            "model_revision_or_snapshot",
            "",
            "model_revision_or_snapshot must be non-empty text",
        ),
        ("temperature", 0.1, "temperature must be exactly 0"),
        ("top_p", 0.9, "top_p must be exactly 1"),
        ("max_output_tokens", 0, "max_output_tokens must be exactly 256"),
        (
            "system_prompt_sha256",
            "missing",
            "system_prompt_sha256 must be a lowercase SHA-256",
        ),
    ],
)
def test_actor_binding_rejects_unresolved_or_drifted_values(
    field: str, value: object, message: str
) -> None:
    payload = _actor_binding().to_mapping()
    payload[field] = value
    with pytest.raises(ContractViolation, match=message):
        ActorBinding.from_mapping(payload)


def test_run_bindings_are_complete_and_have_a_stable_digest() -> None:
    bindings = _run_bindings()
    assert bindings.digest() == bindings.digest()
    assert len(bindings.digest()) == 64
    payload = bindings.to_mapping()
    del payload["corpus"]
    with pytest.raises(ContractViolation, match="missing field.*corpus"):
        RunBindings.from_mapping(payload)


def test_authority_binding_rejects_self_review_and_missing_real_authority() -> None:
    with pytest.raises(ContractViolation, match="builder and reviewer must differ"):
        AuthorityBinding(
            builder_id="same",
            independent_reviewer_id="same",
            c7_owner_id="founder",
            candidate_sha256=SHA_A,
            exact_content_manifest_sha256=SHA_B,
            founder_or_cto_run_authorization_ref="decision:1",
        )
    with pytest.raises(ContractViolation, match="founder_or_cto_run_authorization_ref"):
        AuthorityBinding(
            builder_id="builder",
            independent_reviewer_id="reviewer",
            c7_owner_id="founder",
            candidate_sha256=SHA_A,
            exact_content_manifest_sha256=SHA_B,
            founder_or_cto_run_authorization_ref="",
        )


class _ContractOnlyActor:
    binding = _actor_binding()

    def complete(self, request: ActorRequest) -> ActorResponse:
        return ActorResponse(
            request_id=request.request_id,
            provider=self.binding.provider,
            model_id=self.binding.model_id,
            model_revision_or_snapshot=self.binding.model_revision_or_snapshot,
            action=ProbeAction.ABSTAIN,
            raw_output_sha256=SHA_C,
            input_tokens=1,
            output_tokens=1,
        )


def test_actor_client_protocol_is_typed_and_carries_exact_binding() -> None:
    actor = _ContractOnlyActor()
    assert isinstance(actor, ActorClient)
    request = ActorRequest(
        request_id="run:episode:checkpoint:A0",
        run_id="run-1",
        episode_id="episode-1",
        checkpoint_id="BEFORE_PERTURBATION",
        arm_id=ArmId.A0_FULL_LOG,
        observable_digest=SHA_D,
        representation="visible representation",
        allowed_actions=tuple(ProbeAction),
        tool_schema_sha256=actor.binding.tool_schema_sha256,
    )
    response = actor.complete(request)
    assert response.action is ProbeAction.ABSTAIN
    assert response.request_id == request.request_id


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _current_head(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _native_lock_fixture(tmp_path: Path, repo_root: Path) -> tuple[Path, Path, Path]:
    source_spec = tmp_path / "prereg.yaml"
    source_spec.write_text(
        "prereg_id: R-STATE-CREDIT-1-STAGE-A-20260715\n"
        "mechanism:\n"
        "  channel_claim: X(research-automation)\n"
        "  files:\n"
        "    - experiments/r_state_credit_1/run_contracts.py\n",
        encoding="utf-8",
    )
    canonical_spec = tmp_path / "prereg.json"
    canonical_spec.write_text(
        json.dumps(
            {
                "mechanism": {
                    "channel_claim": "X(research-automation)",
                    "files": ["experiments/r_state_credit_1/run_contracts.py"],
                },
                "prereg_id": "R-STATE-CREDIT-1-STAGE-A-20260715",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    mechanism = repo_root / "experiments/r_state_credit_1/run_contracts.py"
    lock = tmp_path / "prereg.lock"
    lock.write_text(
        json.dumps(
            {
                "prereg_id": "R-STATE-CREDIT-1-STAGE-A-20260715",
                "spec_file_sha256": _sha256_file(source_spec),
                "spec_sha256": _sha256_file(canonical_spec),
                "mechanism_files": {
                    "experiments/r_state_credit_1/run_contracts.py": _sha256_file(
                        mechanism
                    )
                },
                "target_head": _current_head(repo_root),
                "frozen_at": "2026-07-15T00:00:00+00:00",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return lock, source_spec, canonical_spec


def test_native_freeze_verification_binds_raw_canonical_mechanism_and_head(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    lock, source_spec, canonical_spec = _native_lock_fixture(tmp_path, repo_root)
    verified = verify_native_freeze(
        lock_path=lock,
        source_spec_path=source_spec,
        canonical_spec_path=canonical_spec,
        target_root=repo_root,
        expected_prereg_id="R-STATE-CREDIT-1-STAGE-A-20260715",
    )
    assert isinstance(verified, VerifiedNativeFreeze)
    assert verified.lock_sha256 == _sha256_file(lock)
    assert verified.target_head == _current_head(repo_root)
    assert verified.mechanism_files == (
        ArtifactHash(
            path="experiments/r_state_credit_1/run_contracts.py",
            sha256=_sha256_file(
                repo_root / "experiments/r_state_credit_1/run_contracts.py"
            ),
        ),
    )


@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("raw_spec", "source spec hash drift"),
        ("canonical_spec", "canonical spec hash drift"),
        ("mechanism", "mechanism hash drift"),
        ("head", "target HEAD drift"),
    ],
)
def test_native_freeze_verification_fails_closed_on_any_drift(
    tmp_path: Path, drift: str, message: str
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    lock, source_spec, canonical_spec = _native_lock_fixture(tmp_path, repo_root)
    if drift == "raw_spec":
        source_spec.write_text(
            source_spec.read_text(encoding="utf-8") + "note: drift\n"
        )
    elif drift == "canonical_spec":
        canonical_spec.write_text("{}\n", encoding="utf-8")
    else:
        payload = json.loads(lock.read_text(encoding="utf-8"))
        if drift == "mechanism":
            payload["mechanism_files"][
                "experiments/r_state_credit_1/run_contracts.py"
            ] = SHA_A
        else:
            payload["target_head"] = SHA_B[:40]
        lock.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(NativeFreezeViolation, match=message):
        verify_native_freeze(
            lock_path=lock,
            source_spec_path=source_spec,
            canonical_spec_path=canonical_spec,
            target_root=repo_root,
            expected_prereg_id="R-STATE-CREDIT-1-STAGE-A-20260715",
        )


def _write_artifact(root: Path, relative: str, content: str) -> ArtifactHash:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return ArtifactHash(path=relative, sha256=_sha256_file(path))


def _canonical_json_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _execution_bindings(
    target_root: Path,
) -> tuple[RunBindings, BindingArtifactPaths, VerifiedNativeFreeze]:
    prompt = _write_artifact(
        target_root, "bindings/system-prompt.txt", "system prompt\n"
    )
    tool = _write_artifact(target_root, "bindings/tool-schema.json", "{}\n")
    generator = _write_artifact(target_root, "corpus/generator.py", "# generator\n")
    public_manifest = _write_artifact(target_root, "corpus/public.json", "{}\n")
    sealed_manifest = _write_artifact(target_root, "corpus/sealed.json", "{}\n")
    case_file = _write_artifact(target_root, "corpus/case-001.json", "{}\n")
    scorer_source = _write_artifact(target_root, "scorer/scorer.py", "# scorer\n")
    metric_test = _write_artifact(target_root, "scorer/test_metric.py", "# metric\n")
    verdict_test = _write_artifact(target_root, "scorer/test_verdict.py", "# verdict\n")
    candidate_payload = {"artifact_class": "TEST_ONLY_CANDIDATE"}
    candidate_path = target_root / "candidate.json"
    candidate_path.write_text(
        json.dumps(candidate_payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest = _write_artifact(
        target_root,
        "exact-content-manifest.json",
        '{"manifest_id":"test-only"}\n',
    )
    bindings = RunBindings(
        actor=ActorBinding(
            transport=ActorTransport.API_ONLY,
            provider="tests-only-fake-provider",
            model_id="tests-only-fake-model",
            model_revision_or_snapshot="tests-only-snapshot",
            temperature=0.0,
            top_p=1.0,
            max_output_tokens=256,
            system_prompt_sha256=prompt.sha256,
            tool_schema_sha256=tool.sha256,
        ),
        corpus=CorpusBinding(
            scenario_generator_sha256=generator.sha256,
            public_case_manifest_sha256=public_manifest.sha256,
            sealed_referee_manifest_sha256=sealed_manifest.sha256,
            case_files=(case_file,),
        ),
        scorer=ScorerBinding(
            scorer_source_sha256=scorer_source.sha256,
            metric_test_sha256=metric_test.sha256,
            verdict_grammar_test_sha256=verdict_test.sha256,
        ),
        authority=AuthorityBinding(
            builder_id="tests-only-builder",
            independent_reviewer_id="tests-only-reviewer",
            c7_owner_id="tests-only-c7-owner",
            candidate_sha256=_canonical_json_digest(candidate_payload),
            exact_content_manifest_sha256=manifest.sha256,
            founder_or_cto_run_authorization_ref="tests-only:run-authority",
        ),
    )
    paths = BindingArtifactPaths(
        system_prompt=Path(prompt.path),
        tool_schema=Path(tool.path),
        scenario_generator=Path(generator.path),
        public_case_manifest=Path(public_manifest.path),
        sealed_referee_manifest=Path(sealed_manifest.path),
        scorer_source=Path(scorer_source.path),
        metric_test=Path(metric_test.path),
        verdict_grammar_test=Path(verdict_test.path),
        candidate=Path("candidate.json"),
        exact_content_manifest=Path(manifest.path),
    )
    locked_artifacts = (
        prompt,
        tool,
        generator,
        public_manifest,
        sealed_manifest,
        case_file,
        scorer_source,
        metric_test,
        verdict_test,
        ArtifactHash(path="candidate.json", sha256=_sha256_file(candidate_path)),
    )
    freeze = VerifiedNativeFreeze(
        prereg_id="R-STATE-CREDIT-1-STAGE-A-20260715",
        lock_sha256=SHA_A,
        spec_file_sha256=SHA_B,
        spec_sha256=SHA_C,
        mechanism_files=tuple(sorted(locked_artifacts, key=lambda item: item.path)),
        target_head=SHA_D,
        frozen_at="2026-07-15T00:00:00+00:00",
    )
    return bindings, paths, freeze


def test_binding_artifact_preflight_requires_real_locked_bytes(tmp_path: Path) -> None:
    target_root = tmp_path / "target"
    target_root.mkdir()
    bindings, paths, freeze = _execution_bindings(target_root)
    verified = verify_binding_artifacts(
        bindings=bindings,
        paths=paths,
        freeze=freeze,
        target_root=target_root,
    )
    assert verified.bindings_digest == bindings.digest()
    (target_root / paths.system_prompt).write_text("drift\n", encoding="utf-8")
    with pytest.raises(ContractViolation, match="system_prompt hash drift"):
        verify_binding_artifacts(
            bindings=bindings,
            paths=paths,
            freeze=freeze,
            target_root=target_root,
        )


def _rfinal_batch(run_id: str, binding: ActorBinding) -> RFinalBatch:
    cases: list[CheckpointCase] = []
    for family in ScenarioFamily:
        for seed in HELD_OUT_SEEDS:
            episode_id = f"{family.value}:{seed}"
            for checkpoint in CheckpointId:
                observable_digest = hashlib.sha256(
                    f"{episode_id}:{checkpoint.value}".encode("utf-8")
                ).hexdigest()
                requests = tuple(
                    ActorRequest(
                        request_id=(
                            f"{run_id}:{episode_id}:{checkpoint.value}:{arm_id.value}"
                        ),
                        run_id=run_id,
                        episode_id=episode_id,
                        checkpoint_id=checkpoint.value,
                        arm_id=arm_id,
                        observable_digest=observable_digest,
                        representation=(
                            f"tests-only:{episode_id}:{checkpoint.value}:{arm_id.value}"
                        ),
                        allowed_actions=tuple(ProbeAction),
                        tool_schema_sha256=binding.tool_schema_sha256,
                    )
                    for arm_id in ArmId
                )
                cases.append(
                    CheckpointCase(
                        episode_id=episode_id,
                        family=family,
                        seed=seed,
                        checkpoint_id=checkpoint,
                        actor_requests=requests,
                    )
                )
    return RFinalBatch(run_id=run_id, cases=tuple(cases))


def test_rfinal_batch_requires_exact_family_seed_checkpoint_and_arm_coverage() -> None:
    batch = _rfinal_batch("test-run", _actor_binding())
    assert len(batch.cases) == len(ScenarioFamily) * len(HELD_OUT_SEEDS) * len(
        CheckpointId
    )
    with pytest.raises(ContractViolation, match="exact held-out coverage"):
        RFinalBatch(run_id=batch.run_id, cases=batch.cases[:-1])


class _FakeActor:
    def __init__(
        self,
        binding: ActorBinding,
        *,
        interrupt_on_call: int | None = None,
    ) -> None:
        self.binding = binding
        self.calls = 0
        self.interrupt_on_call = interrupt_on_call

    def complete(self, request: ActorRequest) -> ActorResponse:
        self.calls += 1
        if self.interrupt_on_call == self.calls:
            raise KeyboardInterrupt("tests-only interruption")
        return ActorResponse(
            request_id=request.request_id,
            provider=self.binding.provider,
            model_id=self.binding.model_id,
            model_revision_or_snapshot=self.binding.model_revision_or_snapshot,
            action=ProbeAction.ABSTAIN,
            raw_output_sha256=hashlib.sha256(
                f"tests-only:{request.request_id}".encode("utf-8")
            ).hexdigest(),
            input_tokens=1,
            output_tokens=1,
        )


class _FakeScorer:
    def __init__(self, binding: ScorerBinding) -> None:
        self.binding = binding
        self.calls = 0

    def assess(
        self,
        case: CheckpointCase,
        responses: tuple[ActorResponse, ...],
    ) -> tuple[ArmAssessment, ...]:
        self.calls += 1
        return tuple(
            ArmAssessment(arm_id=response_arm.arm_id, loss=CheckpointLoss.CORRECT)
            for response_arm in case.actor_requests
        )


class _UntypedScorer:
    def __init__(self, binding: ScorerBinding) -> None:
        self.binding = binding

    def assess(
        self,
        case: CheckpointCase,
        responses: tuple[ActorResponse, ...],
    ) -> tuple[object, ...]:
        return (object(),) * len(case.actor_requests)


class _FakeC7:
    def __init__(self, owner_id: str, *, abort_on_check: int | None = None) -> None:
        self.owner_id = owner_id
        self.abort_on_check = abort_on_check
        self.checks = 0

    def abort_requested(self) -> bool:
        self.checks += 1
        return self.abort_on_check == self.checks


def test_fake_dependencies_satisfy_typed_protocols() -> None:
    bindings = _run_bindings()
    assert isinstance(_FakeActor(bindings.actor), ActorClient)
    assert isinstance(_FakeScorer(bindings.scorer), ScorerClient)
    assert isinstance(_FakeC7(bindings.authority.c7_owner_id), C7AbortSignal)


def test_rfinal_runner_writes_raw_once_without_verdict_and_forbids_rerun(
    tmp_path: Path,
) -> None:
    target_root = tmp_path / "target"
    target_root.mkdir()
    bindings, paths, freeze = _execution_bindings(target_root)
    batch = _rfinal_batch("tests-only-run", bindings.actor)
    actor = _FakeActor(bindings.actor)
    scorer = _FakeScorer(bindings.scorer)
    c7 = _FakeC7(bindings.authority.c7_owner_id)
    run_dir = tmp_path / "run"
    receipt = execute_r_final_once(
        run_dir=run_dir,
        target_root=target_root,
        bindings=bindings,
        binding_artifact_paths=paths,
        freeze=freeze,
        batch=batch,
        actor=actor,
        scorer=scorer,
        c7=c7,
    )
    assert isinstance(receipt, RFinalRunReceipt)
    payload = json.loads(receipt.result_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "r-state-credit-1-rfinal-raw-v1"
    assert payload["status"] == "RAW_NOT_ADJUDICATED"
    assert len(payload["rows"]) == len(batch.cases) * len(ArmId)
    rendered = json.dumps(payload, sort_keys=True)
    for forbidden in ("verdict", "winner", "MET", "NOT_MET"):
        assert forbidden not in rendered
    assert actor.calls == len(batch.cases) * len(ArmId)
    assert scorer.calls == len(batch.cases)
    with pytest.raises(RunnerViolation, match="RERUN_FORBIDDEN"):
        execute_r_final_once(
            run_dir=run_dir,
            target_root=target_root,
            bindings=bindings,
            binding_artifact_paths=paths,
            freeze=freeze,
            batch=batch,
            actor=_FakeActor(bindings.actor),
            scorer=_FakeScorer(bindings.scorer),
            c7=_FakeC7(bindings.authority.c7_owner_id),
        )


def test_post_start_c7_abort_is_terminal_and_same_lock_cannot_rerun(
    tmp_path: Path,
) -> None:
    target_root = tmp_path / "target"
    target_root.mkdir()
    bindings, paths, freeze = _execution_bindings(target_root)
    batch = _rfinal_batch("tests-only-c7", bindings.actor)
    actor = _FakeActor(bindings.actor)
    run_dir = tmp_path / "run"
    with pytest.raises(RunnerViolation, match="INVALID_C7_ABORT"):
        execute_r_final_once(
            run_dir=run_dir,
            target_root=target_root,
            bindings=bindings,
            binding_artifact_paths=paths,
            freeze=freeze,
            batch=batch,
            actor=actor,
            scorer=_FakeScorer(bindings.scorer),
            c7=_FakeC7(bindings.authority.c7_owner_id, abort_on_check=3),
        )
    terminal = json.loads(
        (run_dir / "rfinal.terminal.json").read_text(encoding="utf-8")
    )
    assert terminal["status"] == "INVALID_C7_ABORT_NO_SAME_LOCK_RERUN"
    assert actor.calls == 1
    assert not (run_dir / "rfinal.result.json").exists()
    with pytest.raises(RunnerViolation, match="RERUN_FORBIDDEN"):
        execute_r_final_once(
            run_dir=run_dir,
            target_root=target_root,
            bindings=bindings,
            binding_artifact_paths=paths,
            freeze=freeze,
            batch=batch,
            actor=_FakeActor(bindings.actor),
            scorer=_FakeScorer(bindings.scorer),
            c7=_FakeC7(bindings.authority.c7_owner_id),
        )


def test_interruption_after_atomic_start_is_terminal_and_cannot_rerun(
    tmp_path: Path,
) -> None:
    target_root = tmp_path / "target"
    target_root.mkdir()
    bindings, paths, freeze = _execution_bindings(target_root)
    batch = _rfinal_batch("tests-only-interrupt", bindings.actor)
    run_dir = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt, match="tests-only interruption"):
        execute_r_final_once(
            run_dir=run_dir,
            target_root=target_root,
            bindings=bindings,
            binding_artifact_paths=paths,
            freeze=freeze,
            batch=batch,
            actor=_FakeActor(bindings.actor, interrupt_on_call=1),
            scorer=_FakeScorer(bindings.scorer),
            c7=_FakeC7(bindings.authority.c7_owner_id),
        )
    terminal = json.loads(
        (run_dir / "rfinal.terminal.json").read_text(encoding="utf-8")
    )
    assert terminal["status"] == "INTERRUPTED_NO_SAME_LOCK_RERUN"
    with pytest.raises(RunnerViolation, match="RERUN_FORBIDDEN"):
        execute_r_final_once(
            run_dir=run_dir,
            target_root=target_root,
            bindings=bindings,
            binding_artifact_paths=paths,
            freeze=freeze,
            batch=batch,
            actor=_FakeActor(bindings.actor),
            scorer=_FakeScorer(bindings.scorer),
            c7=_FakeC7(bindings.authority.c7_owner_id),
        )


def test_untyped_scorer_output_invalidates_started_run_fail_closed(
    tmp_path: Path,
) -> None:
    target_root = tmp_path / "target"
    target_root.mkdir()
    bindings, paths, freeze = _execution_bindings(target_root)
    batch = _rfinal_batch("tests-only-untyped-scorer", bindings.actor)
    run_dir = tmp_path / "run"
    with pytest.raises(RunnerViolation, match="untyped assessment"):
        execute_r_final_once(
            run_dir=run_dir,
            target_root=target_root,
            bindings=bindings,
            binding_artifact_paths=paths,
            freeze=freeze,
            batch=batch,
            actor=_FakeActor(bindings.actor),
            scorer=_UntypedScorer(bindings.scorer),  # type: ignore[arg-type]
            c7=_FakeC7(bindings.authority.c7_owner_id),
        )
    terminal = json.loads(
        (run_dir / "rfinal.terminal.json").read_text(encoding="utf-8")
    )
    assert terminal["status"] == "INVALID_RUNNER_CONTRACT_NO_SAME_LOCK_RERUN"


FORMAL_PREREG = Path(
    "docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREGISTRATION-2026-07-15.yaml"
)
EXACT_CONTENT_MANIFEST = Path(
    "docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.EXACT-CONTENT-MANIFEST-2026-07-15.json"
)


def _workflow_root(repo_root: Path) -> Path:
    common_raw = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    common = Path(common_raw)
    if not common.is_absolute():
        common = (repo_root / common).resolve()
    workflow = common.parent.parent / "ai-agent-engineering-workflow"
    if not (workflow / "src/agent_workflow_runner/cli.py").is_file():
        pytest.skip("native workflow-runner sibling is unavailable")
    return workflow


def _workflow_env(workflow_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    prior = env.get("PYTHONPATH")
    source = str(workflow_root / "src")
    env["PYTHONPATH"] = source if not prior else f"{source}{os.pathsep}{prior}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _workflow_python(workflow_root: Path) -> str:
    interpreter = workflow_root / ".venv/bin/python"
    if not interpreter.is_file():
        pytest.skip("native workflow-runner interpreter is unavailable")
    return str(interpreter)


def _load_formal_spec(repo_root: Path) -> dict[str, Any]:
    workflow = _workflow_root(repo_root)
    script = """
import json
import sys
from pathlib import Path
import yaml
value = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(json.dumps(value, sort_keys=True))
"""
    completed = subprocess.run(
        [_workflow_python(workflow), "-c", script, str(repo_root / FORMAL_PREREG)],
        cwd=workflow,
        env=_workflow_env(workflow),
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


def test_formal_prereg_is_native_schema_and_explicitly_unbound() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    spec_path = repo_root / FORMAL_PREREG
    spec = _load_formal_spec(repo_root)
    assert spec["prereg_id"] == "R-STATE-CREDIT-1-STAGE-A-20260715"
    assert spec["status"] == "DRAFT_BINDINGS_REQUIRED_NOT_REVIEWED_NOT_FROZEN_NOT_RUN"
    assert spec["claim_class"] == "research-automation"
    mechanism = spec["mechanism"]
    assert mechanism["channel_claim"] == "X(research-automation)"
    assert mechanism["files"]
    assert len(mechanism["files"]) == len(set(mechanism["files"]))
    for required in (
        "experiments/r_state_credit_1/run_contracts.py",
        "experiments/r_state_credit_1/result_runner.py",
        "tests/test_r_state_credit_1_runner_prereg.py",
        "docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREG-CANDIDATE-2026-07-15.json",
    ):
        assert required in mechanism["files"]
    readiness = spec["binding_readiness"]
    assert readiness["status"] == "DRAFT_BINDINGS_REQUIRED"
    assert set(readiness["unresolved_contracts"]) == {
        "ACTOR_BINDING",
        "CORPUS_BINDING",
        "SCORER_BINDING",
        "REVIEW_AND_RUN_AUTHORITY_BINDING",
    }
    assert spec["execution"]["result_bearing_execution_authorized"] is False
    assert spec["execution"]["provider_call_authorized"] is False
    assert spec["execution"]["cli_entrypoint"] == "ABSENT_BY_DESIGN"
    rendered = spec_path.read_text(encoding="utf-8")
    for forbidden in ("TBD", "TODO", "PLACEHOLDER", "0" * 64):
        assert forbidden not in rendered


def test_exact_content_manifest_covers_formal_mechanism_bytes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    spec = _load_formal_spec(repo_root)
    manifest = json.loads(
        (repo_root / EXACT_CONTENT_MANIFEST).read_text(encoding="utf-8")
    )
    mechanism_hashes = manifest["mechanism_artifact_hashes"]
    assert set(mechanism_hashes) == set(spec["mechanism"]["files"])
    for relative, expected in mechanism_hashes.items():
        assert _sha256_file(repo_root / relative) == expected
    supporting = manifest["supporting_artifact_hashes"]
    assert supporting == {}, (
        "the native lock binds raw/canonical spec bytes; hashing the spec from the "
        "manifest would create a cycle once the spec binds the manifest digest"
    )
    assert EXACT_CONTENT_MANIFEST.as_posix() not in mechanism_hashes


def test_native_workflow_runner_computes_same_freeze_digest_without_writes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workflow = _workflow_root(repo_root)
    script = """
import json
import sys
from pathlib import Path
from agent_workflow_runner.prereg_review import compute_freeze_digest
root = Path(sys.argv[1])
spec = Path(sys.argv[2])
print(json.dumps(compute_freeze_digest(workspace_root=root, spec_path=spec, target_dir=root), sort_keys=True))
"""
    completed = subprocess.run(
        [
            _workflow_python(workflow),
            "-c",
            script,
            str(repo_root),
            str(repo_root / FORMAL_PREREG),
        ],
        cwd=workflow,
        env=_workflow_env(workflow),
        check=True,
        capture_output=True,
        text=True,
    )
    digest = json.loads(completed.stdout)
    spec = _load_formal_spec(repo_root)
    manifest = json.loads(
        (repo_root / EXACT_CONTENT_MANIFEST).read_text(encoding="utf-8")
    )
    assert digest["prereg_id"] == spec["prereg_id"]
    assert digest["mechanism_file_hashes"] == manifest["mechanism_artifact_hashes"]


def test_native_manifest_verify_passes_and_freeze_still_refuses_without_reviews(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workflow = _workflow_root(repo_root)
    env = _workflow_env(workflow)
    manifest_check = subprocess.run(
        [
            _workflow_python(workflow),
            "-m",
            "agent_workflow_runner.cli",
            "prereg",
            "manifest-verify",
            "--workspace-root",
            str(repo_root),
            "--manifest",
            str(repo_root / EXACT_CONTENT_MANIFEST),
        ],
        cwd=workflow,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    manifest_receipt = json.loads(manifest_check.stdout)
    assert manifest_receipt["intact"] is True
    run_id = "tests-only-native-freeze-refusal"
    run_dir = tmp_path / ".agent_runs" / run_id
    run_dir.mkdir(parents=True)
    freeze = subprocess.run(
        [
            _workflow_python(workflow),
            "-m",
            "agent_workflow_runner.cli",
            "prereg",
            "freeze",
            "--workspace-root",
            str(tmp_path),
            "--run-id",
            run_id,
            "--spec",
            str(repo_root / FORMAL_PREREG),
            "--target",
            str(repo_root),
            "--frozen-by",
            "tests-only-freezer",
        ],
        cwd=workflow,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert freeze.returncode == 1
    refusal = json.loads(freeze.stdout)
    assert refusal["status"] == "denied"
    assert "no review acceptance found" in refusal["reason"]
    assert not (run_dir / "prereg.lock").exists()
    assert not (run_dir / "prereg.json").exists()
