"""Pytest config: stub env vars so api.telegram / api.llm import cleanly
without touching real Telegram or Anthropic.
"""
import os
import sys
from pathlib import Path

# Make the repo root importable as a package root (so `api.telegram` resolves
# whether tests are run from repo root or from `tests/`).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("BOT_REPO", "Libertad-Harbour-LLC/demo-repository")
os.environ.setdefault("BOT_BRANCH", "main")
# Fake admin id so test_access can pick one via next(iter(ADMIN_IDS)).
# Production reads real IDs from BOT_ADMIN_IDS in Vercel env vars.
os.environ.setdefault("BOT_ADMIN_IDS", "111111111")

# Stub the anthropic SDK so trendwatch.analyzer imports cleanly in CI
# without paying for the (heavy) real SDK. Tests don't exercise the
# network path — they exercise pure-Python guards.
import types
if "anthropic" not in sys.modules:
    fake = types.ModuleType("anthropic")
    class _StubClient:
        def __init__(self, *_, **__): pass
        class messages:
            @staticmethod
            def create(*_, **__):
                raise RuntimeError("anthropic SDK stubbed in tests")
    fake.Anthropic = _StubClient
    sys.modules["anthropic"] = fake
