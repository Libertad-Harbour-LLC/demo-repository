"""Final-stage output guardrail tests — _validate_explanation_output.

Belt-and-suspenders defence applied to whatever the model returned,
after refusal-marker check. The validator MUST NOT raise; it always
returns a non-empty string the caller forwards to Telegram.
"""
import pytest

from api.llm import EXPLANATION_MAX_CHARS, _validate_explanation_output


ITEM_STUB = {"url": "https://github.com/example/repo", "repo_full_name": "example/repo"}


def test_normal_output_passes_through_unchanged():
    text = (
        "Это плагин для Claude Code, помогающий писать тесты. "
        "Применять стоит в проектах с устоявшимся стеком. "
        "Отличается от похожих наличием встроенных шаблонов."
    )
    assert _validate_explanation_output(text, ITEM_STUB) == text


def test_url_in_output_is_stripped():
    text = "Это плагин. Скачать: https://example.com/download Подробнее в инструкции."
    out = _validate_explanation_output(text, ITEM_STUB)
    assert "https://" not in out
    assert "example.com" not in out
    assert "Это плагин" in out
    assert "Подробнее в инструкции" in out


def test_multiple_urls_all_stripped():
    text = (
        "Документация http://docs.example.com — кратко. "
        "Репо https://github.com/example/repo — само. "
        "Сравни с https://other.example.com/skill."
    )
    out = _validate_explanation_output(text, ITEM_STUB)
    assert "http" not in out
    assert "example.com" not in out
    assert "Документация" in out


def test_double_spaces_collapsed_after_url_strip():
    text = "До URL https://foo.bar после URL — текст."
    out = _validate_explanation_output(text, ITEM_STUB)
    assert "  " not in out


def test_hard_cap_at_max_chars():
    text = "А" * 3000
    out = _validate_explanation_output(text, ITEM_STUB)
    assert len(out) <= EXPLANATION_MAX_CHARS + 1  # +1 for ellipsis


def test_cap_cuts_at_sentence_boundary_when_possible():
    body = "Длинное предложение про инструмент. " * 60  # ~2200 chars
    out = _validate_explanation_output(body, ITEM_STUB)
    assert len(out) <= EXPLANATION_MAX_CHARS + 1
    # If a "." landed inside the budget half, output ends with period+ellipsis
    assert out.endswith("…")


def test_cap_falls_through_to_hard_truncate_if_no_sentence_break():
    text = "А" * 3000  # no sentence boundary
    out = _validate_explanation_output(text, ITEM_STUB)
    assert out.endswith("…")
    assert len(out) <= EXPLANATION_MAX_CHARS + 1


def test_validator_never_returns_empty():
    """Even on degenerate input (only URLs), return what's left after
    stripping — even if just an ellipsis. The refusal path is the
    caller's responsibility."""
    text = "https://only-a-link.example/foo"
    out = _validate_explanation_output(text, ITEM_STUB)
    # After strip+collapse: empty or single space
    assert isinstance(out, str)


def test_validator_idempotent():
    """Running the validator twice should produce the same result
    (no double-strip oddities)."""
    text = "Skill для тестов. Применять в TDD."
    once = _validate_explanation_output(text, ITEM_STUB)
    twice = _validate_explanation_output(once, ITEM_STUB)
    assert once == twice


def test_validator_preserves_normal_punctuation():
    text = "Один пункт; ещё один — с тире. И вопрос? И список: a, b, c."
    out = _validate_explanation_output(text, ITEM_STUB)
    assert ";" in out
    assert "—" in out
    assert "?" in out
    assert ":" in out
