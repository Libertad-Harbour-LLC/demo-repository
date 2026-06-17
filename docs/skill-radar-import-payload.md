# Daily Skill Radar → `/claude-skills` import payload (contract)

Contract between the **bot** that generates `digests/YYYY-MM-DD.md` (the
trendwatch skills pipeline) and the **catalog importer** (`/claude-skills`).
The bot produces the block per this format; the importer is built exactly
against it.

Bot side lives in [`trendwatch/import_payload.py`](../trendwatch/import_payload.py)
(builder) + [`trendwatch/report.py`](../trendwatch/report.py) (embeds it).
Importer side / idempotency (§5) is **out of scope here** — it lives in the
catalog project.

Domain terms — Skill / Repo / Tag / Category / Rating / Stars / Skill Radar —
are defined in `CONTEXT.md`.

## 1. Principle

- The human-readable report (Executive summary, Rankings, Top — test now,
  Telegram summary, …) **stays as-is**.
- One machine-readable section `## Import payload` with a fenced ` ```json `
  block is appended.
- The importer reads **only** that block and **never** parses prose/tables.

## 2. Placement

A section titled `## Import payload`, immediately followed by exactly one
` ```json … ``` ` block holding an object of the schema below.

- Valid JSON: no comments, no trailing commas, double quotes.
- UTF-8; emoji/markdown inside strings are forbidden.
- More than one `## Import payload` block in a file ⇒ error; there must be exactly one.

## 3. Structure

```
{
  radar_version : string        // schema version, starts at "1.0"
  date          : "YYYY-MM-DD"
  categories    : Category[]
  repos         : Repo[]
}
```

### Category
| Field | Type | Req | Rule |
|---|---|---|---|
| `slug` | string | yes | lower-case, hyphens, no spaces, no `_skill` suffix (`vibe_coding_skill` → `vibe-coding`) |
| `name` | string | yes | human-readable shelf name |
| `status` | `"active"` \| `"suggested"` | yes | `active` — from the dictionary handed to the bot; `suggested` — new, proposed by the bot |
| `rationale` | string | if `suggested` | 1–2 sentences: why a new shelf is needed |

### Repo
| Field | Type | Req | Rule |
|---|---|---|---|
| `slug` | string | yes | `owner/repo` lower-case — **repo identity (upsert key)** |
| `name` | string | yes | as on GitHub, e.g. `PackmindHub/packmind` |
| `url` | string | yes | `https://github.com/<owner>/<repo>` |
| `decision` | `"test_now"` \| `"watch"` \| `"skip"` | yes | only `test_now` is imported into the catalog |
| `category` | string | yes | default shelf slug for the repo's skills |
| `rating` | number | yes | repo `Final` score |
| `github_stars` | integer | no | from `Evidence` |
| `github_forks` | integer | no | from `Evidence` |
| `description` | string | no | plain-text, 1–2 sentences, no newlines/markdown |
| `skills` | Skill[] | yes | **every** skill in the repo (completeness rule) |

### Skill
| Field | Type | Req | Rule |
|---|---|---|---|
| `slug` | string | yes | skill folder name in `.claude/skills/` |
| `name` | string | yes | display name |
| `url` | string | yes | deep link `https://github.com/<owner>/<repo>/tree/<branch>/.claude/skills/<slug>` — **global upsert key** |
| `description` | string | no | plain-text, 1–2 sentences |
| `category` | string | yes | shelf slug; defaults to repo `category` but always set |
| `tags` | string[] | no | lower-case, hyphens |
| `rating` | number | no | defaults to repo `rating` |

## 4. Hard rules

1. **Completeness.** `repo.skills` contains **every** skill of the repo (one
   per folder in `.claude/skills/`). No "…", no "+N more", no truncation.
   This is the whole point — the bot joins the analyzer output against the
   fetched item's full `skills` array, never the truncated prose list.
2. **Stable identifiers (idempotent-upsert keys):** repo by `repo.slug`
   (`owner/repo` lower-case); skill by `skill.url` (canonical deep link).
3. **Normalization.** All `slug`/`category`/`tags` lower-case, hyphens, no
   spaces, no `_skill` suffix. URLs canonical github.com.
4. **Categories from the dictionary.** The bot is handed the current Category
   dictionary (`slug → name`); it reuses existing slugs and does not spawn
   synonyms. New shelves go in `categories[]` with `status:"suggested"` +
   `rationale` and are **not** assigned to skills until approved.
5. **`decision`** is per-repo. The bot may include `watch`/`skip` (importer
   filters) or only `test_now`; the field is always required. *This bot emits
   `test_now` (top_test) + `watch` (top_watch); `skip` is omitted.*
6. **`description`** — plain-text, 1–2 sentences, no newlines, no markdown,
   no wrapping quotes.
7. **Numbers** (`rating`, `github_stars`, `github_forks`) are numbers, not strings.
8. **`radar_version`** always present; bumped when the schema changes.

## 5. Idempotency (importer side, not the bot)

- `claude_skill_repos` — upsert by `slug`.
- `claude_skills` — upsert by `url` (needs `UNIQUE (url)`, added by importer migration).
- Skills that vanish from a repo are not auto-deleted (soft model); unpublish via `is_active`.

## 6. Input handed to the bot

The current Category dictionary (`slug → name`) so mapping is stable and the
bot reuses existing shelves. Active categories from the dictionary get
`status:"active"`; anything new is `status:"suggested"` with a `rationale`,
not assigned to skills.

The active dictionary the bot ships with lives in
`trendwatch/import_payload.py` → `SKILL_CATEGORY_NAMES`.
