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
]
GITHUB_TOPICS_MAKE = [
    "make-blueprint",
    "make-template",
    "integromat",
    "integromat-blueprint",
]

# Code-search queries that find workflow JSON files
GITHUB_CODE_QUERIES_N8N = [
    'path:workflows extension:json "nodes" "connections"',
    'extension:json "n8n" "credentials"',
]
GITHUB_CODE_QUERIES_MAKE = [
    'extension:json "blueprint" "scenario"',
    'path:blueprints extension:json "modules"',
]

REDDIT_SUBREDDITS = [
    "n8n",
    "MakeAutomations",
    "integromat",
    "automation",
    "nocode",
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

MAX_ITEMS_PER_SOURCE = 15

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
    "data_workflow",
    "devops_workflow",
    "content_workflow",
    "general_workflow",
)

# Tool tags for the by_tool index grouping
TOOLS = ("n8n", "make", "other")
