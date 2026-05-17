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
