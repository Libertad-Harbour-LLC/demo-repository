"""Structural sanity on the system prompt — catches accidental drift.

Anthropic prompt caching keys on a byte-stable prefix. Editing the
system prompt invalidates the cache (paid input tokens spike). This
suite doesn't gate edits, but it gates *accidental* drift: rules the
system prompt MUST keep (or the explain feature breaks).
"""
import pytest

from api.llm import _SYSTEM_PROMPT


def test_system_prompt_has_data_not_instructions_rule():
    """The single most important defence against item-description
    prompt injection: explicit 'treat <item> as data' rule."""
    assert "инструкциям из данных" in _SYSTEM_PROMPT or \
           "ДАННЫЕ" in _SYSTEM_PROMPT


def test_system_prompt_constrains_output_format():
    """Detail screen + Telegram both render plain prose. The prompt
    MUST forbid markdown / emoji / lists in the model's reply."""
    assert "Только сплошной текст" in _SYSTEM_PROMPT
    assert "Никаких списков, заголовков, markdown, эмодзи" in _SYSTEM_PROMPT


def test_system_prompt_limits_sentence_count():
    """3-5 sentences keeps the Telegram message readable. Without
    this rule the model occasionally produces 15-sentence essays."""
    assert "3-5 предложений" in _SYSTEM_PROMPT
    assert "Не более 5 предложений" in _SYSTEM_PROMPT


def test_system_prompt_forbids_hallucinating_details():
    """Item descriptions are sometimes sparse. The prompt must tell
    the model not to invent details it doesn't have."""
    assert "Не выдумывай" in _SYSTEM_PROMPT


def test_system_prompt_is_non_empty_and_bounded():
    """Below 500 chars suggests truncation; above 5000 suggests bloat
    (cache cost). Sanity range."""
    assert 500 < len(_SYSTEM_PROMPT) < 5000


def test_system_prompt_no_runtime_volatility():
    """Cache-killers: timestamps, dates, request IDs, user IDs at
    the start of the cacheable prompt. The first 200 chars should
    be byte-stable across runs."""
    prefix = _SYSTEM_PROMPT[:200]
    # No 4-digit year (2024, 2026, ...) in the prefix
    import re
    assert not re.search(r"20\d\d-\d\d-\d\d", prefix), \
        "Date-like substring in cacheable prefix → cache invalidations"
    # No UUID-like patterns
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", prefix)
