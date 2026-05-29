"""Configuration for the workflows trendwatch pipeline.

Edit this file to change keywords, source toggles, or thresholds.
"""

# n8n and Make workflow tracking

KEYWORDS = [
    "n8n workflow",
    "n8n template",
    "make.com workflow",
    "make blueprint",
    "integromat blueprint",
    "automation workflow",
]

GITHUB_TOPICS_N8N = [
    "n8n",
    "n8n-workflow",
    "n8n-workflows",
    "n8n-template",
    "n8n-templates",
    "n8n-automation",
    "n8n-nodes",
    "automation",
]
GITHUB_TOPICS_MAKE = [
    "make-blueprint",
    "make-template",
    "integromat",
    "integromat-blueprint",
    "make-automation",
    "make-scenarios",
    "no-code-automation",
]

# Code-search queries that find workflow JSON files
GITHUB_CODE_QUERIES_N8N = [
    'path:workflows extension:json "nodes" "connections"',
    'extension:json "n8n" "credentials"',
    'extension:json "nodes" "connections" "n8n-nodes-base"',
    'path:n8n extension:json "workflow"',
    'filename:workflow.json "n8n"',
    # Domain-targeted — counter the devops/data bias by directly surfacing
    # marketing/content/video/photo/web n8n workflows that the popularity
    # sort would otherwise truncate below infra/automation repos.
    'extension:json "nodes" "connections" marketing OR seo OR leads',
    'extension:json "nodes" "connections" content OR social OR blog',
    'extension:json "nodes" "connections" video OR youtube OR image',
    'extension:json "nodes" "connections" website OR webhook OR wordpress',
    'extension:json "nodes" "connections" bot OR chatbot OR agent OR telegram OR discord',
]
GITHUB_CODE_QUERIES_MAKE = [
    'extension:json "blueprint" "scenario"',
    'path:blueprints extension:json "modules"',
    'extension:json "make" "scenario" "modules"',
    'filename:blueprint.json',
    # Domain-targeted Make blueprints (see n8n note above).
    'extension:json "modules" marketing OR social OR content',
    'extension:json "modules" video OR image OR youtube',
    'extension:json "modules" website OR wordpress OR shopify',
    'extension:json "modules" bot OR chatbot OR agent OR telegram',
]

REDDIT_SUBREDDITS = [
    # Automation / no-code communities
    "n8n",
    "MakeAutomations",
    "integromat",
    "automation",
    "nocode",
    # Domain communities — broaden discovery beyond devops/data automation.
    # REDDIT_KEYWORDS_FILTER still keeps only workflow/template/json posts, so
    # these surface domain-specific automations without flooding the digest.
    "marketing",
    "socialmedia",
    "content_marketing",
    "SEO",
    "Entrepreneur",
    "smallbusiness",
    "SaaS",
    "webdev",
    "NewTubers",
    "ecommerce",
    "AI_Agents",
    "chatbots",
]
REDDIT_KEYWORDS_FILTER = [
    "workflow",
    "template",
    ".json",
    "blueprint",
    "import",
    "automation",
]
REDDIT_MIN_SCORE = 5

SOURCES = {
    "n8n_github": True,
    "make_github": True,
    "reddit": True,
}

MAX_ITEMS_PER_SOURCE = 80  # was 50 — gave more headroom so low-star niche
# (marketing/content/video/photo/web) workflows survive the star-sort
# truncation instead of being crowded out by high-star devops/automation repos.

# Verification: for n8n, fetch the JSON and check it has "nodes" and "connections" keys.
# For Make, check for "blueprint"/"flow" structure. Skip verification if file is too big.
VERIFY_WORKFLOW_JSON = True
MAX_JSON_FETCH_BYTES = 200_000  # don't pull megabyte JSONs

# Data dir (relative to repo root) — fully isolated from skills data
DATA_DIR = "digests/workflows"
STATE_PATH = f"{DATA_DIR}/state.json"
RECOMMENDED_PATH = f"{DATA_DIR}/recommended.json"
WATCHLIST_PATH = f"{DATA_DIR}/watchlist.json"
INDEX_DIR = f"{DATA_DIR}/index"
DIGEST_DIR = DATA_DIR  # daily YYYY-MM-DD.md goes here

# Categories for workflows
CATEGORIES = (
    "marketing_workflow",
    "sales_workflow",
    "content_workflow",
    "video_workflow",
    "photo_workflow",
    "web_workflow",
    "data_workflow",
    "devops_workflow",
    "general_workflow",
)

# Tool tags for the by_tool index grouping
TOOLS = ("n8n", "make", "other")
