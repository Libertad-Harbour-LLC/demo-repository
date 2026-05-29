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
    # Domain-targeted SKILL.md queries — counter the coding bias by directly
    # surfacing non-coding skills (marketing, content, video, photo, web, design)
    # that the popularity sort would otherwise truncate below dev-tool repos.
    'filename:SKILL.md marketing OR seo OR copywriting',
    'filename:SKILL.md content OR blog OR newsletter OR social',
    'filename:SKILL.md video OR youtube OR shorts OR subtitle',
    'filename:SKILL.md image OR photo OR design OR presentation OR slides',
    'filename:SKILL.md website OR landing OR frontend OR webflow',
    'filename:SKILL.md agent OR chatbot OR bot OR assistant',
]

REDDIT_SUBREDDITS = [
    # Claude / AI / coding communities
    "ClaudeAI",
    "ChatGPTCoding",
    "AI_Agents",
    "cursor",
    "LocalLLaMA",
    # Domain communities — broaden discovery beyond coding. The
    # REDDIT_KEYWORDS_FILTER below still keeps only skill-related posts,
    # so these surface Claude-skill discussion in non-dev niches without
    # flooding the digest with generic posts.
    "marketing",
    "SEO",
    "content_marketing",
    "socialmedia",
    "Entrepreneur",
    "NewTubers",
    "VideoEditing",
    "webdev",
    "web_design",
    "nocode",
    "copywriting",
    "Blogging",
    "chatbots",
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

MAX_ITEMS_PER_SOURCE = 80  # was 50 — gave more headroom so low-star niche
# (marketing/content/video/photo/web/design) skills survive the star-sort
# truncation instead of being crowded out by high-star dev-tool repos.

VERIFY_GITHUB_SKILLS = True  # if True, hit the repo's /.claude/skills/ path to confirm

APIFY_TWITTER_ACTOR = "apidojo~tweet-scraper"
APIFY_THREADS_ACTOR = "apify~threads-scraper"
