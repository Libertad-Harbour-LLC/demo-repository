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

try:
    from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
except ImportError:
    from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

DEFAULT_MODEL = "claude-sonnet-4-6"
# PR #17 added a required `description` field to top_test/top_watch entries.
# For 15 candidates with full rankings + top_test + top_watch + top_skip +
# best_pick + telegram_summary + metadata, observed output drifted above
# 12K — the analyzer raised "Response truncated by max_tokens" and the
# orchestrator fell through to [FALLBACK_LINKS]. Bumped to 20K, well under
# Sonnet 4.6's per-call output ceiling and ~$0.06 extra per worst-case run.
DEFAULT_MAX_TOKENS = 20000
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
    system_prompt: str | None = None,
) -> dict:
    """Call Claude to analyze the day's preprocessed trendwatch data.

    ``graduated_candidates`` are watchlist items whose ``signal_to_wait`` was
    met by fresh metrics this run; the model should treat them as priority
    promotions to ``top_test`` and reference their ``trigger`` in
    ``why_growing``.

    ``system_prompt`` lets callers swap the cached system prompt (e.g. the
    workflows pipeline uses its own one). When ``None`` (default), the
    Claude-Skills SYSTEM_PROMPT from ``prompts.py`` is used.

    Raises ``AnalyzerError`` on any failure (network, parsing, schema).
    """
    chosen_model = model or os.environ.get("TRENDWATCH_MODEL") or DEFAULT_MODEL
    system_text = system_prompt if system_prompt is not None else SYSTEM_PROMPT

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

    # Read explicitly and .strip() — GH Actions / Vercel UI may preserve a
    # trailing newline on paste which httpx rejects as "Illegal header
    # value", and an extra space silently maps to a different (invalid)
    # key value at Anthropic, yielding 401 invalid x-api-key.
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise AnalyzerError(
            "ANTHROPIC_API_KEY env var not set in this runner — "
            "check GitHub repo Settings → Secrets and variables → Actions"
        )

    try:
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as exc:
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
                    "text": system_text,
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

    # Defensive cleanup: even though the system prompt forbids the
    # "🗑 Пропустить" Telegram block, the model occasionally emits it
    # anyway from prompt-cache memory. Strip it post-hoc so users never see
    # the skip section in the daily digest.
    summary = parsed.get("telegram_summary")
    if isinstance(summary, str) and summary:
        parsed["telegram_summary"] = _strip_skip_block(summary)

    _backfill_descriptions(parsed)

    return parsed


def _backfill_descriptions(parsed: dict) -> None:
    """Ensure every top_test / top_watch entry has a non-empty description.

    The bot's detail screen renders ``description`` as the primary
    human-readable card. If the LLM ignores the schema requirement, we log
    a warning per entry and fall back to ``what`` / ``why_interesting`` /
    repo name so the bot card is never blank.
    """
    for bucket in ("top_test", "top_watch"):
        items = parsed.get(bucket)
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            desc = it.get("description")
            if isinstance(desc, str) and desc.strip():
                continue
            fallback = (
                (it.get("what") if bucket == "top_test" else it.get("why_interesting"))
                or it.get("name")
                or ""
            )
            it["description"] = (fallback or "").strip()
            print(
                f"[trendwatch.analyzer] WARN missing description in "
                f"{bucket} entry name={it.get('name')!r} — "
                f"backfilled from {'what' if bucket == 'top_test' else 'why_interesting'}",
                file=sys.stderr,
            )


_SKIP_BLOCK_RE = re.compile(
    r"^\s*\U0001f5d1[^\n]*\n(?:(?!^\s*(?:\U0001f680|\U0001f525|\U0001f440|"
    r"\U0001f3af|\U0001f4ca|⚠️|⚙️|\U0001f4a1)).*\n?)*",
    re.MULTILINE,
)


def _strip_skip_block(summary: str) -> str:
    """Remove the legacy "🗑 Пропустить:" block from a telegram_summary.

    Matches the 🗑 header line and every following line until the next
    section header (one of the emoji bullets used in our templates).
    """
    return _SKIP_BLOCK_RE.sub("", summary).rstrip() + "\n"


__all__ = ["analyze", "AnalyzerError", "DEFAULT_MODEL"]
