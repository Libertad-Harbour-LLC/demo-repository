#!/usr/bin/env python3
"""Print Telegram chat_ids that have messaged your bot.

Usage:
  1. Send /start to your bot from each chat you want to capture.
  2. Run: TELEGRAM_BOT_TOKEN=... python trendwatch/get_chat_id.py
     (or: python trendwatch/get_chat_id.py --token <bot_token>)
"""
import argparse
import os
import sys

import requests


def main() -> int:
    print("Send /start to your bot first, then run this script.\n")

    parser = argparse.ArgumentParser()
    parser.add_argument("--token", help="Telegram bot token (or set TELEGRAM_BOT_TOKEN)")
    args = parser.parse_args()

    token = args.token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("error: pass --token or set TELEGRAM_BOT_TOKEN env var", file=sys.stderr)
        return 1

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"error: getUpdates failed: {exc}", file=sys.stderr)
        return 1

    payload = resp.json()
    if not payload.get("ok"):
        print(f"error: telegram returned {payload}", file=sys.stderr)
        return 1

    updates = payload.get("result", []) or []
    if not updates:
        print("No updates yet. Send /start (or any message) to the bot, then re-run.")
        return 0

    seen: set = set()
    for upd in updates:
        chat = None
        for key in ("message", "channel_post", "edited_message", "my_chat_member"):
            obj = upd.get(key)
            if isinstance(obj, dict) and "chat" in obj:
                chat = obj["chat"]
                break
        if not chat:
            continue
        cid = chat.get("id")
        if cid in seen:
            continue
        seen.add(cid)
        label = chat.get("username") or chat.get("title") or "(no name)"
        ctype = chat.get("type", "?")
        print(f"chat_id={cid}\ttype={ctype}\tname={label}")

    if not seen:
        print("Updates exist but no chats parsed. Send a fresh /start and retry.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
