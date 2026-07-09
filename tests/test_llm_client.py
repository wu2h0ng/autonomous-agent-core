"""Tests for src/aac/llm_client.py — no real API key required."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from aac.llm_client import (
    AnthropicBackend,
    OpenAIBackend,
    StubFallbackBackend,
    build_backend,
)
from aac.plumbing_instrument import PlumbingInstrument


def _anthropic_response(content: list[dict], stop_reason: str = "end_turn") -> bytes:
    return json.dumps(
        {"content": content, "stop_reason": stop_reason, "id": "test"}
    ).encode("utf-8")


def _openai_response(message: dict, finish_reason: str = "stop") -> bytes:
    return json.dumps(
        {"choices": [{"message": message, "finish_reason": finish_reason}]}
    ).encode("utf-8")


class TestBuildBackend(unittest.TestCase):
    def test_stub_when_no_key(self) -> None:
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            os.environ.pop(key, None)
        backend = build_backend("anthropic")
        self.assertTrue(getattr(backend, "stub_only", False))
        self.assertIsInstance(backend, StubFallbackBackend)

    def test_stub_provider_explicit(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        backend = build_backend("stub")
        self.assertTrue(getattr(backend, "stub_only", False))
        del os.environ["ANTHROPIC_API_KEY"]

    def test_anthropic_when_key_present(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        backend = build_backend("anthropic")
        self.assertFalse(getattr(backend, "stub_only", True))
        self.assertIsInstance(backend, AnthropicBackend)
        del os.environ["ANTHROPIC_API_KEY"]

    def test_openai_when_key_present(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        backend = build_backend("openai")
        self.assertFalse(getattr(backend, "stub_only", True))
        self.assertIsInstance(backend, OpenAIBackend)
        del os.environ["OPENAI_API_KEY"]

    @patch("aac.llm_client._http_post")
    def test_custom_api_url_from_env(self, mock_post: MagicMock) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        os.environ["ANTHROPIC_API_URL"] = "https://api.kimi.com/coding/v1/messages"
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir)
        try:
            backend = build_backend("anthropic", cache_dir=tmpdir)
            mock_post.return_value = _anthropic_response(
                [{"type": "text", "text": '{"final_answer": {"edges": []}}'}]
            )
            backend.call("prompt")
            called_url = mock_post.call_args[0][0]
            self.assertEqual(called_url, "https://api.kimi.com/coding/v1/messages")
        finally:
            del os.environ["ANTHROPIC_API_KEY"]
            del os.environ["ANTHROPIC_API_URL"]

    @patch("aac.llm_client._http_post")
    def test_custom_model_from_env(self, mock_post: MagicMock) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["OPENAI_MODEL"] = "kimi-k2-0711-preview"
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir)
        try:
            backend = build_backend("openai", cache_dir=tmpdir)
            mock_post.return_value = _openai_response(
                {"role": "assistant", "content": '{"final_answer": {"edges": []}}'}
            )
            backend.call("prompt")
            sent_body = json.loads(mock_post.call_args[0][2])
            self.assertEqual(sent_body["model"], "kimi-k2-0711-preview")
        finally:
            del os.environ["OPENAI_API_KEY"]
            del os.environ["OPENAI_MODEL"]


class TestAnthropicBackend(unittest.TestCase):
    def _backend(
        self, instrument: PlumbingInstrument | None = None, cache_dir: str | None = None
    ) -> AnthropicBackend:
        if cache_dir is None:
            cache_dir = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, cache_dir)
        return AnthropicBackend(
            api_key="sk-test",
            model="claude-sonnet-4-20250514",
            cache_dir=cache_dir,
            instrument=instrument,
        )

    @patch("aac.llm_client._http_post")
    def test_tool_call_parsing(self, mock_post: MagicMock) -> None:
        body = _anthropic_response(
            [
                {
                    "type": "tool_use",
                    "name": "info_gain",
                    "input": {"n_mc_samples": 5},
                }
            ]
        )
        mock_post.return_value = body
        backend = self._backend()
        resp = backend.call("tool prompt", tools=[{"name": "info_gain"}])
        self.assertEqual(resp.get("tool_call", {}).get("name"), "info_gain")
        self.assertEqual(resp.get("tool_call", {}).get("arguments"), {"n_mc_samples": 5})

    @patch("aac.llm_client._http_post")
    def test_final_answer_parsing(self, mock_post: MagicMock) -> None:
        body = _anthropic_response(
            [{"type": "text", "text": '{"final_answer": {"edges": [[0, 1, 0.9]]}}'}]
        )
        mock_post.return_value = body
        backend = self._backend()
        resp = backend.call("final prompt")
        self.assertEqual(
            resp.get("final_answer", {}).get("edges"), [[0, 1, 0.9]]
        )

    @patch("aac.llm_client._http_post")
    def test_truncated_emits_plumbing(self, mock_post: MagicMock) -> None:
        body = _anthropic_response(
            [{"type": "text", "text": "cut"}], stop_reason="max_tokens"
        )
        mock_post.return_value = body
        instr = PlumbingInstrument(run_id="t", arm="anthropic")
        backend = self._backend(instrument=instr)
        resp = backend.call("truncated prompt")
        self.assertEqual(resp.get("_plumbing_failure"), "unparseable")
        self.assertGreaterEqual(instr.counts().get("truncated", 0), 1)

    @patch("aac.llm_client._http_post")
    def test_unparseable_emits_plumbing(self, mock_post: MagicMock) -> None:
        body = b"not json"
        mock_post.return_value = body
        instr = PlumbingInstrument(run_id="u", arm="anthropic")
        backend = self._backend(instrument=instr)
        resp = backend.call("unparseable prompt")
        self.assertEqual(resp.get("_plumbing_failure"), "unparseable")
        self.assertGreaterEqual(instr.counts().get("unparseable", 0), 1)

    @patch("aac.llm_client._http_post")
    def test_caching_avoids_second_post(self, mock_post: MagicMock) -> None:
        body = _anthropic_response(
            [{"type": "text", "text": '{"final_answer": {"edges": []}}'}]
        )
        mock_post.return_value = body
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir)
        backend = AnthropicBackend(api_key="sk-test", cache_dir=tmpdir)
        backend.call("cache prompt")
        backend.call("cache prompt")
        self.assertEqual(mock_post.call_count, 1)


class TestOpenAIBackend(unittest.TestCase):
    def _backend(
        self, instrument: PlumbingInstrument | None = None, cache_dir: str | None = None
    ) -> OpenAIBackend:
        if cache_dir is None:
            cache_dir = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, cache_dir)
        return OpenAIBackend(
            api_key="sk-test",
            model="gpt-4o-2024-08-06",
            cache_dir=cache_dir,
            instrument=instrument,
        )

    @patch("aac.llm_client._http_post")
    def test_tool_call_parsing(self, mock_post: MagicMock) -> None:
        body = _openai_response(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "info_gain",
                            "arguments": '{"n_mc_samples": 7}',
                        }
                    }
                ],
            }
        )
        mock_post.return_value = body
        backend = self._backend()
        resp = backend.call("openai tool prompt", tools=[{"name": "info_gain"}])
        self.assertEqual(resp.get("tool_call", {}).get("name"), "info_gain")
        self.assertEqual(resp.get("tool_call", {}).get("arguments"), {"n_mc_samples": 7})

    @patch("aac.llm_client._http_post")
    def test_final_answer_parsing(self, mock_post: MagicMock) -> None:
        body = _openai_response(
            {"role": "assistant", "content": '{"final_answer": {"edges": [[1, 2, 0.8]]}}'}
        )
        mock_post.return_value = body
        backend = self._backend()
        resp = backend.call("openai final prompt")
        self.assertEqual(
            resp.get("final_answer", {}).get("edges"), [[1, 2, 0.8]]
        )

    @patch("aac.llm_client._http_post")
    def test_truncated_emits_plumbing(self, mock_post: MagicMock) -> None:
        body = _openai_response(
            {"role": "assistant", "content": "x"}, finish_reason="length"
        )
        mock_post.return_value = body
        instr = PlumbingInstrument(run_id="t", arm="openai")
        backend = self._backend(instrument=instr)
        resp = backend.call("openai truncated prompt")
        self.assertEqual(resp.get("_plumbing_failure"), "unparseable")
        self.assertGreaterEqual(instr.counts().get("truncated", 0), 1)


class TestStubFallbackBackend(unittest.TestCase):
    def test_stub_only_flag(self) -> None:
        backend = StubFallbackBackend(seed=0)
        self.assertTrue(backend.stub_only)
        resp = backend.call("prompt", tools=[{"name": "info_gain"}])
        self.assertEqual(resp.get("tool_call", {}).get("name"), "info_gain")


if __name__ == "__main__":
    unittest.main()
