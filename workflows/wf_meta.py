"""Per-workflow metadata extraction for the catalog cards.

Computes the four card fields the web catalog renders as chips, in the EXACT
format the bundled n8n library uses (so the site's filters line up):

    node_count   int  — number of nodes/modules in the workflow JSON (>0)
    complexity   str  — "simple" (≤5) | "medium" (6–15) | "complex" (>15)
    integrations [str]— real external services (Slack, Gmail, OpenAI, …)
    trigger_type str  — "webhook" | "schedule" | "manual" | "chat" | "email" | …

All four are OPTIONAL and backwards-compatible: a workflow with no detectable
services simply omits ``integrations``; node_count==0 omits both node_count and
complexity. Nothing here raises — bad/partial JSON yields an empty result.

Pure functions only (no network); the network layer lives in the orchestrator /
backfill and feeds parsed JSON in here.
"""
from __future__ import annotations

import re
from collections import Counter

# --- complexity thresholds (must match the n8n library exactly) -------------
def complexity_for(node_count: int) -> str | None:
    if not node_count or node_count <= 0:
        return None
    if node_count <= 5:
        return "simple"
    if node_count <= 15:
        return "medium"
    return "complex"


# ---------------------------------------------------------------------------
# n8n
# ---------------------------------------------------------------------------
# Built-in control/util + generic-protocol node kinds (lowercased, prefix
# stripped). These are NOT external services, so they never appear in
# ``integrations``. Trigger nodes live here too — they drive ``trigger_type``,
# not the integration chips.
_N8N_GENERIC = {
    # control flow / data shaping
    "if", "switch", "merge", "set", "code", "function", "functionitem",
    "noop", "splitinbatches", "splitout", "aggregate", "itemlists", "filter",
    "sort", "limit", "renamekeys", "datetime", "movebinarydata", "markdown",
    "html", "htmlextract", "extractfromfile", "xml", "crypto", "stickynote",
    "comparedatasets", "removeduplicates", "summarize", "stopanderror", "wait",
    "executeworkflow", "executecommand", "converttofile", "editimage",
    "rename", "n8ntrainingcustomerdatastore", "debughelper",
    # generic protocols / transport (not a branded service)
    "httprequest", "http", "webhook", "respondtowebhook", "graphql",
    "emailsend", "emailreadimap", "readwritefile", "ftp", "ssh", "sse",
    "rssfeedread", "readbinaryfiles", "readbinaryfile", "writebinaryfile",
    "spreadsheetfile", "localfiletrigger",
    # triggers (consumed by trigger_type, excluded from integrations)
    "start", "manualtrigger", "scheduletrigger", "cron", "interval",
    "errortrigger", "executeworkflowtrigger", "n8ntrigger", "formtrigger",
    "chattrigger", "workflowtrigger",
    # n8n's own platform nodes — not an external service
    "n8n", "n8ntrainingcustomerdatastore", "noop",
}

# Branded node kind (lowercased) -> display name with correct casing. Anything
# not here falls back to ``_prettify``.
_N8N_SERVICE_NAMES = {
    "slack": "Slack", "telegram": "Telegram", "discord": "Discord",
    "gmail": "Gmail", "googlesheets": "Google Sheets",
    "googledrive": "Google Drive", "googledocs": "Google Docs",
    "googlecalendar": "Google Calendar", "googlebigquery": "Google BigQuery",
    "googletasks": "Google Tasks", "youtube": "YouTube",
    "notion": "Notion", "airtable": "Airtable", "hubspot": "HubSpot",
    "salesforce": "Salesforce", "pipedrive": "Pipedrive",
    "openai": "OpenAI", "openaiassistant": "OpenAI",
    "anthropic": "Anthropic", "mistralcloud": "Mistral",
    "postgres": "Postgres", "mysql": "MySQL", "mongodb": "MongoDB",
    "redis": "Redis", "supabase": "Supabase", "qdrant": "Qdrant",
    "pinecone": "Pinecone", "elasticsearch": "Elasticsearch",
    "twilio": "Twilio", "sendgrid": "SendGrid", "mailchimp": "Mailchimp",
    "mailgun": "Mailgun", "stripe": "Stripe", "shopify": "Shopify",
    "woocommerce": "WooCommerce", "wordpress": "WordPress",
    "github": "GitHub", "gitlab": "GitLab", "jira": "Jira",
    "trello": "Trello", "asana": "Asana", "clickup": "ClickUp",
    "monday": "Monday.com", "linear": "Linear", "zendesk": "Zendesk",
    "intercom": "Intercom", "twitter": "X (Twitter)", "linkedin": "LinkedIn",
    "facebookgraphapi": "Facebook", "instagram": "Instagram",
    "whatsapp": "WhatsApp", "dropbox": "Dropbox", "awss3": "AWS S3",
    "s3": "AWS S3", "microsoftoutlook": "Microsoft Outlook",
    "microsoftexcel": "Microsoft Excel", "microsoftteams": "Microsoft Teams",
    "microsoftonedrive": "Microsoft OneDrive", "baserow": "Baserow",
    "nocodb": "NocoDB", "ghost": "Ghost", "webflow": "Webflow",
    "calendly": "Calendly", "clockify": "Clockify",
    "lmchatopenai": "OpenAI", "lmchatanthropic": "Anthropic",
    "lmchatgooglegemini": "Google Gemini", "lmchatollama": "Ollama",
    "lmchatgroq": "Groq", "lmchatdeepseek": "DeepSeek",
    "lmchatopenrouter": "OpenRouter", "lmchatperplexity": "Perplexity",
    "lmchatmistralcloud": "Mistral", "lmchatazureopenai": "Azure OpenAI",
    "lmopenai": "OpenAI", "embeddingsopenai": "OpenAI",
    "embeddingsgooglegemini": "Google Gemini", "embeddingscohere": "Cohere",
    "embeddingsmistralcloud": "Mistral", "embeddingsazureopenai": "Azure OpenAI",
    "embeddingsollama": "Ollama", "embeddingshuggingfaceinference": "Hugging Face",
    "openrouter": "OpenRouter", "perplexity": "Perplexity",
    "deepseek": "DeepSeek", "elevenlabs": "ElevenLabs",
}

# LangChain (@n8n/n8n-nodes-langchain.*) framework plumbing — NOT a service.
# Provider nodes (lmChat*, embeddings*) are kept and mapped above; everything
# starting with one of these is internal wiring (agents, chains, memory,
# parsers, tools, splitters, vector stores) and must not become a chip.
_N8N_LC_PLUMBING_PREFIXES = (
    "agent", "chain", "memory", "outputparser", "tool", "textsplitter",
    "documentdefaultdataloader", "documentloader", "retriever",
    "informationextractor", "sentimentanalysis", "textclassifier",
    "vectorstore",
)

_ACRONYMS = {
    "Ai": "AI", "Api": "API", "Url": "URL", "Aws": "AWS", "Sql": "SQL",
    "Http": "HTTP", "Crm": "CRM", "Pdf": "PDF", "Id": "ID", "Io": "IO",
}


def _prettify(kind: str) -> str:
    """camelCase / lowercased node kind -> 'Title Cased' display name."""
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+", kind)
    if not parts:
        parts = [kind]
    words = []
    for p in parts:
        w = p if p.isupper() else p.capitalize()
        words.append(_ACRONYMS.get(w, w))
    return " ".join(words).strip()


def _n8n_kind(node_type: str) -> str:
    """'n8n-nodes-base.googleSheets' / '@n8n/n8n-nodes-langchain.lmChatOpenAi'
    -> last dotted segment, ORIGINAL case ('googleSheets' / 'lmChatOpenAi').
    Callers lowercase for lookups; ``_prettify`` needs the camelCase intact."""
    if not isinstance(node_type, str) or not node_type:
        return ""
    return node_type.rsplit(".", 1)[-1].strip()


def _n8n_node_lists(parsed) -> list[list]:
    """Return every ``nodes`` array reachable in a parsed n8n JSON (handles the
    single-workflow, wrapped, id-keyed-collection, and array shapes that the
    validator accepts)."""
    out: list[list] = []

    def _from(d):
        if isinstance(d, dict):
            nodes = d.get("nodes")
            if isinstance(nodes, list):
                out.append(nodes)
            wf = d.get("workflow")
            if isinstance(wf, dict):
                _from(wf)

    if isinstance(parsed, dict):
        if isinstance(parsed.get("nodes"), list):
            out.append(parsed["nodes"])
        elif isinstance(parsed.get("workflow"), dict):
            _from(parsed["workflow"])
        else:
            for v in parsed.values():
                _from(v)
    elif isinstance(parsed, list):
        for x in parsed:
            _from(x)
    return out


# Node kinds (lowercased) that are triggers but don't end in "trigger".
_N8N_TRIGGER_KINDS = {"webhook", "cron", "interval", "start", "emailreadimap"}


def _n8n_trigger_kind(kind_lower: str) -> str | None:
    """Classify a TRIGGER node's kind. Returns None for non-trigger nodes, so
    callers must only pass kinds that are actually triggers (guards against
    'lmChatOpenAi' matching 'chat', etc.)."""
    if not kind_lower:
        return None
    is_trigger = kind_lower.endswith("trigger") or kind_lower in _N8N_TRIGGER_KINDS
    if not is_trigger:
        return None
    if "webhook" in kind_lower:
        return "webhook"
    if "schedule" in kind_lower or "cron" in kind_lower or "interval" in kind_lower:
        return "schedule"
    if "chat" in kind_lower:
        return "chat"
    if "email" in kind_lower or "imap" in kind_lower:
        return "email"
    if "form" in kind_lower:
        return "form"
    if "manual" in kind_lower or kind_lower == "start":
        return "manual"
    # app/event triggers (slackTrigger, telegramTrigger, …) are webhook-style
    return "webhook"


# trigger_type preference when several triggers coexist.
_TRIGGER_PRIORITY = ["webhook", "schedule", "chat", "email", "form", "manual"]


def extract_n8n(parsed) -> dict:
    node_lists = _n8n_node_lists(parsed)
    node_count = sum(len(n) for n in node_lists)
    services: list[str] = []
    seen: set[str] = set()
    triggers: set[str] = set()
    for nodes in node_lists:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = _n8n_kind(node.get("type") or "")
            if not kind:
                continue
            kl = kind.lower()
            tk = _n8n_trigger_kind(kl)
            if tk:
                triggers.add(tk)
            if kl in _N8N_GENERIC:
                continue
            # App/event trigger nodes (telegramTrigger, slackTrigger) ARE a real
            # service — resolve them by their base name minus the Trigger suffix.
            base, disp = kl, kind
            if kl.endswith("trigger"):
                base, disp = kl[:-7], kind[:-7]
                if base in _N8N_GENERIC or not base:
                    continue
            # Drop LangChain framework plumbing (keep mapped lm*/embeddings*).
            if base not in _N8N_SERVICE_NAMES and base.startswith(
                _N8N_LC_PLUMBING_PREFIXES
            ):
                continue
            name = _N8N_SERVICE_NAMES.get(base) or _prettify(disp)
            if name and name.lower() not in seen:
                seen.add(name.lower())
                services.append(name)
    trigger = next((t for t in _TRIGGER_PRIORITY if t in triggers), None)
    return {
        "node_count": node_count,
        "integrations": services,
        "trigger_type": trigger,
    }


# ---------------------------------------------------------------------------
# Make (Integromat)
# ---------------------------------------------------------------------------
# Module prefixes that are flow-control / util, not external services.
_MAKE_GENERIC_PREFIXES = {
    "util", "builtin", "json", "gateway", "flow", "repeater", "basictrigger",
    "regexp", "tools", "datastore", "math", "text", "array", "date", "http",
    "scheduler", "webhook", "webhooks", "sleep", "parser", "csv", "xml",
}

_MAKE_SERVICE_NAMES = {
    "google-email": "Gmail", "google-sheets": "Google Sheets",
    "google-drive": "Google Drive", "google-docs": "Google Docs",
    "google-calendar": "Google Calendar", "slack": "Slack",
    "telegram": "Telegram", "discord": "Discord", "notion": "Notion",
    "airtable": "Airtable", "hubspot": "HubSpot crm", "openai-gpt-3": "OpenAI",
    "openai": "OpenAI", "anthropic-claude": "Anthropic",
    "stripe": "Stripe", "shopify": "Shopify", "wordpress": "WordPress",
    "mailchimp": "Mailchimp", "twilio": "Twilio", "hunterio": "Hunter.io",
    "linkedin": "LinkedIn", "facebook": "Facebook", "instagram": "Instagram",
}


def _make_module_lists(parsed) -> list[list]:
    out: list[list] = []

    def _from(d):
        if isinstance(d, dict):
            for key in ("flow", "modules"):
                if isinstance(d.get(key), list):
                    out.append(d[key])
            bp = d.get("blueprint")
            if isinstance(bp, dict):
                _from(bp)

    if isinstance(parsed, dict):
        if isinstance(parsed.get("flow"), list):
            out.append(parsed["flow"])
        elif isinstance(parsed.get("modules"), list):
            out.append(parsed["modules"])
        elif isinstance(parsed.get("blueprint"), dict):
            _from(parsed["blueprint"])
        else:
            for v in parsed.values():
                _from(v)
    elif isinstance(parsed, list):
        for x in parsed:
            _from(x)
    return out


def _make_prefix(module: str) -> tuple[str, str]:
    """'google-email:ActionSendEmail' -> ('google-email', 'ActionSendEmail')."""
    if not isinstance(module, str) or ":" not in module:
        return (module or "").strip().lower(), ""
    pref, _, action = module.partition(":")
    return pref.strip().lower(), action.strip()


def extract_make(parsed) -> dict:
    module_lists = _make_module_lists(parsed)
    node_count = sum(len(m) for m in module_lists)
    services: list[str] = []
    seen: set[str] = set()
    trigger: str | None = None
    for modules in module_lists:
        for mod in modules:
            if not isinstance(mod, dict):
                continue
            pref, action = _make_prefix(mod.get("module") or "")
            blob = f"{pref}:{action}".lower()
            if trigger is None:
                if "webhook" in blob or "customhook" in blob or "hook" in blob:
                    trigger = "webhook"
                elif "watch" in blob or "trigger" in blob:
                    trigger = "schedule"
            if not pref or pref in _MAKE_GENERIC_PREFIXES:
                continue
            name = _MAKE_SERVICE_NAMES.get(pref) or _prettify(
                pref.replace("-", " ").replace("_", " ")
            )
            if name and name.lower() not in seen:
                seen.add(name.lower())
                services.append(name)
    return {
        "node_count": node_count,
        "integrations": services,
        "trigger_type": trigger,
    }


# ---------------------------------------------------------------------------
# dispatch + merge + field assembly
# ---------------------------------------------------------------------------
def extract(tool: str, parsed) -> dict:
    """Single-workflow extraction. Never raises."""
    try:
        if (tool or "").lower() == "make":
            return extract_make(parsed)
        return extract_n8n(parsed)
    except Exception:
        return {"node_count": 0, "integrations": [], "trigger_type": None}


def merge(metas: list[dict]) -> dict:
    """Combine per-workflow metas for a repo-level entry: sum node_count, union
    integrations (order-preserving), most-common trigger_type."""
    node_count = 0
    services: list[str] = []
    seen: set[str] = set()
    triggers: list[str] = []
    for m in metas or []:
        node_count += int(m.get("node_count") or 0)
        for s in m.get("integrations") or []:
            if s.lower() not in seen:
                seen.add(s.lower())
                services.append(s)
        t = m.get("trigger_type")
        if t:
            triggers.append(t)
    trigger = None
    if triggers:
        counts = Counter(triggers)
        top = max(counts.values())
        # tie-break by first-seen order among the most common
        for t in triggers:
            if counts[t] == top:
                trigger = t
                break
    return {
        "node_count": node_count,
        "integrations": services,
        "trigger_type": trigger,
    }


def fields_for(meta: dict) -> dict:
    """Turn a (possibly merged) meta into the catalog fields, applying the
    optional/omit rules: node_count>0 or skip it + complexity; non-empty
    integrations only; trigger_type only if detected."""
    out: dict = {}
    nc = int(meta.get("node_count") or 0)
    if nc > 0:
        out["node_count"] = nc
        cx = complexity_for(nc)
        if cx:
            out["complexity"] = cx
    integrations = [s for s in (meta.get("integrations") or []) if s]
    if integrations:
        out["integrations"] = integrations
    trigger = meta.get("trigger_type")
    if trigger:
        out["trigger_type"] = trigger
    return out


def fields_from_workflows(tool: str, parsed_workflows: list) -> dict:
    """Convenience: parsed JSON objects -> catalog fields for one entry."""
    metas = [extract(tool, p) for p in (parsed_workflows or [])]
    return fields_for(merge(metas))


__all__ = [
    "complexity_for", "extract", "extract_n8n", "extract_make",
    "merge", "fields_for", "fields_from_workflows",
]
