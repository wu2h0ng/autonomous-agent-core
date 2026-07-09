"""LLMWeightOrgan — LLM-backed strategy weight proposal organ (G11).

Reads environment situation + recent history, outputs a weight vector proposal
over K metrics. The output is STRICTLY parsed: only a weight vector and a
scalar confidence survive. The organ writes only the K(weight) channel —
never action, policy, shell, or gate.

Inherits the LLMPriorOrgan safety pattern: the LLM is UNTRUSTED, the parser
discards everything except a simplex weight vector. The gate always has final
say on whether to adopt the proposal.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from .prior_organ import BeliefSnapshot, OrganAdvice


def _parse_weight_vector(raw: Any, n_metrics: int) -> list[float] | None:
    """Parse a weight vector from raw LLM output. Returns None on parse failure."""
    if isinstance(raw, (list, tuple)):
        weights = []
        for x in raw:
            try:
                w = float(x)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(w) or w < 0.0:
                return None
            weights.append(w)
        if len(weights) != n_metrics:
            return None
        total = sum(weights)
        if total <= 0.0:
            return None
        return [w / total for w in weights]
    return None


def _parse_confidence(raw: Any) -> float:
    try:
        c = float(raw)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(c):
        return 0.5
    return min(1.0, max(0.0, c))


class SimpleLLMBackend:
    """Minimal OpenAI-compatible chat-completion backend using stdlib urllib.

    Used by LLMWeightOrgan to make API calls. Reads OPENAI_API_URL and
    OPENAI_API_KEY from environment. Falls back to deterministic stub if
    no key is present.
    """

    def __init__(self, model: str = "kimi-k2-0711-preview", temperature: float = 1.0):
        import os
        import urllib.request
        import urllib.error
        import ssl
        import hashlib

        self._model = model
        self._temperature = temperature
        self._api_key = os.environ.get("OPENAI_API_KEY", "")
        self._api_url = os.environ.get(
            "OPENAI_API_URL", "https://api.openai.com/v1/chat/completions"
        )
        self._cache_dir = ".cache/llm_weight_calls"
        os.makedirs(self._cache_dir, exist_ok=True)
        self._call_count = 0

    def propose(self, prompt: str) -> Mapping[str, Any]:
        """Make an API call and return parsed JSON response."""
        if not self._api_key:
            return self._stub(prompt)

        import urllib.request
        import urllib.error
        import ssl
        import hashlib

        cache_key = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        cache_path = f"{self._cache_dir}/{cache_key}.json"

        try:
            with open(cache_path, "r") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        body = json.dumps({
            "model": self._model,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": "你是一个策略分析师。根据环境信号输出JSON格式的指标权重向量。"},
                {"role": "user", "content": prompt},
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            self._api_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )

        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return self._stub(prompt)

        self._call_count += 1
        content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = self._extract_json(content)
        with open(cache_path, "w") as f:
            f.write(json.dumps(parsed, ensure_ascii=False))
        return parsed

    def _extract_json(self, content: str) -> dict:
        """Extract JSON from LLM response, with markdown code-block handling.

        Robust to LLMs that return Chinese-keyed dicts or other non-standard formats.
        Always normalizes to {"weights": [...], "confidence": float}.
        """
        if not content:
            return {"weights": None, "confidence": 0.0}
        text = content.strip()
        if "```" in text:
            in_block = False
            lines = []
            for line in text.split("\n"):
                if line.strip().startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    lines.append(line)
            if lines:
                text = "\n".join(lines)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return self._fallback_parse(text)

        if isinstance(parsed, dict):
            if "weights" in parsed:
                return parsed
            nums = []
            for v in parsed.values():
                try:
                    nums.append(float(v))
                except (TypeError, ValueError):
                    pass
            if len(nums) >= 2:
                return {"weights": nums, "confidence": 0.7}
        return {"weights": None, "confidence": 0.0}

    def _fallback_parse(self, text: str) -> dict:
        """Fallback: try to extract a JSON-like object from the text."""
        import re
        for match in re.finditer(r'\{[^{}]+\}', text):
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict):
                    nums = []
                    for v in parsed.values():
                        try:
                            nums.append(float(v))
                        except (TypeError, ValueError):
                            pass
                    if len(nums) >= 2:
                        return {"weights": nums, "confidence": 0.6}
            except json.JSONDecodeError:
                continue
        return {"weights": None, "confidence": 0.0}

    def _stub(self, _prompt: str) -> dict:
        """Deterministic stub: returns uniform weights, zero confidence."""
        return {"weights": None, "confidence": 0.0}


@dataclass
class LLMWeightOrgan:
    """LLM organ that proposes metric weight vectors for G11 strategy selection.

    The organ reads a situation dict from a MultiObjectiveEnv and proposes
    a weight vector on the K-dimensional simplex. The proposal is ONLY advisory:
    a weight vector and a confidence score. The gate decides whether to adopt it.

    Channel signature: σ = {K_weight} — only writes the weight channel.
    """

    backend: Any  # SimpleLLMBackend or compatible
    n_metrics: int = 3
    call_interval: int = 10  # steps between LLM calls (to reduce cost)

    _last_call_step: int = -100
    _cached_proposal: tuple[list[float], float] | None = None
    _fresh: bool = False
    _total_calls: int = 0

    def propose(self, situation: Mapping[str, Any]) -> tuple[list[float] | None, float, bool]:
        """Propose a weight vector and confidence score.

        Returns (weights, confidence, is_fresh). is_fresh=True only when a NEW
        API call was made (not a cached replay). Cached for call_interval steps.
        """
        step = situation.get("step", 0)
        if self._cached_proposal is not None and (step - self._last_call_step) < self.call_interval:
            return (*self._cached_proposal, False)

        self._last_call_step = step
        self._total_calls += 1

        prompt = self._build_prompt(situation)
        raw = self.backend.propose(prompt)

        weights = _parse_weight_vector(raw.get("weights"), self.n_metrics)
        confidence = _parse_confidence(raw.get("confidence"))

        self._cached_proposal = (weights, confidence)
        return (weights, confidence, True)

    def _build_prompt(self, situation: Mapping[str, Any]) -> str:
        description = situation.get("description", "")
        just_shifted = situation.get("just_shifted", False)
        action_summary = situation.get("action_summary", {})
        best_now = situation.get("best_action_now", "?")
        best_before = situation.get("best_action_before", "?")
        best_shifted = situation.get("best_action_shifted", False)

        lines = ["你是一个电商运营策略分析师。根据以下信号推理当前业务阶段并输出最优指标权重。\n"]

        lines.append("【市场观察】")
        lines.append(description)

        lines.append(f"\n【动作表现统计（最近40步）】")
        if action_summary:
            for a_id, stats in sorted(action_summary.items()):
                lines.append(f"  动作{a_id}: 平均奖励{stats['mean']}, 趋势{stats['trend']}, 采样{stats['count']}次")
        else:
            lines.append("  暂无足够数据")

        lines.append(f"\n【策略变化信号】")
        lines.append(f"  最优动作是否变化: {'是' if best_shifted else '否'} (前{best_before}→现{best_now})")
        lines.append(f"  刚刚发生环境切换: {'是' if just_shifted else '否'}")

        lines.append("""
【推理框架】
你需要判断当前处于哪个业务阶段。关键信号：
1. 如果描述提到"流量红利""抢量优先""用户增长" → 拉新期
2. 如果描述提到"转化效率""精细运营""复购率提升" → 收割期  
3. 如果描述提到"利润导向""客单价提升""利润率" → 利润期
4. 如果描述提到"信号混杂""均衡" → 均衡期

如果最优动作发生切换 + 环境切换标记 = 高度确定发生了阶段转换。
如果动作统计中多个动作表现接近 → 可能是均衡期。

【输出格式 - 仅输出JSON，不要任何其他文字】
{"weights": [流量权重, 转化率权重, 客单价权重], "confidence": 0.0到1.0, "phase": "阶段名", "reasoning": "一句话推理依据"}

权重示例：
- 拉新期: [0.7, 0.2, 0.1]
- 收割期: [0.1, 0.7, 0.2]
- 利润期: [0.1, 0.2, 0.7]
- 均衡期: [0.34, 0.33, 0.33]
只有在你非常确定(置信度>0.8)时才输出极端权重[0.8, 0.1, 0.1]。不确定时请保持均衡或温和偏向。

置信度对应你的确定程度：
- 0.9-1.0: 多个信号一致指向同一阶段
- 0.7-0.8: 有明确信号但存在矛盾点
- 0.5-0.6: 信号模糊，多个阶段都有可能
- 低于0.5: 没有足够信息做出判断""")
        return "\n".join(lines)

    @property
    def total_calls(self) -> int:
        return self._total_calls
