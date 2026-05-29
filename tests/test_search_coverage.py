"""Discovery-coverage + bot-search regression tests.

Two concerns, both offline (no network):

1. **Discovery coverage** — the skills and workflows pipelines must actually
   *look* for each domain the product cares about: coding, vibe-coding,
   content automation, photo/image generation, video, bots, agents, websites,
   marketing. We assert that across all discovery surfaces (GitHub code
   queries, topics, keyword lists, subreddits, category enums) there is at
   least one term per domain. If someone narrows the queries back to a
   coding-only set, this fails loudly.

2. **Bot /search** — `screen_search` must find items by a domain substring
   across title / description / skills_in_repo, in any language.
"""
from __future__ import annotations

import pytest


# --- 1. Discovery coverage ------------------------------------------------

def _skills_corpus() -> str:
    from trendwatch import config, index_writer

    parts: list[str] = []
    parts += config.GITHUB_CODE_QUERIES
    parts += config.GITHUB_TOPICS
    parts += config.KEYWORDS
    parts += config.REDDIT_SUBREDDITS
    parts += config.REDDIT_KEYWORDS_FILTER
    parts += list(index_writer.CATEGORIES)
    return " ".join(parts).lower()


def _workflows_corpus() -> str:
    from trendwatch import links
    from workflows import config

    parts: list[str] = []
    parts += config.GITHUB_CODE_QUERIES_N8N
    parts += config.GITHUB_CODE_QUERIES_MAKE
    parts += config.GITHUB_TOPICS_N8N
    parts += config.GITHUB_TOPICS_MAKE
    parts += config.KEYWORDS
    parts += config.REDDIT_SUBREDDITS
    parts += config.REDDIT_KEYWORDS_FILTER
    parts += list(config.CATEGORIES)
    parts += list(links.WORKFLOWS_CATEGORIES)
    return " ".join(parts).lower()


# Each domain → at least one of these substrings must appear in the corpus.
_CORE_DOMAINS = {
    "content": ["content", "blog", "social", "newsletter", "copywriting"],
    "photo": ["photo", "image"],
    "video": ["video", "youtube", "shorts"],
    "bots": ["bot", "chatbot"],
    "agents": ["agent"],
    "websites": ["website", "web", "landing", "frontend", "wordpress"],
    "marketing": ["marketing", "seo", "lead"],
}

# Domains that only make sense for the skills pipeline (n8n/Make are no-code,
# so "coding"/"vibe coding" aren't workflow categories).
_SKILLS_ONLY_DOMAINS = {
    "coding": ["coding", "code", "refactor", "debug"],
    "vibe_coding": ["vibe"],
}


def _covered(corpus: str, alternatives: list[str]) -> bool:
    return any(term in corpus for term in alternatives)


@pytest.mark.parametrize("domain,alts", {**_CORE_DOMAINS, **_SKILLS_ONLY_DOMAINS}.items())
def test_skills_discovery_covers_domain(domain, alts):
    corpus = _skills_corpus()
    assert _covered(corpus, alts), (
        f"skills discovery has no term for '{domain}' "
        f"(expected one of {alts}) — add a GitHub query / topic / subreddit"
    )


@pytest.mark.parametrize("domain,alts", _CORE_DOMAINS.items())
def test_workflows_discovery_covers_domain(domain, alts):
    corpus = _workflows_corpus()
    assert _covered(corpus, alts), (
        f"workflows discovery has no term for '{domain}' "
        f"(expected one of {alts}) — add a GitHub query / topic / subreddit"
    )


# --- 2. Bot /search -------------------------------------------------------

def _recommended_db(items: list[dict]) -> dict:
    return {"skills": {it["url"]: it for it in items}}


_SEARCH_FIXTURE = [
    {"url": "https://github.com/acme/video-suite", "title": "acme/video-suite",
     "description": "генерация видео и коротких роликов", "category": "video_skill"},
    {"url": "https://github.com/acme/photo-gen", "title": "acme/photo-gen",
     "description": "генерация фото и изображений", "category": "photo_skill"},
    {"url": "https://github.com/acme/telegram-bot-kit", "title": "acme/telegram-bot-kit",
     "description": "создание чат-ботов и агентов", "category": "general_skill"},
    {"url": "https://github.com/acme/site-builder", "title": "acme/site-builder",
     "description": "сборка сайтов и лендингов", "category": "webdev_skill"},
    {"url": "https://github.com/acme/content-factory", "title": "acme/content-factory",
     "description": "фабрика контента и автопостинг", "category": "content_skill"},
    {"url": "https://github.com/acme/refactor-helper", "title": "acme/refactor-helper",
     "description": "кодинг-ассистент: рефактор и дебаг", "category": "vibe_coding_skill"},
]


@pytest.fixture
def _bot_with_fixture(monkeypatch):
    from api import telegram as tg

    def fake_fetch(source_key: str) -> dict:
        return _recommended_db(_SEARCH_FIXTURE) if source_key == "skills" else {"skills": {}}

    monkeypatch.setattr(tg, "_fetch", fake_fetch)
    monkeypatch.setattr(tg, "_fetch_watchlist", lambda source_key: {"items": {}})
    return tg


@pytest.mark.parametrize("query,expect_repo", [
    ("видео", "video-suite"),
    ("фото", "photo-gen"),
    ("bot", "telegram-bot-kit"),
    ("агент", "telegram-bot-kit"),
    ("сайт", "site-builder"),
    ("контент", "content-factory"),
    ("рефактор", "refactor-helper"),
])
def test_bot_search_finds_each_domain(_bot_with_fixture, query, expect_repo):
    text, _kb = _bot_with_fixture.screen_search(query)
    assert expect_repo in text, f"/search '{query}' did not surface {expect_repo}\n{text}"


def test_bot_search_empty_query_is_handled(_bot_with_fixture):
    text, _kb = _bot_with_fixture.screen_search("   ")
    assert "Пустой запрос" in text


def test_bot_search_no_match_reports_nothing_found(_bot_with_fixture):
    text, _kb = _bot_with_fixture.screen_search("zzz-nonexistent-term")
    assert "ничего не нашлось" in text
