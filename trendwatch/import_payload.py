"""Build the machine-readable ``## Import payload`` block for Daily Skill Radar.

This is the **bot side** of the contract documented in
``docs/skill-radar-import-payload.md``: the catalog importer (``/claude-skills``)
reads ONLY this JSON block and never parses the prose/tables of the report.

The single hard requirement that drives the design is *completeness*
(contract §4.1): ``repo.skills`` must list EVERY skill folder in the repo.
The analyzer's ``skills_in_repo`` is truncated for the human summary
("52 skills: a, b, c…"), so we never trust it as the source of truth — we
join the analyzer output against the original fetched items (which carry the
full ``skills`` array of ``{name, path, url}``) by repo URL / full name.

Pure functions only; no I/O. ``build_payload`` returns a dict ready for
``json.dumps`` — ``report.to_markdown`` serialises and embeds it.
"""
from __future__ import annotations

import re
from typing import Any

RADAR_VERSION = "1.0"

# Active category dictionary (catalog shelves): slug -> Russian title.
# These are the ONLY active categories; the per-skill enricher and the
# analyzer must reuse these slugs. Anything new is surfaced as
# ``status: "suggested"`` with a rationale and is never assigned to a skill.
SKILL_CATEGORY_NAMES: dict[str, str] = {
    "vibe-coding": "Вайбкодинг",
    "engineering": "Инженерия",
    "automation": "Автоматизация",
    "marketing": "Маркетинг",
    "content": "Контент",
    "design": "Дизайн",
    "research": "Исследования",
    "documentation": "Документация",
    "testing": "Тестирование",
    "data": "Данные",
    "ai-tooling": "AI-тулинг",
    "devops": "DevOps",
    "security": "Безопасность",
    "integration": "Интеграции",
    "orchestration": "Оркестрация",
    "productivity": "Продуктивность",
    "seo": "SEO",
    "learning": "Обучение",
    "general": "Общее",
}

# Map the pipeline's own normalized category slugs (and common variants) onto
# the catalog dictionary above, so a repo's analyzer-assigned category always
# resolves to a real shelf.
CATEGORY_ALIASES: dict[str, str] = {
    "vibe-coding": "vibe-coding",
    "coding": "vibe-coding",
    "webdev": "engineering",
    "web-development": "engineering",
    "frontend": "engineering",
    "video": "content",
    "photo": "content",
    "image": "content",
    "ai-content": "ai-tooling",
    "ai-content-generation": "ai-tooling",
    "ml": "ai-tooling",
    "sales": "marketing",
    "social": "marketing",
    "smm": "marketing",
    "docs": "documentation",
    "qa": "testing",
    "infra": "devops",
    "ops": "devops",
    "ci-cd": "devops",
    "api": "integration",
    "knowledge": "learning",
    "education": "learning",
}


def resolve_category(value: str | None, default: str = "general") -> str:
    """Normalize a raw category to a known catalog slug, applying aliases.

    Returns ``default`` (clamped to the dictionary) when the value maps to
    nothing known — callers that need to detect "unknown" should compare
    ``normalize_category`` + ``CATEGORY_ALIASES`` against
    ``SKILL_CATEGORY_NAMES`` themselves.
    """
    slug = normalize_category(value)
    slug = CATEGORY_ALIASES.get(slug, slug)
    if slug in SKILL_CATEGORY_NAMES:
        return slug
    return default if default in SKILL_CATEGORY_NAMES else "general"

_GITHUB_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s#?]+)", re.IGNORECASE)
# Broad emoji / symbol ranges + markdown emphasis we strip from plain-text fields.
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "←-⇿⌀-⏿⬀-⯿️‍]"
)
_DESC_MAX = 300


def normalize_category(value: str | None) -> str:
    """``vibe_coding_skill`` -> ``vibe-coding``; ``Data Skill`` -> ``data``.

    Lower-case, strip a trailing ``_skill``/``_workflow`` suffix, then map
    underscores/spaces to hyphens and drop stray punctuation.
    """
    s = (value or "").strip().lower()
    for suf in ("_skill", "-skill", " skill", "_workflow", "-workflow", " workflow"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def clean_text(value: Any, max_len: int = _DESC_MAX) -> str:
    """Plain-text, single line, no markdown/emoji, no surrounding quotes."""
    if value is None:
        return ""
    t = str(value)
    t = t.replace("`", "").replace("*", "").replace("#", "")
    t = t.replace("[", "").replace("]", "")
    t = _EMOJI_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.strip("\"'").strip()
    if len(t) > max_len:
        t = t[:max_len].rstrip() + "…"
    return t


def _github_owner_repo(entry: dict, item: dict | None) -> str | None:
    """Return ``owner/repo`` in its **original case** (for the canonical URL
    and display name) or None if the entry is not a GitHub repo. The caller
    lower-cases it for the ``slug`` upsert key.
    """
    # 1. explicit repo_full_name on the joined item
    full = (item or {}).get("repo_full_name") if item else None
    if isinstance(full, str) and "/" in full:
        return full.strip()
    # 2. analyzer ``name`` shaped like "owner/repo" (drop any ": workflow" tail)
    name = entry.get("name") or ""
    head = name.split(":", 1)[0].strip()
    if head.count("/") == 1 and " " not in head:
        return head
    # 3. parse a github.com URL from entry or item
    for url in (entry.get("url"), (item or {}).get("url") if item else None):
        if isinstance(url, str):
            m = _GITHUB_RE.search(url)
            if m:
                repo = m.group(2)
                if repo.endswith(".git"):
                    repo = repo[:-4]
                return f"{m.group(1)}/{repo}"
    return None


def _index_items(items: list[dict] | None) -> tuple[dict, dict]:
    """Build (by_url, by_repo_full_name_lower) lookups from fetched items."""
    by_url: dict[str, dict] = {}
    by_repo: dict[str, dict] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        url = it.get("url")
        if isinstance(url, str) and url and url not in by_url:
            by_url[url] = it
        full = it.get("repo_full_name")
        if isinstance(full, str) and "/" in full:
            by_repo.setdefault(full.lower(), it)
    return by_url, by_repo


def _skill_objects(
    item: dict | None,
    entry: dict,
    owner_repo: str,
    category_slug: str,
    rating: float | int | None,
) -> list[dict]:
    """Full skill list for the repo (completeness rule). Prefer the fetched
    item's ``skills`` array (name/path/url); fall back to the analyzer's
    ``skills_in_repo`` names, synthesising canonical deep links on ``main``.
    """
    out: list[dict] = []
    seen: set[str] = set()

    raw_skills = (item or {}).get("skills") if item else None
    if isinstance(raw_skills, list) and raw_skills:
        for s in raw_skills:
            if not isinstance(s, dict):
                continue
            name = (s.get("name") or "").strip()
            url = (s.get("url") or "").strip()
            if not name or not url or url in seen:
                continue
            seen.add(url)
            out.append(_skill_obj(name, url, category_slug, rating))
        return out

    # Fallback: names only -> synthesise the canonical deep link on main.
    for name in entry.get("skills_in_repo") or []:
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        url = f"https://github.com/{owner_repo}/tree/main/.claude/skills/{name}"
        if url in seen:
            continue
        seen.add(url)
        out.append(_skill_obj(name, url, category_slug, rating))
    return out


def _skill_obj(name: str, url: str, category_slug: str, rating) -> dict:
    obj = {
        "slug": name,
        "name": name,
        "url": url,
        "category": category_slug,
    }
    if isinstance(rating, (int, float)) and not isinstance(rating, bool):
        obj["rating"] = rating
    return obj


def _build_repo(entry: dict, decision: str, by_url: dict, by_repo: dict) -> dict | None:
    item = None
    url = entry.get("url")
    if isinstance(url, str):
        item = by_url.get(url)
    owner_repo = _github_owner_repo(entry, item)
    if not owner_repo:
        return None  # non-GitHub (e.g. reddit-only watch item) — not catalog material
    slug = owner_repo.lower()
    if item is None:
        item = by_repo.get(slug)

    category_slug = resolve_category(entry.get("category"))
    rating = entry.get("final_score")
    if not isinstance(rating, (int, float)) or isinstance(rating, bool):
        rating = None

    repo: dict = {
        "slug": slug,
        "name": (item or {}).get("repo_full_name") or entry.get("name") or owner_repo,
        "url": f"https://github.com/{owner_repo}",
        "decision": decision,
        "category": category_slug,
        "rating": rating if rating is not None else 0,
        "skills": _skill_objects(item, entry, owner_repo, category_slug, rating),
    }
    stars = (item or {}).get("stars")
    if isinstance(stars, int):
        repo["github_stars"] = stars
    forks = (item or {}).get("forks")
    if isinstance(forks, int):
        repo["github_forks"] = forks
    desc = clean_text(entry.get("description") or entry.get("what"))
    if desc:
        repo["description"] = desc
    return repo


def _normalize_suggested(raw: Any) -> dict | None:
    """Coerce a raw suggested-category dict into the contract shape, or None.

    Dropped when the slug is empty or actually a *known* dictionary slug
    (a known shelf is active, never "suggested").
    """
    if not isinstance(raw, dict):
        return None
    slug = normalize_category(raw.get("slug"))
    if not slug or slug in SKILL_CATEGORY_NAMES:
        return None
    return {
        "slug": slug,
        "name": clean_text(raw.get("name")) or slug.replace("-", " ").title(),
        "status": "suggested",
        "rationale": clean_text(raw.get("rationale"), max_len=400),
    }


def _categories(repos: list[dict], suggested: list[dict] | None) -> list[dict]:
    """Active shelves actually referenced by repos/skills (must be in the
    dictionary) + de-duplicated suggested shelves (must NOT be in it)."""
    out: list[dict] = []
    seen: set[str] = set()
    for repo in repos:
        slugs = [repo.get("category")] + [s.get("category") for s in repo.get("skills", [])]
        for slug in slugs:
            if slug in SKILL_CATEGORY_NAMES and slug not in seen:
                seen.add(slug)
                out.append({"slug": slug, "name": SKILL_CATEGORY_NAMES[slug], "status": "active"})
    for sug in suggested or []:
        norm = _normalize_suggested(sug)
        if norm and norm["slug"] not in seen:
            seen.add(norm["slug"])
            out.append(norm)
    return out


def _meta_suggested(analysis: dict) -> list[dict]:
    meta = analysis.get("metadata") if isinstance(analysis, dict) else None
    raw = (meta or {}).get("suggested_categories") if isinstance(meta, dict) else None
    return list(raw or [])


def assemble_payload(
    repos: list[dict],
    date: str,
    suggested: list[dict] | None = None,
    *,
    radar_version: str = RADAR_VERSION,
) -> dict:
    return {
        "radar_version": radar_version,
        "date": date,
        "categories": _categories(repos, suggested),
        "repos": repos,
    }


def build_payload(
    analysis: dict,
    items: list[dict] | None,
    date: str,
    *,
    radar_version: str = RADAR_VERSION,
) -> dict:
    """Assemble the import payload dict. ``repos`` covers ``top_test``
    (decision=test_now) and ``top_watch`` (decision=watch); test_now wins on
    a slug collision. Non-GitHub entries are skipped.
    """
    by_url, by_repo = _index_items(items)
    repos: list[dict] = []
    seen_slugs: set[str] = set()
    for bucket, decision in (("top_test", "test_now"), ("top_watch", "watch")):
        for entry in analysis.get(bucket) or []:
            if not isinstance(entry, dict):
                continue
            repo = _build_repo(entry, decision, by_url, by_repo)
            if repo is None or repo["slug"] in seen_slugs:
                continue
            seen_slugs.add(repo["slug"])
            repos.append(repo)

    return assemble_payload(
        repos, date, _meta_suggested(analysis), radar_version=radar_version
    )


def apply_category_updates(payload: dict, extra_suggested: list[dict] | None = None) -> dict:
    """Re-derive ``payload['categories']`` after enrichment changed per-skill
    categories. Preserves already-present suggested shelves and merges any new
    ones discovered during enrichment. Mutates and returns ``payload``.
    """
    prior_suggested = [c for c in payload.get("categories", []) if c.get("status") == "suggested"]
    merged = prior_suggested + list(extra_suggested or [])
    payload["categories"] = _categories(payload.get("repos", []), merged)
    return payload


def make_repo_entry(
    owner_repo: str,
    branch: str,
    skill_names: list[str],
    *,
    stars: int | None = None,
    category: str = "general",
    rating: float | int = 0,
    decision: str = "test_now",
    description: str | None = None,
) -> dict:
    """Build a base Repo entry from a known skill-folder listing — used by the
    backfill path, which has no analyzer output. Skills get canonical deep
    links; enrichment fills description/category/tags afterwards.
    """
    cat = resolve_category(category)
    skills = []
    for name in skill_names:
        name = (name or "").strip()
        if not name:
            continue
        skills.append(_skill_obj(
            name,
            f"https://github.com/{owner_repo}/tree/{branch}/.claude/skills/{name}",
            cat,
            rating,
        ))
    repo = {
        "slug": owner_repo.lower(),
        "name": owner_repo,
        "url": f"https://github.com/{owner_repo}",
        "decision": decision,
        "category": cat,
        "rating": rating,
        "skills": skills,
    }
    if isinstance(stars, int):
        repo["github_stars"] = stars
    desc = clean_text(description)
    if desc:
        repo["description"] = desc
    return repo


__all__ = [
    "RADAR_VERSION",
    "SKILL_CATEGORY_NAMES",
    "CATEGORY_ALIASES",
    "normalize_category",
    "resolve_category",
    "clean_text",
    "build_payload",
    "assemble_payload",
    "apply_category_updates",
    "make_repo_entry",
]
