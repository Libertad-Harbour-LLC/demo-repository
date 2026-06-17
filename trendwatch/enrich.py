"""Per-skill enrichment for the catalog Import payload.

For each ``test_now`` repo we read every skill's ``SKILL.md`` (raw GitHub) and
ask Claude, in batches, for three fields per skill:

- ``description`` — 1-2 sentences IN RUSSIAN: what it does and what for, naming
  the platforms/tools and their synonyms (e.g. «Инстаграм», «Reels», «SMM») so
  the website's keyword search finds it;
- ``category`` — a slug from the catalog dictionary
  (``import_payload.SKILL_CATEGORY_NAMES``), defaulting to the repo category;
- ``tags`` — 3-7 english slugs (lowercase-hyphen).

Network + LLM live here, behind injectable ``md_fetch`` / ``claude_complete``
seams so the logic is unit-testable without hitting GitHub or Anthropic.
Failures degrade gracefully: a skill keeps its base slug/name/url/category.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Callable

import requests

try:
    from . import import_payload
except ImportError:  # pragma: no cover
    import import_payload

RAW_BASE = "https://raw.githubusercontent.com"
DEFAULT_MODEL = os.environ.get("ENRICH_MODEL", "claude-haiku-4-5-20251001").strip()
DEFAULT_BATCH = int(os.environ.get("ENRICH_BATCH_SIZE", "8") or 8)
# Per-repo cap so a 300-skill repo can't blow the token budget in one run.
DEFAULT_MAX_PER_REPO = int(os.environ.get("ENRICH_MAX_SKILLS_PER_REPO", "60") or 60)
SKILL_MD_MAX_CHARS = 4000
MAX_TAGS = 7
MIN_TAGS = 3

# skill.url is ``github.com/<owner>/<repo>/tree/<branch>/<path>`` (path ends at
# the skill folder). We turn it into the raw SKILL.md URL.
_SKILL_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+?)/?$", re.IGNORECASE)

_SYSTEM_PROMPT = """\
Ты обогащаешь карточки Claude Code Skills для веб-каталога с поиском по словам.
На вход — несколько скиллов (id, репозиторий, имя папки, фрагмент SKILL.md).
Для КАЖДОГО верни объект с полями:
- "id": тот же id, что во входе;
- "description": 1–2 предложения ПО-РУССКИ — что делает скилл и для чего.
  ОБЯЗАТЕЛЬНО упоминай платформы/инструменты и их синонимы (например
  «Инстаграм», «Reels», «Шортс», «SMM», «лендинг», «n8n»), потому что сайт
  ищет по этим словам. Без markdown, эмодзи и кавычек по краям.
- "category": РОВНО один slug из словаря категорий ниже. Если ничего не
  подходит — поставь дефолтную (категория репозитория) и дополнительно верни
  "suggest": {"slug": "<новый-slug>", "name": "<рус. имя>", "rationale": "<1 фраза>"}.
  Новые категории НЕ присваивай скиллу — только предлагай в "suggest".
- "tags": массив из 3–7 английских слагов в нижнем регистре через дефис
  (например ["instagram","reels","content-automation"]).

Верни СТРОГО валидный JSON: {"results": [ {...}, {...} ]}. Без префиксов и
markdown-обёртки. Не выдумывай фактов, которых нет в SKILL.md; если данных
мало — опиши по имени папки и репозиторию.

Словарь категорий (slug = русское имя):
"""


def _category_dictionary_text() -> str:
    return "\n".join(
        f"- {slug} = {name}" for slug, name in import_payload.SKILL_CATEGORY_NAMES.items()
    )


def raw_skill_md_url(skill_url: str | None) -> str | None:
    m = _SKILL_URL_RE.search(skill_url or "")
    if not m:
        return None
    owner, repo, branch, path = m.groups()
    return f"{RAW_BASE}/{owner}/{repo}/{branch}/{path}/SKILL.md"


def _default_md_fetch(url: str | None) -> str:
    if not url:
        return ""
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return r.text[:SKILL_MD_MAX_CHARS]
    except Exception as exc:
        print(f"[enrich] SKILL.md fetch failed {url}: {exc}", file=sys.stderr)
    return ""


def _make_anthropic_completer(model: str) -> Callable[[str, str], str] | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        print("[enrich] anthropic SDK not installed — skipping enrichment", file=sys.stderr)
        return None
    client = anthropic.Anthropic(api_key=api_key)

    def complete(system_text: str, user_text: str) -> str:
        resp = client.messages.create(
            model=model,
            max_tokens=2000,
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_text}],
        )
        parts = []
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", "") or "")
        return "".join(parts)

    return complete


def _parse_results(text: str) -> list[dict]:
    if not text:
        return []
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*\n?", "", t)
        t = re.sub(r"\n?```\s*$", "", t)
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            return []
    results = data.get("results") if isinstance(data, dict) else data
    return [r for r in (results or []) if isinstance(r, dict)]


def normalize_tags(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for t in raw:
        if not isinstance(t, str):
            continue
        s = t.strip().lower()
        s = re.sub(r"[\s_]+", "-", s)
        s = re.sub(r"[^a-z0-9-]+", "", s)
        s = re.sub(r"-{2,}", "-", s).strip("-")
        if s and s not in out:
            out.append(s)
    return out[:MAX_TAGS]


def _apply_result(skill: dict, result: dict, repo_category: str, suggested: dict) -> None:
    desc = import_payload.clean_text(result.get("description"))
    if desc:
        skill["description"] = desc

    raw_cat = result.get("category")
    norm = import_payload.normalize_category(raw_cat)
    norm = import_payload.CATEGORY_ALIASES.get(norm, norm)
    if norm in import_payload.SKILL_CATEGORY_NAMES:
        skill["category"] = norm
    else:
        skill["category"] = repo_category  # unknown -> keep repo default

    sug = result.get("suggest")
    if isinstance(sug, dict):
        slug = import_payload.normalize_category(sug.get("slug"))
        if slug and slug not in import_payload.SKILL_CATEGORY_NAMES and slug not in suggested:
            suggested[slug] = {
                "slug": slug,
                "name": import_payload.clean_text(sug.get("name")) or slug.replace("-", " ").title(),
                "rationale": import_payload.clean_text(sug.get("rationale"), max_len=400),
            }

    tags = normalize_tags(result.get("tags"))
    if tags:
        skill["tags"] = tags


def _process_batch(batch: list[tuple], claude_complete, suggested: dict) -> None:
    """batch items: (skill_dict, repo_category, repo_name, skill_md)."""
    lines = ["Скиллы для обогащения:"]
    for i, (skill, repo_cat, repo_name, md) in enumerate(batch):
        lines.append(
            f"\n--- id={i} ---\n"
            f"repo: {repo_name}\n"
            f"skill_folder: {skill.get('slug') or skill.get('name')}\n"
            f"default_category: {repo_cat}\n"
            f"SKILL.md:\n{md or '(пусто / не удалось прочитать)'}"
        )
    user_text = "\n".join(lines)
    try:
        text = claude_complete(_SYSTEM_PROMPT + _category_dictionary_text(), user_text)
    except Exception as exc:
        print(f"[enrich] Claude call failed for batch of {len(batch)}: {exc}", file=sys.stderr)
        return
    by_id = {}
    for r in _parse_results(text):
        try:
            by_id[int(r.get("id"))] = r
        except (TypeError, ValueError):
            continue
    for i, (skill, repo_cat, _repo_name, _md) in enumerate(batch):
        result = by_id.get(i)
        if result:
            _apply_result(skill, result, repo_cat, suggested)


def enrich_payload(
    payload: dict,
    *,
    md_fetch: Callable[[str | None], str] = _default_md_fetch,
    claude_complete: Callable[[str, str], str] | None = None,
    batch_size: int = DEFAULT_BATCH,
    max_per_repo: int = DEFAULT_MAX_PER_REPO,
    model: str = DEFAULT_MODEL,
) -> list[dict]:
    """Enrich the skills of every ``test_now`` repo in ``payload`` in place.

    Returns the list of suggested (new, not-in-dictionary) categories Claude
    proposed, ready to merge via ``import_payload.apply_category_updates``.
    No-op (returns ``[]``) if no completer is available (missing key/SDK).
    """
    if claude_complete is None:
        claude_complete = _make_anthropic_completer(model)
        if claude_complete is None:
            print("[enrich] no Anthropic completer — skipping enrichment", file=sys.stderr)
            return []

    suggested: dict[str, dict] = {}
    batch: list[tuple] = []
    enriched = 0
    for repo in payload.get("repos", []):
        if repo.get("decision") != "test_now":
            continue
        repo_cat = repo.get("category") or "general"
        repo_name = repo.get("name") or repo.get("slug") or ""
        for skill in (repo.get("skills") or [])[:max_per_repo]:
            md = md_fetch(raw_skill_md_url(skill.get("url")))
            batch.append((skill, repo_cat, repo_name, md))
            enriched += 1
            if len(batch) >= batch_size:
                _process_batch(batch, claude_complete, suggested)
                batch = []
    if batch:
        _process_batch(batch, claude_complete, suggested)

    print(f"[enrich] enriched {enriched} skill(s); {len(suggested)} suggested category(ies)",
          file=sys.stderr)
    return list(suggested.values())


__all__ = ["enrich_payload", "raw_skill_md_url", "normalize_tags", "DEFAULT_BATCH"]
