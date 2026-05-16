![Trendwatch](https://github.com/Libertad-Harbour-LLC/demo-repository/actions/workflows/trendwatch.yml/badge.svg)
![Workflows](https://github.com/Libertad-Harbour-LLC/demo-repository/actions/workflows/workflows.yml/badge.svg)

# demo-repository

Контейнер с двумя ежедневными tracking-пайплайнами и интерактивным
Telegram-ботом поверх их результатов.

## Что внутри

### 1. `trendwatch/` — daily Claude Code Skills digest
Cron в 09:00 UTC сканирует GitHub (code + topic search), Reddit и
опционально X/Threads на свежие `.claude/skills/<name>/SKILL.md`,
прогоняет находки через Claude (`claude-sonnet-4-6` + prompt caching),
коммитит `digests/YYYY-MM-DD.md` и отправляет скоринговый дайджест в
Telegram. Постоянная БД с graduation: `top_test` → `recommended.json`
(показывается один раз навсегда), `top_watch` → `watchlist.json`
(всплывает обратно, когда набирает дельту по звёздам/скилам).

### 2. `workflows/` — daily n8n + Make workflow digest
Cron в 12:00 UTC, тот же Telegram-чат, отдельный заголовок
`⚙️ Daily Workflow Radar`. Ищет готовые JSON-воркфлоу для импорта в
n8n / Make, переиспользует примитивы из `trendwatch/`
(`analyzer`, `state`, `skill_db`, `telegram_client`, `index_writer`,
`report`, `normalizer`). Артефакты — в `digests/workflows/`.

### 3. `api/telegram.py` — Vercel-бот
Serverless webhook, читает `recommended.json` + `watchlist.json` обоих
пайплайнов напрямую с `raw.githubusercontent.com`. Команды `/start`,
`/menu`, `/skills`, `/n8n`, `/make`, постоянная reply-клавиатура,
пагинация и детальный экран каждого item с опциональной кнопкой
`🤖 Объясни простыми словами` (single-shot Claude Haiku, гейтится
`ANTHROPIC_API_KEY`). Подробнее в [`bot-README.md`](bot-README.md).

## Запуск локально

```bash
pip install -r trendwatch/requirements.txt

python trendwatch/trendwatch.py --dry-run   # fetch + print, без API
python trendwatch/trendwatch.py             # полный прогон + Telegram
python workflows/workflows.py --dry-run
python workflows/workflows.py
```

Флаги: `--no-analyzer` (fallback на plain-link дайджест),
`--force` (обойти идемпотентность `last_sent_date`).

## Secrets (GitHub Actions)
`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`APIFY_API_TOKEN` (опционально, для X/Threads).

## Дальше читать
- [`CLAUDE.md`](CLAUDE.md) — структура пайплайнов, ключевые файлы, конвенции
- [`CONTEXT.md`](CONTEXT.md) — словарь предметной области бота (Source, Item, View, Screen, Route)
- [`bot-README.md`](bot-README.md) — деплой и эксплуатация Telegram-бота
