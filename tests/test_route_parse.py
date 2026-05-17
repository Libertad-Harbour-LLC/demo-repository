"""Wire-format contract for inline_keyboard callback_data.

Inline keyboards live in Telegram chat history indefinitely. Every callback
shape ever emitted MUST keep parsing the same way across releases — break
this and old user messages start firing into None.
"""
import pytest

from api.telegram import Route


@pytest.mark.parametrize("data,expected", [
    # Top-level menu
    ("menu", Route(kind="top_menu", source_key=None)),

    # Source menu + per-source views
    ("src:skills:menu", Route(kind="source_menu", source_key="skills")),
    ("src:n8n:menu", Route(kind="source_menu", source_key="n8n")),
    ("src:make:menu", Route(kind="source_menu", source_key="make")),
    ("src:skills:categories", Route(kind="categories", source_key="skills")),
    ("src:n8n:months", Route(kind="months", source_key="n8n")),

    # List / category / month pagination (with and without explicit page)
    ("src:skills:list:0", Route(kind="list", source_key="skills", page=0)),
    ("src:skills:list:3", Route(kind="list", source_key="skills", page=3)),
    ("src:skills:list", Route(kind="list", source_key="skills", page=0)),
    ("src:skills:cat:marketing_skill:0",
     Route(kind="category", source_key="skills", arg="marketing_skill", page=0)),
    ("src:skills:cat:marketing_skill:2",
     Route(kind="category", source_key="skills", arg="marketing_skill", page=2)),
    ("src:n8n:month:2026-05:0",
     Route(kind="month", source_key="n8n", arg="2026-05", page=0)),

    # Per-item actions
    ("src:make:item:abcd1234",
     Route(kind="item", source_key="make", arg="abcd1234")),
    ("src:skills:explain:abcd1234",
     Route(kind="explain", source_key="skills", arg="abcd1234")),
    ("src:skills:random",
     Route(kind="random", source_key="skills")),
    ("src:skills:share:abcd1234",
     Route(kind="share", source_key="skills", arg="abcd1234")),
    ("src:skills:setup:abcd1234",
     Route(kind="setup", source_key="skills", arg="abcd1234")),
    ("src:skills:similar:abcd1234",
     Route(kind="similar", source_key="skills", arg="abcd1234")),
])
def test_route_parse_known_shapes(data, expected):
    assert Route.parse(data) == expected


@pytest.mark.parametrize("data", [
    "",                          # empty
    "totally_unknown",           # not src: prefix
    "src:skills",                # missing action
    "src:unknown_source:menu",   # invalid source
    "src:skills:bogus",          # unknown action
    "src:skills:item",           # missing url_id arg
    "src:skills:explain",        # missing url_id arg
])
def test_route_parse_invalid_returns_none(data):
    assert Route.parse(data) is None
