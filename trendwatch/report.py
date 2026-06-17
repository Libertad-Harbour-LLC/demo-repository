"""Render the JSON analysis blob into a human-readable Markdown report.

Used to write ``digests/YYYY-MM-DD.md`` after each successful analyzer run so
we get a permanent, browsable archive in the repo.

When ``items`` is supplied (skills pipeline only), a single machine-readable
``## Import payload`` JSON block is appended for the ``/claude-skills`` catalog
importer — see ``import_payload.py`` and ``docs/skill-radar-import-payload.md``.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from . import import_payload
except ImportError:  # pragma: no cover - script-style import fallback
    import import_payload


def _fmt_scores(scores: dict | None) -> str:
    if not isinstance(scores, dict):
        return ""
    order = ["novelty", "traction", "utility", "testability", "business_impact", "noise_risk"]
    parts = [f"{k}={scores.get(k, '?')}" for k in order if k in scores]
    return ", ".join(parts)


def _safe(x: Any, default: str = "") -> str:
    if x is None:
        return default
    if isinstance(x, str):
        return x
    return str(x)


def to_markdown(analysis: dict, date: str, items: list[dict] | None = None) -> str:
    """Render the analyzer JSON dict into a Markdown report.

    ``items`` are the original fetched items (with their full ``skills``
    arrays). When provided, a single ``## Import payload`` JSON block is
    appended per the catalog-import contract. When ``None`` (e.g. the
    workflows pipeline, which has its own schema), no payload is emitted.
    """
    lines: list[str] = []
    lines.append(f"# Daily Skill Radar — {date}")
    lines.append("")

    main = analysis.get("main_takeaway")
    if main:
        lines.append("## Main takeaway")
        lines.append("")
        lines.append(_safe(main))
        lines.append("")

    summary = analysis.get("executive_summary")
    if summary:
        lines.append("## Executive summary")
        lines.append("")
        lines.append(_safe(summary))
        lines.append("")

    rankings = analysis.get("rankings") or []
    if rankings:
        lines.append("## Rankings")
        lines.append("")
        lines.append("| # | Skill | Category | Final | Confidence | Decision | Source | URL |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in rankings:
            if not isinstance(r, dict):
                continue
            lines.append(
                "| {rank} | {skill} | {cat} | {fs} | {conf} | {dec} | {src} | {url} |".format(
                    rank=_safe(r.get("rank")),
                    skill=_safe(r.get("skill")),
                    cat=_safe(r.get("category")),
                    fs=_safe(r.get("final_score")),
                    conf=_safe(r.get("confidence")),
                    dec=_safe(r.get("decision")),
                    src=_safe(r.get("source")),
                    url=_safe(r.get("url")),
                )
            )
        lines.append("")

    top_test = analysis.get("top_test") or []
    if top_test:
        lines.append("## Top — test now")
        lines.append("")
        for t in top_test:
            if not isinstance(t, dict):
                continue
            lines.append(f"### {_safe(t.get('name'))}")
            lines.append("")
            if t.get("category"):
                lines.append(f"- **Category:** {_safe(t.get('category'))}")
            if t.get("what"):
                lines.append(f"- **What:** {_safe(t.get('what'))}")
            if t.get("problem"):
                lines.append(f"- **Problem:** {_safe(t.get('problem'))}")
            if t.get("why_growing"):
                lines.append(f"- **Why growing:** {_safe(t.get('why_growing'))}")
            if t.get("evidence"):
                lines.append(f"- **Evidence:** {_safe(t.get('evidence'))}")
            scores = _fmt_scores(t.get("scores"))
            if scores:
                lines.append(f"- **Scores:** {scores}")
            if t.get("final_score") is not None:
                lines.append(f"- **Final score:** {_safe(t.get('final_score'))}")
            if t.get("confidence"):
                lines.append(f"- **Confidence:** {_safe(t.get('confidence'))}")
            steps = t.get("test_steps") or []
            if steps:
                lines.append("- **Test steps:**")
                for i, step in enumerate(steps, 1):
                    lines.append(f"  {i}. {_safe(step)}")
            if t.get("metric"):
                lines.append(f"- **Metric:** {_safe(t.get('metric'))}")
            if t.get("expected_result"):
                lines.append(f"- **Expected:** {_safe(t.get('expected_result'))}")
            if t.get("risk"):
                lines.append(f"- **Risk:** {_safe(t.get('risk'))}")
            lines.append("")

    graduates = analysis.get("graduated_from_watch") or []
    if graduates:
        lines.append("## Promoted from watchlist this run")
        lines.append("")
        for g in graduates:
            if not isinstance(g, dict):
                continue
            name = _safe(g.get("repo_full_name") or g.get("title") or g.get("name"))
            url = _safe(g.get("url"))
            trigger = _safe(g.get("trigger"))
            signal = _safe(g.get("signal_to_wait"))
            line = f"- **{name}** — trigger: {trigger}"
            if signal:
                line += f" (original signal: {signal})"
            if url:
                line += f" — <{url}>"
            lines.append(line)
        lines.append("")

    top_watch = analysis.get("top_watch") or []
    if top_watch:
        lines.append("## Top — watch")
        lines.append("")
        for w in top_watch:
            if not isinstance(w, dict):
                continue
            lines.append(
                f"- **{_safe(w.get('name'))}** — {_safe(w.get('why_interesting'))} "
                f"(signal to wait: {_safe(w.get('signal_to_wait'))})"
            )
        lines.append("")

    top_skip = analysis.get("top_skip") or []
    if top_skip:
        lines.append("## Top — skip")
        lines.append("")
        for s in top_skip:
            if not isinstance(s, dict):
                continue
            lines.append(f"- **{_safe(s.get('name'))}** — {_safe(s.get('reason'))}")
        lines.append("")

    best = analysis.get("best_pick")
    if isinstance(best, dict) and best:
        lines.append("## Best pick of the day")
        lines.append("")
        if best.get("name"):
            lines.append(f"**{_safe(best.get('name'))}**")
            lines.append("")
        if best.get("why"):
            lines.append(f"- **Why:** {_safe(best.get('why'))}")
        if best.get("comparison"):
            lines.append(f"- **Comparison:** {_safe(best.get('comparison'))}")
        if best.get("first_test"):
            lines.append(f"- **First test:** {_safe(best.get('first_test'))}")
        if best.get("metric"):
            lines.append(f"- **Metric:** {_safe(best.get('metric'))}")
        lines.append("")

    excluded = analysis.get("excluded")
    if isinstance(excluded, dict) and excluded:
        lines.append("## Excluded")
        lines.append("")
        for cat, names in excluded.items():
            if not names:
                continue
            lines.append(f"### {cat}")
            lines.append("")
            for n in names:
                if isinstance(n, dict):
                    lines.append(f"- {_safe(n.get('name') or n)}")
                else:
                    lines.append(f"- {_safe(n)}")
            lines.append("")

    self_check = analysis.get("self_check")
    if isinstance(self_check, dict) and self_check:
        lines.append("## Self-check")
        lines.append("")
        for k, v in self_check.items():
            lines.append(f"- **{k}:** {_safe(v)}")
        lines.append("")

    meta = analysis.get("metadata")
    if isinstance(meta, dict) and meta:
        lines.append("## Metadata")
        lines.append("")
        for k, v in meta.items():
            lines.append(f"- **{k}:** {_safe(v)}")
        lines.append("")

    summary_text = analysis.get("telegram_summary")
    if summary_text:
        lines.append("## Telegram summary (sent)")
        lines.append("")
        lines.append("```")
        lines.append(_safe(summary_text))
        lines.append("```")
        lines.append("")

    # Machine-readable catalog-import block (skills pipeline only). Exactly one
    # ``## Import payload`` section; importer reads only this, never the prose.
    if items is not None:
        payload = import_payload.build_payload(analysis, items, date)
        if payload.get("repos"):
            lines.append("## Import payload")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["to_markdown"]
