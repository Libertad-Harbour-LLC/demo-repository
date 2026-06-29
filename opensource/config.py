"""Configuration for the Open Source radar pipeline.

Discovers ready-to-use / self-hostable open-source **products & platforms**
(not Claude skills, not n8n/Make workflows) — things you can deploy as-is,
rebrand + attach an API, or vibe-code on top of to ship your own service.
Data lives under ``digests/opensource/`` — fully isolated from the other
pipelines. Reuses trendwatch primitives via import.
"""

KEYWORDS = [
    "open source alternative",
    "self-hostable",
    "self-hosted ai",
    "open source saas",
]

# Repo topics that tend to tag deployable OSS products/platforms across domains
# (deliberately broad — video, avatars, ads, agents, apps, dev-tools, …).
GITHUB_TOPICS = [
    "open-source-alternative",
    "self-hosted",
    "selfhosted",
    "saas-alternative",
    "ai-agents",
    "ai-tools",
    "text-to-video",
    "ai-video",
    "ugc",
    "ai-influencer",
    "ai-avatars",
    "llm-app",
    "boilerplate",
]

# Repo-search queries over name/description/readme. The legacy search API does
# NOT support OR, so each is a single-phrase query; results are repo-level.
GITHUB_DESC_QUERIES = [
    '"open source alternative" in:readme,description',
    '"open-source alternative to" in:readme',
    '"self-hostable" in:readme,description',
    '"self-hosted" "open source" in:readme',
    '"rebrand" "self-host" in:readme',
    '"deploy your own" in:readme,description',
]

# Seed repos: the owner-provided examples + a curated diverse set. They are
# injected as candidates every run so the analyzer evaluates and (if they
# qualify) promotes them — guarantees the bot is populated from day one and
# the seeds make it into the DB. Spread across domains on purpose.
SEED_REPOS = [
    # owner-provided
    "https://github.com/calesthio/OpenMontage",
    "https://github.com/Autom8AI/Open-Higgsfield-AI",
    "https://github.com/NickIBrody/arcade_ai",
    "https://github.com/arelove/infinity-loop",
    "https://github.com/hexo-ai/sia",
    "https://github.com/nesquena/hermes-webui",
    "https://github.com/Lum1104/Understand-Anything",
    # curated diverse
    "https://github.com/Anil-matcha/Open-Generative-AI",
    "https://github.com/Anil-matcha/Open-AI-UGC",
    "https://github.com/GuijiAI/HeyGem.ai",
    "https://github.com/mutonby/openshorts",
    "https://github.com/seanZhang414/openadserver",
    "https://github.com/FlowiseAI/Flowise",
    "https://github.com/activepieces/activepieces",
    "https://github.com/every-app/open-seo",
]

SOURCES = {
    "github_oss": True,
}

MAX_ITEMS_PER_SOURCE = 80

# Data dir (relative to repo root) — fully isolated from skills/workflows data
DATA_DIR = "digests/opensource"
STATE_PATH = f"{DATA_DIR}/state.json"
RECOMMENDED_PATH = f"{DATA_DIR}/recommended.json"
WATCHLIST_PATH = f"{DATA_DIR}/watchlist.json"
INDEX_DIR = f"{DATA_DIR}/index"
DIGEST_DIR = DATA_DIR  # YYYY-MM-DD.md goes here

# Categories (slug -> Russian label), broad to cover any deployable OSS product.
CATEGORIES = (
    "video_oss",
    "avatars_oss",
    "image_oss",
    "marketing_oss",
    "agents_oss",
    "automation_oss",
    "devtools_oss",
    "apps_oss",
    "data_oss",
    "general_oss",
)
DEFAULT_CATEGORY = "general_oss"
