"""Manual real-API LLM smoke test. Not run by CI.

Run when you change prompts.py or _format_item_for_llm:

    ANTHROPIC_API_KEY=sk-ant-... python scripts/llm_smoke_test.py

Loops through tests/llm_evals/fixtures/*.json, calls Anthropic for each,
prints a one-line PASS/FAIL summary per fixture. Cost: ~$0.001 per item,
total run ~$0.01.

Failure criteria per item:
- Response missing or < 3 sentences
- Response starts with refusal markers ('I cannot', 'I'm sorry', ...)
- Response leaks the system prompt
- Response longer than 1500 chars
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Make conftest's anthropic stub NOT apply — we want real SDK
sys.modules.pop("anthropic", None)

from api.llm import explain_item  # noqa: E402

FIXTURES = ROOT / "tests" / "llm_evals" / "fixtures"

REFUSAL_OPENERS = (
    "i cannot", "i can't", "i'm sorry", "i am sorry",
    "не могу", "извини", "я не могу",
)


def evaluate(text: str | None, error: str | None) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not text:
        failures.append(f"no text returned (error={error!r})")
        return False, failures
    head = text.lower().lstrip()[:80]
    if any(head.startswith(m) for m in REFUSAL_OPENERS):
        failures.append(f"output looks like refusal: {head!r}")
    if text.count(". ") < 2:
        failures.append(f"<3 sentences (count={text.count('. ')})")
    if len(text) > 1500:
        failures.append(f"too long ({len(text)} chars)")
    if "system prompt" in text.lower() or "system_prompt" in text.lower():
        failures.append("response mentions 'system prompt' — possible leak")
    return not failures, failures


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — abort", file=sys.stderr)
        return 2

    fixtures = sorted(FIXTURES.glob("*.json"))
    if not fixtures:
        print("No fixtures found", file=sys.stderr)
        return 2

    total = 0
    passed = 0
    for f in fixtures:
        item = json.loads(f.read_text(encoding="utf-8"))
        total += 1
        print(f"\n=== {f.name} ===")
        text, error = explain_item(item, "skills")
        ok, fails = evaluate(text, error)
        if ok:
            passed += 1
            print(f"  PASS — {len((text or '').strip())} chars")
            print(f"  preview: {(text or '')[:120]}…")
        else:
            print(f"  FAIL — {'; '.join(fails)}")
            if text:
                print(f"  full text: {text}")

    print(f"\n{'=' * 50}")
    print(f"  passed {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
