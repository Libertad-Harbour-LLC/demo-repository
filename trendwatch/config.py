"""Configuration for the trendwatch system.

Edit this file to change keywords, source toggles, or thresholds.
No secrets here — those live in GitHub Secrets / env vars.
"""

KEYWORDS = [
    "claude code skill",
    "claude skill",
    "SKILL.md",
    ".claude/skills",
    "claude marketplace skill",
]

GITHUB_TOPICS = [
    "claude-skill",
    "claude-skills",
    "claude-code-skill",
    "claude-code-skills",
    "claude-code",
    "anthropic-claude",
    "agent-skill",
]

GITHUB_CODE_QUERIES = [
    'path:.claude/skills filename:SKILL.md',
    'path:skills filename:SKILL.md "claude"',
    'filename:SKILL.md "name:" "description:"',  # YAML-frontmatter skills at root or any depth
    'path:.claude filename:SKILL.md',
]

REDDIT_SUBREDDITS = [
    "ClaudeAI",
    "ChatGPTCoding",
    "AI_Agents",
    "cursor",
    "LocalLLaMA",
]

REDDIT_KEYWORDS_FILTER = [
    "skill",
    ".claude/skills",
    "SKILL.md",
    "claude code skill",
    "claude skill",
]

REDDIT_MIN_SCORE = 5  # lowered — Claude Skills are niche, posts get less score

SOURCES = {
    "github": True,
    "reddit": True,
    "twitter": False,   # disabled per Sprint 3 — too noisy for this niche
    "threads": False,   # disabled per Sprint 3
}

MAX_ITEMS_PER_SOURCE = 50  # was 15 — too aggressive, hid most candidates from the LLM

VERIFY_GITHUB_SKILLS = True  # if True, hit the repo's /.claude/skills/ path to confirm

APIFY_TWITTER_ACTOR = "apidojo~tweet-scraper"
APIFY_THREADS_ACTOR = "apify~threads-scraper"
