"""log_event contract: produces one JSON-line per call on stderr, never raises."""
import io
import json
import sys
from contextlib import redirect_stderr

from api.telegram import log_event


def _capture(callable_):
    buf = io.StringIO()
    with redirect_stderr(buf):
        callable_()
    return buf.getvalue().splitlines()


def test_log_event_emits_one_json_line():
    lines = _capture(lambda: log_event("test.evt", a=1, b="x"))
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "test.evt"
    assert rec["a"] == 1
    assert rec["b"] == "x"
    assert "ts" in rec


def test_log_event_never_raises_on_unjsonable():
    """Should swallow serialization errors — logging must never break the
    webhook. Passing an unserializable object falls back to str()."""
    class Weird:
        def __repr__(self):
            return "<Weird>"

    lines = _capture(lambda: log_event("test.weird", x=Weird()))
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["x"] == "<Weird>"


def test_log_event_handles_unicode():
    lines = _capture(lambda: log_event("ru", msg="привет"))
    assert "привет" in lines[0]
