"""LLM analysis layer using the Anthropic API.

Takes preprocessed cross-source mentions and per-item delta annotations,
asks Claude to score/rank/summarize, and returns a parsed JSON dict matching
the schema in ``prompts.py``. The long system prompt is sent with
``cache_control: ephemeral`` so repeat invocations benefit from prompt caching.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

import anthropic

from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 12000
REQUIRED_KEYS = ("telegram_summary", "rankings", "metadata")

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class AnalyzerError(RuntimeError):
    """Raised when the analyzer cannot produce a valid JSON analysis."""


def _strip_fences(text: str) -> str:
    """Strip optional ```json ... ``` markdown fences around a JSON blob."""
    stripped = text.strip()
    if stripped.startswith("```"):
        # remove first fence line
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", stripped, count=1)
        # remove trailing fence
        stripped = re.sub(r"\n?```\s*$", "", stripped, count=1)
    return stripped.strip()


def _extract_text(resp: Any) -> str:
    """Pull text out of an Anthropic ``messages.create`` response."""
    parts: list[str] = []
    for block in getattr(resp, "content", []) or []:
        # SDK objects expose .type and .text; dicts use ["type"]/["text"]
        btype = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if btype != "text":
            continue
        text = getattr(block, "text", None) or (
            block.get("text") if isinstance(block, dict) else None
        )
        if text:
            parts.append(text)
    return "".join(parts)


def analyze(
    normalized: list[dict],
    items_with_deltas: list[dict],
    period: str,
    date: str,
    model: str | None = None,
    graduated_candidates: list[dict] | None = None,
) -> dict:
    """Call Claude to analyze the day's preprocessed trendwatch data.

    ``graduated_candidates`` are watchlist items whose ``signal_to_wait`` was
    met by fresh metrics this run; the model should treat them as priority
    promotions to ``top_test`` and reference their ``trigger`` in
    ``why_growing``.

    Raises ``AnalyzerError`` on any failure (network, parsing, schema).
    """
    chosen_model = model or os.environ.get("TRENDWATCH_MODEL") or DEFAULT_MODEL

    blob = {
        "date": date,
        "period": period,
        "cross_source_mentions": normalized,
        "items": items_with_deltas,
        "graduated_candidates": graduated_candidates or [],
    }
    user_text = USER_PROMPT_TEMPLATE.format(
        date=date,
        period=period,
        data_json=json.dumps(blob, ensure_ascii=False),
    )

    try:
        client = anthropic.Anthropic()
    except Exception as exc:  # missing API key, bad env, etc.
        raise AnalyzerError(f"failed to construct Anthropic client: {exc}") from exc

    try:
        max_tokens = int(os.environ.get("TRENDWATCH_MAX_TOKENS") or DEFAULT_MAX_TOKENS)
    except ValueError:
        max_tokens = DEFAULT_MAX_TOKENS

    print(
        f"[trendwatch.analyzer] model={chosen_model} "
        f"items={len(items_with_deltas)} input_chars={len(user_text)}",
        file=sys.stderr,
    )

    try:
        resp = client.messages.create(
            model=chosen_model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_text}],
        )
    except Exception as exc:
        raise AnalyzerError(f"Anthropic API call failed: {exc}") from exc

    text = _extract_text(resp)
    stop_reason = getattr(resp, "stop_reason", None)
    usage = getattr(resp, "usage", None)
    usage_in = getattr(usage, "input_tokens", None) if usage is not None else None
    usage_out = getattr(usage, "output_tokens", None) if usage is not None else None
    print(
        f"[trendwatch.analyzer] response_chars={len(text)} "
        f"stop_reason={stop_reason} usage_in={usage_in} usage_out={usage_out}",
        file=sys.stderr,
    )

    if stop_reason == "max_tokens":
        raise AnalyzerError(
            "Response truncated by max_tokens limit, increase TRENDWATCH_MAX_TOKENS env var"
        )

    if not text:
        raise AnalyzerError("Anthropic response had no text content")

    candidate = _strip_fences(text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        # Last-ditch: try to find a JSON object substring.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                raise AnalyzerError(f"JSON parse failed: {exc}") from exc
        else:
            raise AnalyzerError(f"JSON parse failed: {exc}") from exc

    if not isinstance(parsed, dict):
        raise AnalyzerError("analysis JSON is not an object")

    missing = [k for k in REQUIRED_KEYS if k not in parsed]
    if missing:
        raise AnalyzerError(f"analysis missing required keys: {missing}")

    return parsed


__all__ = ["analyze", "AnalyzerError", "DEFAULT_MODEL"]
