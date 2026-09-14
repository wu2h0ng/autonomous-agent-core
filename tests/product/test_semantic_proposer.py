"""Tests for SemanticProposer (Stage 2)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from agent_os_contracts import (
    CheckType,
    PredicateKind,
    ProviderResponse,
    ProviderUsage,
)

from agent_os_core.provider import DeterministicProvider
from agent_os_core.semantic_proposer import (
    MAX_SEMANTIC_PREDICATES,
    SemanticProposalError,
    SemanticProposer,
    _parse_predicate_array,
    _strip_markdown_fences,
    _validate_predicates,
)


def _make_response(text: str) -> ProviderResponse:
    from datetime import datetime, timezone
    from uuid import uuid4

    return ProviderResponse(
        response_id=f"resp:{uuid4()}",
        request_id=f"req:{uuid4()}",
        text=text,
        tool_proposals=(),
        usage=ProviderUsage(input_tokens=100, output_tokens=50, total_tokens=150, estimated_cost_usd=Decimal("0")),
        finish_reason="stop",
        received_at=datetime.now(timezone.utc),
    )


def _good_predicate_dict(pid: str = "pred:sem:001") -> dict:
    return {
        "predicate_id": pid,
        "kind": "SEMANTIC",
        "description": "The deliverable contains a valid order ID",
        "check_type": "REGEX",
        "check_params": {"pattern": r"^ORD-\d+$"},
        "evidence_bindings": [
            {
                "binding_id": "bind:1",
                "source_type": "ARTIFACT",
                "source_selector": "output.json",
                "extract_path": "$.order_id",
                "relation": "proves order ID exists",
            }
        ],
        "confidence": 0.9,
        "falsifiable": False,
        "blocking": False,
        "source": "llm:test-model",
        "meta_template": "schema",
        "scope_tags": [],
    }


class TestStripMarkdownFences:
    def test_plain_json(self):
        assert _strip_markdown_fences('[1, 2]') == '[1, 2]'

    def test_json_fence(self):
        assert _strip_markdown_fences('```json\n[1, 2]\n```') == '[1, 2]'

    def test_plain_fence(self):
        assert _strip_markdown_fences('```\n[1, 2]\n```') == '[1, 2]'


class TestParsePredicateArray:
    def test_valid_array(self):
        items = _parse_predicate_array('[{"a": 1}]')
        assert items == [{"a": 1}]

    def test_array_with_prose_around(self):
        text = 'Here is the result:\n[{"a": 1}]\nDone.'
        items = _parse_predicate_array(text)
        assert items == [{"a": 1}]

    def test_fenced_array(self):
        items = _parse_predicate_array('```json\n[{"a": 1}]\n```')
        assert items == [{"a": 1}]

    def test_non_array_raises(self):
        with pytest.raises(ValueError):
            _parse_predicate_array('{"not": "array"}')

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_predicate_array('not json at all')


class TestValidatePredicates:
    def test_valid_predicate(self):
        items = [_good_predicate_dict()]
        preds = _validate_predicates(items, "test-model")
        assert len(preds) == 1
        assert preds[0].kind is PredicateKind.SEMANTIC
        assert preds[0].source == "llm:test-model"
        assert preds[0].falsifiable is False
        assert preds[0].blocking is False
        assert preds[0].scope_tags == ()

    def test_overrides_llm_provenance_fields(self):
        d = _good_predicate_dict()
        d["kind"] = "STRUCTURAL"  # LLM tries to set STRUCTURAL
        d["source"] = "llm:other-model"
        d["falsifiable"] = True
        d["blocking"] = True
        d["scope_tags"] = ["domain:x"]
        preds = _validate_predicates([d], "test-model")
        assert preds[0].kind is PredicateKind.SEMANTIC
        assert preds[0].source == "llm:test-model"
        assert preds[0].falsifiable is False
        assert preds[0].blocking is False
        assert preds[0].scope_tags == ()

    def test_confidence_is_clamped_below_full(self):
        d = _good_predicate_dict()
        d["confidence"] = 1.0
        preds = _validate_predicates([d], "test-model")
        assert preds[0].confidence < 1.0

    def test_model_id_collision_is_rewritten_to_content_ids(self):
        # A model cannot choose/collide predicate ids: they are recomputed from
        # content, so two same-id but different-content predicates stay distinct.
        a = _good_predicate_dict("pred:SAME")
        b = _good_predicate_dict("pred:SAME")
        b["description"] = "HIDDEN condition"
        b["check_params"] = {"pattern": "^HIDDEN$"}
        preds = _validate_predicates([a, b], "test-model")
        ids = [p.predicate_id for p in preds]
        assert len(ids) == 2
        assert len(set(ids)) == 2
        assert "pred:SAME" not in ids

    def test_identical_duplicate_content_is_deduped(self):
        a = _good_predicate_dict("pred:one")
        b = _good_predicate_dict("pred:two")  # identical content, different id
        preds = _validate_predicates([a, b], "test-model")
        assert len(preds) == 1

    def test_non_castable_confidence_fails_closed(self):
        bad = _good_predicate_dict()
        bad["confidence"] = [1]
        good = _good_predicate_dict("pred:good")
        preds = _validate_predicates([bad, good], "test-model")
        # The malformed item is dropped; the valid one survives.
        assert len(preds) == 1
        assert isinstance(preds[0].confidence, float)

    def test_invalid_predicate_skipped(self):
        good = _good_predicate_dict("pred:good")
        bad = _good_predicate_dict("pred:bad")
        bad["check_type"] = "INVALID_TYPE"
        preds = _validate_predicates([good, bad], "test-model")
        assert len(preds) == 1
        assert preds[0].predicate_id.startswith("pred:")

    def test_all_invalid_raises(self):
        bad = _good_predicate_dict()
        bad["check_type"] = "INVALID_TYPE"
        with pytest.raises(SemanticProposalError, match="no valid predicates"):
            _validate_predicates([bad], "test-model")

    def test_max_count_enforced(self):
        items = []
        for i in range(20):
            d = _good_predicate_dict(f"pred:{i}")
            d["check_params"] = {"pattern": f"^ITEM-{i}$"}  # distinct content
            items.append(d)
        preds = _validate_predicates(items, "test-model")
        assert len(preds) == MAX_SEMANTIC_PREDICATES

    def test_missing_predicate_id_auto_assigned(self):
        d = _good_predicate_dict()
        del d["predicate_id"]
        preds = _validate_predicates([d], "test-model")
        assert preds[0].predicate_id.startswith("pred:")


class TestSemanticProposer:
    def test_successful_proposal(self):
        response_text = json.dumps([_good_predicate_dict()])
        provider = DeterministicProvider(text=response_text)
        proposer = SemanticProposer(provider, model_id="test-model")
        preds = proposer.propose(
            mandate_text="Create an order",
            tool_schemas=[{"tool_name": "create_order"}],
            structural_predicates=[],
        )
        assert len(preds) == 1
        assert preds[0].check_type is CheckType.REGEX

    def test_retry_on_invalid_json(self):
        good_text = json.dumps([_good_predicate_dict()])
        provider = DeterministicProvider(
            scripted=(("not json", ()), (good_text, ()))
        )
        proposer = SemanticProposer(provider, model_id="test-model")
        preds = proposer.propose(
            mandate_text="test",
            tool_schemas=[],
            structural_predicates=[],
        )
        assert len(preds) == 1

    def test_fatal_after_two_failures(self):
        provider = DeterministicProvider(
            scripted=(("bad1", ()), ("bad2", ()))
        )
        proposer = SemanticProposer(provider, model_id="test-model")
        with pytest.raises(SemanticProposalError, match="semantic_proposal_failed"):
            proposer.propose(
                mandate_text="test",
                tool_schemas=[],
                structural_predicates=[],
            )

    def test_fenced_response_parsed(self):
        response_text = "```json\n" + json.dumps([_good_predicate_dict()]) + "\n```"
        provider = DeterministicProvider(text=response_text)
        proposer = SemanticProposer(provider, model_id="test-model")
        preds = proposer.propose("test", [], [])
        assert len(preds) == 1

    def test_prompt_includes_mandate_and_rules(self):
        captured_messages = []

        class CapturingProvider(DeterministicProvider):
            def complete(self, request):
                captured_messages.extend(request.messages)
                return super().complete(request)

        response_text = json.dumps([_good_predicate_dict()])
        provider = CapturingProvider(text=response_text)
        proposer = SemanticProposer(provider, model_id="test-model")
        proposer.propose(
            mandate_text="Send an email to the supplier",
            tool_schemas=[{"tool_name": "send_email"}],
            structural_predicates=[],
        )
        user_msg = captured_messages[1].content
        assert "Send an email to the supplier" in user_msg
        assert "R1:" in user_msg
        assert "R9:" in user_msg
