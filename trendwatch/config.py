"""Configuration for the trendwatch system.

Edit this file to change keywords, subreddits, or source toggles.
No secrets here — those live in GitHub Secrets / env vars.
"""

KEYWORDS = [
    "vibe coding",
    "claude code",
    "cursor ai",
    "ai agents",
    "ai marketing",
    "growth hacking ai",
    "gpt prompts",
    "llm tools",
    "marketing automation ai",
]

GITHUB_TOPICS = [
    "vibe-coding",
    "ai-agents",
    "llm",
    "claude",
    "marketing-automation",
    "growth-hacking",
]

REDDIT_SUBREDDITS = [
    "LocalLLaMA",
    "ChatGPTCoding",
    "ClaudeAI",
    "cursor",
    "SideProject",
    "marketing",
    "growthhacking",
    "Entrepreneur",
]

REDDIT_MIN_SCORE = 20

SOURCES = {
    "github": True,
    "reddit": True,
    "twitter": True,
    "threads": True,
}

MAX_ITEMS_PER_SOURCE = 10

APIFY_TWITTER_ACTOR = "apidojo~tweet-scraper"
APIFY_THREADS_ACTOR = "apify~threads-scraper"
