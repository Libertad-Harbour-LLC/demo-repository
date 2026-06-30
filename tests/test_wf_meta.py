"""Tests for workflows card-metadata extraction (wf_meta) + enrichment glue."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflows import wf_meta, wf_enrich  # noqa: E402


# --- complexity thresholds (must match the n8n library) --------------------
def test_complexity_thresholds():
    assert wf_meta.complexity_for(1) == "simple"
    assert wf_meta.complexity_for(5) == "simple"
    assert wf_meta.complexity_for(6) == "medium"
    assert wf_meta.complexity_for(15) == "medium"
    assert wf_meta.complexity_for(16) == "complex"
    assert wf_meta.complexity_for(99) == "complex"
    assert wf_meta.complexity_for(0) is None
    assert wf_meta.complexity_for(-3) is None


# --- n8n extraction --------------------------------------------------------
def _n8n(nodes):
    return {"nodes": nodes, "connections": {}}


def test_n8n_node_count_and_integrations():
    wf = _n8n([
        {"type": "n8n-nodes-base.scheduleTrigger", "name": "cron"},
        {"type": "n8n-nodes-base.slack", "name": "post"},
        {"type": "n8n-nodes-base.googleSheets", "name": "log"},
        {"type": "n8n-nodes-base.if", "name": "branch"},      # generic
        {"type": "n8n-nodes-base.set", "name": "set"},        # generic
        {"type": "n8n-nodes-base.httpRequest", "name": "http"},  # generic
    ])
    meta = wf_meta.extract("n8n", wf)
    assert meta["node_count"] == 6
    assert meta["integrations"] == ["Slack", "Google Sheets"]
    assert meta["trigger_type"] == "schedule"


def test_n8n_trigger_priority_and_dedup():
    wf = _n8n([
        {"type": "n8n-nodes-base.webhook", "name": "hook"},
        {"type": "n8n-nodes-base.scheduleTrigger", "name": "cron"},
        {"type": "n8n-nodes-base.slack", "name": "a"},
        {"type": "n8n-nodes-base.slack", "name": "b"},  # duplicate service
    ])
    meta = wf_meta.extract("n8n", wf)
    assert meta["trigger_type"] == "webhook"        # webhook beats schedule
    assert meta["integrations"] == ["Slack"]         # de-duplicated


def test_n8n_app_trigger_is_webhook():
    wf = _n8n([{"type": "n8n-nodes-base.telegramTrigger", "name": "t"}])
    meta = wf_meta.extract("n8n", wf)
    assert meta["trigger_type"] == "webhook"
    # the trigger node is a Telegram one -> Telegram is also a real service
    assert meta["integrations"] == ["Telegram"]


def test_n8n_langchain_service_naming():
    wf = _n8n([
        {"type": "@n8n/n8n-nodes-langchain.lmChatOpenAi", "name": "llm"},
        {"type": "n8n-nodes-base.manualTrigger", "name": "m"},
    ])
    meta = wf_meta.extract("n8n", wf)
    assert meta["integrations"] == ["OpenAI"]
    assert meta["trigger_type"] == "manual"


def test_n8n_langchain_plumbing_filtered_but_providers_kept():
    wf = _n8n([
        {"type": "@n8n/n8n-nodes-langchain.chatTrigger"},
        {"type": "@n8n/n8n-nodes-langchain.agent"},                # plumbing
        {"type": "@n8n/n8n-nodes-langchain.chainLlm"},             # plumbing
        {"type": "@n8n/n8n-nodes-langchain.memoryBufferWindow"},   # plumbing
        {"type": "@n8n/n8n-nodes-langchain.outputParserStructured"},  # plumbing
        {"type": "@n8n/n8n-nodes-langchain.toolWorkflow"},         # plumbing
        {"type": "@n8n/n8n-nodes-langchain.lmChatOpenAi"},         # provider -> OpenAI
        {"type": "@n8n/n8n-nodes-langchain.embeddingsOpenAi"},     # provider -> OpenAI
    ])
    meta = wf_meta.extract("n8n", wf)
    assert meta["integrations"] == ["OpenAI"]   # plumbing dropped, provider kept
    assert meta["trigger_type"] == "chat"


def test_n8n_prettify_unknown_service():
    wf = _n8n([{"type": "n8n-nodes-base.mauticCampaign", "name": "x"}])
    meta = wf_meta.extract("n8n", wf)
    assert meta["integrations"] == ["Mautic Campaign"]


def test_n8n_array_of_workflows_sums_nodes():
    parsed = [
        _n8n([{"type": "n8n-nodes-base.slack"}, {"type": "n8n-nodes-base.if"}]),
        _n8n([{"type": "n8n-nodes-base.gmail"}]),
    ]
    meta = wf_meta.extract("n8n", parsed)
    assert meta["node_count"] == 3
    assert meta["integrations"] == ["Slack", "Gmail"]


# --- Make extraction -------------------------------------------------------
def test_make_modules_and_trigger():
    bp = {"flow": [
        {"module": "gateway:CustomWebHook"},
        {"module": "google-email:ActionSendEmail"},
        {"module": "util:SetVariables"},     # generic
        {"module": "http:ActionSendData"},   # generic (protocol)
        {"module": "slack:CreateMessage"},
    ]}
    meta = wf_meta.extract("make", bp)
    assert meta["node_count"] == 5
    assert meta["integrations"] == ["Gmail", "Slack"]
    assert meta["trigger_type"] == "webhook"


def test_make_blueprint_wrapped():
    bp = {"blueprint": {"flow": [
        {"module": "airtable:WatchRecords"},
        {"module": "openai-gpt-3:CreateCompletion"},
    ]}}
    meta = wf_meta.extract("make", bp)
    assert meta["node_count"] == 2
    assert meta["integrations"] == ["Airtable", "OpenAI"]
    assert meta["trigger_type"] == "schedule"   # "Watch" => polling/schedule


# --- field assembly + omit rules -------------------------------------------
def test_fields_omit_rules():
    # zero nodes -> no node_count, no complexity
    assert wf_meta.fields_for({"node_count": 0, "integrations": [], "trigger_type": None}) == {}
    # no services -> integrations omitted; trigger omitted when None
    f = wf_meta.fields_for({"node_count": 3, "integrations": [], "trigger_type": None})
    assert f == {"node_count": 3, "complexity": "simple"}
    # full set
    f2 = wf_meta.fields_for(
        {"node_count": 12, "integrations": ["HubSpot", "Slack"], "trigger_type": "webhook"}
    )
    assert f2 == {
        "node_count": 12, "complexity": "medium",
        "integrations": ["HubSpot", "Slack"], "trigger_type": "webhook",
    }


def test_merge_sums_unions_and_picks_trigger():
    merged = wf_meta.merge([
        {"node_count": 4, "integrations": ["Slack"], "trigger_type": "webhook"},
        {"node_count": 13, "integrations": ["Slack", "Gmail"], "trigger_type": "schedule"},
        {"node_count": 0, "integrations": [], "trigger_type": "schedule"},
    ])
    assert merged["node_count"] == 17
    assert merged["integrations"] == ["Slack", "Gmail"]   # union, order kept
    assert merged["trigger_type"] == "schedule"           # most common
    assert wf_meta.fields_for(merged)["complexity"] == "complex"


def test_extract_never_raises_on_garbage():
    for bad in [None, 42, "x", {"nodes": "notalist"}, {"flow": 3}, [1, 2, 3]]:
        m = wf_meta.extract("n8n", bad)
        assert m["node_count"] == 0
        assert wf_meta.fields_for(m) == {}


# --- enrichment glue (injected fetcher) ------------------------------------
def test_enrich_db_writes_fields_and_respects_only_missing():
    db = {"skills": {
        "u1": {"tool": "n8n", "skills_in_repo": ["a"]},
        "u2": {"tool": "n8n", "node_count": 99},   # already has meta
    }}

    def fake_fetch(entry):
        return [_n8n([
            {"type": "n8n-nodes-base.webhook"},
            {"type": "n8n-nodes-base.hubspot"},
        ])]

    n = wf_enrich.enrich_db(db, fake_fetch, only_missing=True)
    assert n == 1
    assert db["skills"]["u1"]["node_count"] == 2
    assert db["skills"]["u1"]["complexity"] == "simple"
    assert db["skills"]["u1"]["integrations"] == ["HubSpot"]
    assert db["skills"]["u1"]["trigger_type"] == "webhook"
    # u2 untouched
    assert db["skills"]["u2"]["node_count"] == 99


def test_enrich_db_url_filter_and_fetch_failure_is_safe():
    db = {"skills": {"u1": {"tool": "n8n"}, "u2": {"tool": "n8n"}}}

    def boom(entry):
        raise RuntimeError("network down")

    n = wf_enrich.enrich_db(db, boom, urls=["u1"])
    assert n == 0
    assert "node_count" not in db["skills"]["u1"]


def test_owner_repo_from_polluted_repo_full_name():
    e = {"repo_full_name": "Foo/Bar: some-workflow", "url": "https://github.com/Foo/Bar"}
    assert wf_enrich.owner_repo_from_entry(e) == "Foo/Bar"
    e2 = {"repo_full_name": "", "url": "https://github.com/A/B.git"}
    assert wf_enrich.owner_repo_from_entry(e2) == "A/B"


# --- catalog payload -------------------------------------------------------
def test_catalog_build_payload_and_push_guard(monkeypatch):
    from workflows import catalog
    db = {"skills": {"u1": {"tool": "n8n", "node_count": 3}}}
    assert catalog.build_payload(db) == {"workflows": {"u1": {"tool": "n8n", "node_count": 3}}}

    # no secret -> skipped, never posts
    res, err = catalog.push_recommended(db, secret="")
    assert res is None and "AUTOMATION_INGEST_SECRET" in err

    # empty db -> nothing to push
    res, err = catalog.push_recommended({"skills": {}}, secret="s")
    assert res is None and "empty" in err

    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"ok": True, "workflows": 1}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResp()

    res, err = catalog.push_recommended(db, secret="sekret", post=fake_post)
    assert err is None and res == {"ok": True, "workflows": 1}
    assert captured["headers"]["x-automation-secret"] == "sekret"
    assert captured["url"].endswith("/ingest-automation-workflows")
    assert captured["json"] == {"workflows": db["skills"]}
