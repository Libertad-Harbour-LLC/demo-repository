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
from typing import Any

import anthropic

from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

DEFAULT_MODEL = "claude-sonnet-4-6"
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
) -> dict:
    """Call Claude to analyze the day's preprocessed trendwatch data.

    Raises ``AnalyzerError`` on any failure (network, parsing, schema).
    """
    chosen_model = model or os.environ.get("TRENDWATCH_MODEL") or DEFAULT_MODEL

    blob = {
        "date": date,
        "period": period,
        "cross_source_mentions": normalized,
        "items": items_with_deltas,
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
        resp = client.messages.create(
            model=chosen_model,
            max_tokens=8000,
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
