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

# NOTE: the legacy /search/code API does NOT support OR — multi-term queries
# are ANDed, so the old "marketing OR seo OR copywriting" style never did
# what it looked like. Domain targeting therefore uses one single-term query
# per domain. Each query costs one paced request (~7.5s apart) against code
# search's 10-requests/min budget.
GITHUB_CODE_QUERIES = [
    'path:.claude/skills filename:SKILL.md',
    'path:skills filename:SKILL.md "claude"',
    'filename:SKILL.md "name:" "description:"',  # YAML-frontmatter skills at root or any depth
    'path:.claude filename:SKILL.md',
    # Domain-targeted SKILL.md queries — counter the coding bias by directly
    # surfacing non-coding skills that the star sort would otherwise truncate
    # below dev-tool repos.
    'filename:SKILL.md marketing',
    'filename:SKILL.md seo',
    'filename:SKILL.md content',
    'filename:SKILL.md social',
    'filename:SKILL.md video',
    'filename:SKILL.md image',
    'filename:SKILL.md presentation',
    'filename:SKILL.md website',
    'filename:SKILL.md agent',
    'filename:SKILL.md chatbot',
    # Cross-agent skill dirs (borrowed from vercel-labs/skills PRIORITY_PREFIXES):
    # the SKILL.md format is shared across agents, so skills published for
    # Codex/OpenCode/Windsurf/etc. work in Claude Code too. Each query is one
    # paced request; we take the most active dirs, not all 28.
    'path:.agents/skills filename:SKILL.md',
    'path:.codex/skills filename:SKILL.md',
    'path:.opencode/skills filename:SKILL.md',
    'path:.github/skills filename:SKILL.md',
    'path:.windsurf/skills filename:SKILL.md',
]

# skills.sh registry search (vercel-labs/skills backend). One GET per query;
# results carry INSTALL COUNTS — real usage telemetry, a stronger traction
# signal than stars for niche skills. Domain-targeted like the code queries.
SKILLS_SH_QUERIES = [
    "marketing",
    "seo",
    "content",
    "social media",
    "video",
    "image",
    "presentation",
    "website",
    "design",
    "chatbot",
    "agent",
    "automation",
    "email",
    "writing",
    "analytics",
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
    "skills_sh": True,  # skills.sh registry (vercel-labs/skills backend) —
                        # install-count traction signal + registry-only repos.
    "reddit": False,    # disabled — Reddit 403-blocks Actions IPs and the
                        # OAuth route needs API creds we don't maintain; it
                        # contributed 0 every run and only spammed logs. Flip
                        # to True (+ set REDDIT_CLIENT_ID/SECRET) to re-enable.
    "twitter": False,   # disabled per Sprint 3 — too noisy for this niche
    "threads": False,   # disabled per Sprint 3
}

MAX_ITEMS_PER_SOURCE = 80  # was 50 — gave more headroom so low-star niche
# (marketing/content/video/photo/web/design) skills survive the star-sort
# truncation instead of being crowded out by high-star dev-tool repos.

VERIFY_GITHUB_SKILLS = True  # if True, hit the repo's /.claude/skills/ path to confirm

APIFY_TWITTER_ACTOR = "apidojo~tweet-scraper"
APIFY_THREADS_ACTOR = "apify~threads-scraper"
