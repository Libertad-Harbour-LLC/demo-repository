#!/usr/bin/env python3
"""Workflows orchestrator: fetch -> normalize+deltas -> LLM analyze -> Telegram.

Mirrors ``trendwatch/trendwatch.py`` but targets ready-made n8n and Make
workflows. Reuses trendwatch primitives (state, skill_db, analyzer,
telegram_client, index_writer, links) via direct imports — only the
fetchers, prompts, normalizer vocabulary, and the daily-report path differ.

Data lives under ``digests/workflows/`` (state.json, recommended.json,
watchlist.json, index/, YYYY-MM-DD.md) — fully isolated from the skills
pipeline's ``digests/`` files.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

# Ensure repo root is on sys.path so ``trendwatch.*`` and ``workflows.*``
# imports resolve no matter where this script is launched from.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from trendwatch import analyzer  # noqa: E402
from trendwatch import index_writer  # noqa: E402
from trendwatch import report  # noqa: E402
from trendwatch import skill_db  # noqa: E402
from trendwatch import state  # noqa: E402
from trendwatch import telegram_client  # noqa: E402

from workflows import config  # noqa: E402
from workflows import normalizer  # noqa: E402
from workflows.prompts import SYSTEM_PROMPT as WORKFLOWS_SYSTEM_PROMPT  # noqa: E402
from workflows.sources.make_github import fetch_make_github  # noqa: E402
from workflows.sources.n8n_github import fetch_n8n_github  # noqa: E402
from workflows.sources.reddit import fetch_reddit  # noqa: E402


def _is_worth_showing(item: dict) -> bool:
    """Dedupe: include items that are new, gained workflows, grew ≥5 stars,
    or have absolute stars ≥100 (high-star repos always re-evaluated by the
    LLM — otherwise a 1k-star automation repo seen once with zero daily
    growth would silently vanish from analysis forever).
    """
    if item.get("is_new", True):
        return True
    if item.get("has_new_skills"):
        return True
    delta = item.get("delta_stars") or 0
    if isinstance(delta, int) and delta >= 5:
        return True
    stars = item.get("stars") or 0
    if isinstance(stars, int) and stars >= 100:
        return True
    return False


def _safe(name: str, fn, *args, **kwargs) -> list[dict]:
    try:
        return fn(*args, **kwargs) or []
    except Exception as exc:
        print(f"[workflows:{name}] unexpected: {exc}", file=sys.stderr)
        return []


def _owner_repo_from(entry: dict) -> str | None:
    """owner/repo from a promoted analyzer entry (name like 'owner/repo: wf' or
    a github URL)."""
    import re
    name = (entry.get("name") or "").split(":", 1)[0].strip()
    if name.count("/") == 1 and " " not in name:
        return name
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", entry.get("url") or "")
    if m:
        repo = m.group(2)
        return f"{m.group(1)}/{repo[:-4] if repo.endswith('.git') else repo}"
    return None


def _explode_promotions(top_test_items: list[dict]) -> list[dict]:
    """Fix 2: turn each promoted REPO into one entry per individual workflow
    JSON, so the catalog counts importable workflows, not repos. Enumerates the
    full repo (git tree) only for these few promoted repos. Repos that can't be
    enumerated fall back to a single repo-level entry.
    """
    try:
        from workflows.sources import _github_common as gh
        from workflows.sources.make_github import _is_make_blueprint
        from workflows.sources.n8n_github import _is_n8n_workflow
    except ImportError:  # pragma: no cover
        from sources import _github_common as gh
        from sources.make_github import _is_make_blueprint
        from sources.n8n_github import _is_n8n_workflow

    validators = {"n8n": _is_n8n_workflow, "make": _is_make_blueprint}
    cap = getattr(config, "EXPLODE_MAX_WORKFLOWS_PER_REPO", 25)
    out: list[dict] = []
    for entry in top_test_items:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        tool = (entry.get("tool") or "").lower()
        owner_repo = _owner_repo_from(entry)
        validator = validators.get(tool)
        wfs: list[dict] = []
        if owner_repo and validator:
            try:
                meta = gh._repo_meta(owner_repo)
                branch = meta.get("default_branch") or "main"
                wfs = gh.list_repo_workflows(owner_repo, branch, validator, limit=cap)
            except Exception as exc:
                print(f"[workflows] explode failed for {owner_repo}: {exc}",
                      file=sys.stderr)
        if not wfs:
            out.append(entry)  # keep repo-level entry as fallback
            continue
        for wf in wfs:
            e = dict(entry)
            e["name"] = f"{owner_repo}: {wf['name']}"
            e["url"] = wf["blob_url"]
            e["json_url"] = wf["json_url"]
            e["repo_full_name"] = owner_repo
            e["skills_in_repo"] = [wf["name"]]
            out.append(e)
        print(f"[workflows] exploded {owner_repo} -> {len(wfs)} workflow entries",
              file=sys.stderr)
    return out


def _fetch_all() -> dict[str, list[dict]]:
    enabled = getattr(config, "SOURCES", {})
    max_items = getattr(config, "MAX_ITEMS_PER_SOURCE", 15)
    out: dict[str, list[dict]] = {}
    if enabled.get("n8n_github"):
        out["github_n8n"] = _safe(
            "n8n_github",
            fetch_n8n_github,
            config.GITHUB_TOPICS_N8N,
            config.GITHUB_CODE_QUERIES_N8N,
            24,
            max_items,
            getattr(config, "VERIFY_WORKFLOW_JSON", True),
            getattr(config, "MAX_JSON_FETCH_BYTES", 200_000),
        )
    if enabled.get("make_github"):
        out["github_make"] = _safe(
            "make_github",
            fetch_make_github,
            config.GITHUB_TOPICS_MAKE,
            config.GITHUB_CODE_QUERIES_MAKE,
            24,
            max_items,
            getattr(config, "VERIFY_WORKFLOW_JSON", True),
            getattr(config, "MAX_JSON_FETCH_BYTES", 200_000),
        )
    if enabled.get("reddit"):
        out["reddit"] = _safe(
            "reddit",
            fetch_reddit,
            config.REDDIT_SUBREDDITS,
            config.REDDIT_MIN_SCORE,
            24,
            max_items,
            config.REDDIT_KEYWORDS_FILTER,
        )
    return out


def _build_cross_source_map(annotated_items: list[dict]) -> dict[str, int]:
    name_sources: dict[str, set[str]] = {}
    for it in annotated_items or []:
        src = it.get("source") or ""
        if not src:
            continue
        for name in it.get("matched_names") or []:
            name_sources.setdefault(name, set()).add(src)
    out: dict[str, int] = {}
    for it in annotated_items or []:
        url = it.get("url")
        if not url:
            continue
        best = 1
        for name in it.get("matched_names") or []:
            best = max(best, len(name_sources.get(name, {it.get("source") or ""})))
        out[url] = max(out.get(url, 0), best)
    return out


def _annotate_cross_source(items: list[dict], cross_map: dict[str, int]) -> list[dict]:
    for it in items or []:
        url = it.get("url")
        if url and url in cross_map:
            it["cross_source_count"] = cross_map[url]
    return items


def _baseline_metrics(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items or []:
        url = it.get("url") or ""
        if not url:
            continue
        out[url] = {
            "stars": it.get("stars"),
            "skills_count": it.get("skills_count") or it.get("workflow_count"),
            "cross_source_count": it.get("cross_source_count"),
        }
    return out


def _write_report(analysis: dict, date: str) -> str:
    os.makedirs(config.DIGEST_DIR, exist_ok=True)
    path = os.path.join(config.DIGEST_DIR, f"{date}.md")
    md = report.to_markdown(analysis, date)
    # Replace the skills-pipeline header so the file is self-identifying.
    md = md.replace(
        f"# Daily Skill Radar — {date}",
        f"# Daily Workflow Radar — {date}",
        1,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path


def run(
    dry_run: bool = False, no_analyzer: bool = False, force: bool = False
) -> int:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not dry_run:
        if not bot_token or not chat_id:
            print(
                "[workflows] TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required "
                "(or use --dry-run)",
                file=sys.stderr,
            )
            return 1

    # Idempotency guard: skip if a digest was already sent today.
    if not dry_run and not force and state.was_sent_today(path=config.STATE_PATH):
        print("[ALREADY_SENT_TODAY] workflows digest already sent today, skipping")
        return 0

    items_by_source = _fetch_all()
    counts = " ".join(f"{k}={len(v)}" for k, v in items_by_source.items())
    summary = f"[workflows] {counts}"
    print(f"[PHASE:FETCH] {counts}", file=sys.stderr)

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    period = "24h"

    if dry_run:
        for src, items in items_by_source.items():
            print(f"--- {src} ({len(items)}) ---")
            for it in items[:5]:
                print(
                    f"  • {it.get('tool', '?')} | {it.get('title', '')[:80]} | "
                    f"{it.get('json_url') or it.get('url', '')}"
                )
        print("[WORKFLOWS_DRY_RUN]")
        print(summary)
        return 0

    if no_analyzer:
        # Plain link fallback — reuse trendwatch.telegram_client.send_digest.
        try:
            telegram_client.send_digest(items_by_source, bot_token, chat_id)
        except Exception as exc:
            print(f"[workflows] telegram send failed: {exc}", file=sys.stderr)
            print(summary)
            return 1
        print("[WORKFLOWS_FALLBACK] --no-analyzer requested")
        print(summary)
        return 0

    # --- Analyzer pipeline ---
    prev_state = state.load_state(path=config.STATE_PATH)
    items_with_deltas = state.compute_deltas(items_by_source, prev_state)

    recommended_db = skill_db.load_recommended(path=config.RECOMMENDED_PATH)
    watchlist_db = skill_db.load_watchlist(path=config.WATCHLIST_PATH)

    # Drop already-recommended workflows. With per-workflow explosion (Fix 2)
    # recommended.json is keyed by individual workflow URLs, so also exclude any
    # repo whose workflows we already catalogued (matched by repo_full_name) —
    # otherwise the repo would be re-analysed and re-exploded every run.
    recommended_repos = {
        v.get("repo_full_name")
        for v in (recommended_db.get("skills") or {}).values()
        if isinstance(v, dict) and v.get("repo_full_name")
    }
    pre_filter = len(items_with_deltas)
    items_with_deltas = [
        i for i in items_with_deltas
        if not skill_db.is_recommended(recommended_db, i.get("url") or "")
        and i.get("repo_full_name") not in recommended_repos
    ]
    dropped = pre_filter - len(items_with_deltas)
    if dropped:
        print(
            f"[workflows] dropped {dropped} already-recommended workflow(s)",
            file=sys.stderr,
        )

    normalized, annotated = normalizer.normalize(items_by_source)
    cross_map = _build_cross_source_map(annotated)
    items_with_deltas = _annotate_cross_source(items_with_deltas, cross_map)

    expired = skill_db.prune_expired(watchlist_db, date)
    if expired:
        print(
            f"[workflows] pruned {len(expired)} expired watchlist item(s)",
            file=sys.stderr,
        )
    graduates = skill_db.check_watchlist_graduates(watchlist_db, items_with_deltas)
    graduate_urls = {g.get("url") for g in graduates if g.get("url")}
    for g in graduates:
        g["graduated_from_watch"] = True

    pre_worth_count = len(items_with_deltas)
    filtered_items = [it for it in items_with_deltas if _is_worth_showing(it)]
    # Bound the analyzer input (the fetch cap is high now). Prioritise NEW repos,
    # then star count, so fresh discoveries get evaluated first and the rest
    # rotate through subsequent runs.
    analyzer_cap = getattr(config, "ANALYZER_MAX_ITEMS", 60)
    pre_cap = len(filtered_items)
    if pre_cap > analyzer_cap:
        filtered_items.sort(
            key=lambda it: (not it.get("is_new", False), -(it.get("stars") or 0))
        )
        filtered_items = filtered_items[:analyzer_cap]
    print(
        f"[PHASE:FILTER] after_is_recommended={pre_worth_count} "
        f"after_is_worth_showing={pre_cap} to_analyzer={len(filtered_items)} "
        f"graduates={len(graduates)}",
        file=sys.stderr,
    )

    if not filtered_items and not graduates:
        msg = (
            f"⚙️ Daily Workflow Radar — {date}\n\n"
            "Нет новых n8n/Make workflows за период. Все обнаруженные репозитории "
            "уже были в предыдущих дайджестах без значимого роста.\n\n"
            f"\U0001f4ca Источников проверено: {', '.join(items_by_source.keys())}"
        )
        try:
            telegram_client.send_text(msg, bot_token, chat_id)
        except Exception as exc:
            print(f"[workflows] telegram send_text failed: {exc}", file=sys.stderr)
            print(summary)
            return 1
        try:
            state.save_state(items_by_source, path=config.STATE_PATH)
        except Exception as exc:
            print(f"[workflows] state save failed: {exc}", file=sys.stderr)
        try:
            skill_db.save_watchlist(watchlist_db, path=config.WATCHLIST_PATH)
        except Exception as exc:
            print(f"[workflows] watchlist save failed: {exc}", file=sys.stderr)
        try:
            state.mark_sent_today(path=config.STATE_PATH)
        except Exception as exc:
            print(f"[workflows] mark_sent failed: {exc}", file=sys.stderr)
        print("[WORKFLOWS_NO_NEW_ITEMS]")
        print(summary)
        return 0

    try:
        analysis = analyzer.analyze(
            normalized,
            filtered_items,
            period=period,
            date=date,
            graduated_candidates=graduates,
            system_prompt=WORKFLOWS_SYSTEM_PROMPT,
        )
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(
            f"[workflows] analyzer failed: {msg}; falling back to link digest",
            file=sys.stderr,
        )
        try:
            telegram_client.send_digest(items_by_source, bot_token, chat_id)
        except Exception as exc2:
            print(f"[workflows] telegram fallback failed: {exc2}", file=sys.stderr)
            print(summary)
            return 1
        try:
            telegram_client.send_text(
                f"⚠️ Workflow LLM-анализ упал, отправлены плоские ссылки.\n"
                f"Причина: {msg[:300]}",
                bot_token, chat_id,
            )
        except Exception as exc2:
            print(f"[workflows] reason-note send failed: {exc2}", file=sys.stderr)
        print("[WORKFLOWS_FALLBACK] LLM analysis failed, sent link list.")
        print(summary)
        return 0

    analysis.setdefault("graduated_from_watch", graduates)

    telegram_text = analysis.get("telegram_summary") or ""
    if not telegram_text.strip():
        print(
            "[WORKFLOWS_FALLBACK] empty telegram_summary from analyzer",
            file=sys.stderr,
        )
        try:
            telegram_client.send_digest(items_by_source, bot_token, chat_id)
        except Exception as exc:
            print(f"[workflows] telegram fallback failed: {exc}", file=sys.stderr)
            print(summary)
            return 1
        print("[WORKFLOWS_FALLBACK] empty summary, sent link list.")
        print(summary)
        return 0

    # Persist DB changes.
    baseline_map = _baseline_metrics(items_with_deltas)
    top_test_items = analysis.get("top_test") or []
    top_watch_items = analysis.get("top_watch") or []

    # Repo URLs BEFORE explosion (for watchlist removal — watchlist is keyed by
    # repo URL, but explosion rewrites entry URLs to per-workflow blob URLs).
    promoted_repo_urls = {
        (it.get("url") or "") for it in top_test_items if isinstance(it, dict)
    }
    # Fix 2: explode each promoted REPO into one entry per individual workflow
    # JSON, so the catalog counts importable workflows, not repos.
    top_test_items = _explode_promotions(top_test_items)

    try:
        added_rec = skill_db.add_to_recommended(recommended_db, top_test_items, date)
        if added_rec:
            print(
                f"[workflows] added {len(added_rec)} workflow(s) to recommended.json",
                file=sys.stderr,
            )
        # Copy `tool` onto each new recommended entry so by_tool indexes work.
        rec_skills = recommended_db.get("skills", {}) or {}
        for it in top_test_items:
            if not isinstance(it, dict):
                continue
            url = it.get("url") or ""
            if url in rec_skills and isinstance(rec_skills[url], dict):
                rec_skills[url]["tool"] = (it.get("tool") or "other").lower()

        to_remove = (graduate_urls & promoted_repo_urls) | {
            u for u in graduate_urls if u in recommended_db.get("skills", {})
        }
        if to_remove:
            skill_db.remove_from_watchlist(watchlist_db, list(to_remove))

        added_watch = skill_db.add_to_watchlist(
            watchlist_db,
            top_watch_items,
            date,
            baseline_map,
            default_category="general_workflow",
        )
        if added_watch:
            print(
                f"[workflows] added {len(added_watch)} workflow(s) to watchlist.json",
                file=sys.stderr,
            )
        skill_db.save_recommended(recommended_db, path=config.RECOMMENDED_PATH)
        skill_db.save_watchlist(watchlist_db, path=config.WATCHLIST_PATH)
    except Exception as exc:
        print(f"[workflows] skill_db save failed: {exc}", file=sys.stderr)

    # Regenerate indexes for workflows (with by_tool grouping).
    try:
        index_writer.write_indexes(
            recommended_db,
            base_dir=config.INDEX_DIR,
            categories=config.CATEGORIES,
            tools=getattr(config, "TOOLS", ("n8n", "make", "other")),
            default_category="general_workflow",
        )
    except Exception as exc:
        print(f"[workflows] index write failed: {exc}", file=sys.stderr)

    try:
        report_path = _write_report(analysis, date)
        print(f"[workflows] wrote {report_path}")
        try:
            state.save_state(items_by_source, path=config.STATE_PATH)
        except Exception as exc:
            print(f"[workflows] state save failed: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"[workflows] report write failed: {exc}", file=sys.stderr)

    try:
        telegram_client.send_text(telegram_text, bot_token, chat_id)
    except Exception as exc:
        print(f"[workflows] telegram send_text failed: {exc}", file=sys.stderr)
        print(summary)
        return 1

    try:
        state.mark_sent_today(path=config.STATE_PATH)
    except Exception as exc:
        print(f"[workflows] mark_sent failed: {exc}", file=sys.stderr)

    print("[WORKFLOWS_ANALYSIS_OK]")
    print(summary)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Workflows daily digest")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print fetched items instead of sending to Telegram (no API calls)",
    )
    parser.add_argument(
        "--no-analyzer",
        action="store_true",
        help="Skip LLM analysis and state I/O; send the legacy link digest",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the once-per-day idempotency guard (for manual reruns).",
    )
    args = parser.parse_args()
    return run(
        dry_run=args.dry_run, no_analyzer=args.no_analyzer, force=args.force
    )


if __name__ == "__main__":
    sys.exit(main())
