# Trendwatch Telegram Bot

## Что это

Webhook handler для интерактивного Telegram-бота. Читает
`digests/recommended.json` напрямую с GitHub
(`raw.githubusercontent.com/<repo>/<branch>/digests/recommended.json`)
и отдаёт пользователю через команды и inline-клавиатуры.

Бот живёт отдельно от cron-пайплайна `trendwatch/` — это Python
serverless-функция на Vercel (`api/telegram.py`). Без базы данных,
60-секундный in-process кэш.

Команды: `/start`, `/list`, `/categories`, `/months` + пагинация и
фильтры через callback-кнопки.

## Deploy шаги

1. На [vercel.com](https://vercel.com) → **New Project** → **Import Git
   Repository** → выбрать этот репо.
2. Framework Preset: **Other**. Root Directory: оставить как есть (корень).
   Build / Output / Install: оставить дефолты.
3. Environment Variables (Settings → Environment Variables):
   - `TELEGRAM_BOT_TOKEN` — твой bot token от @BotFather (обязательно)
   - `TELEGRAM_WEBHOOK_SECRET` — любая строка-секрет (опционально,
     повышает безопасность; Telegram пришлёт её в заголовке
     `X-Telegram-Bot-Api-Secret-Token`)
   - `BOT_REPO` — `Libertad-Harbour-LLC/demo-repository` (опционально,
     это значение по умолчанию)
   - `BOT_BRANCH` — `main` (опционально)
4. **Deploy**. Vercel выдаст URL вида
   `https://trendwatch-claude-skills.vercel.app`.
5. Зарегистрировать webhook одной командой:

   ```bash
   curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<your-vercel-url>/api/telegram&secret_token=<TELEGRAM_WEBHOOK_SECRET>"
   ```

   Если секрет не используешь — опусти `&secret_token=...`.
6. Проверить:

   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
   ```

   Увидишь `url` и `last_error_date` (должно быть пусто или старым).

## Test

Открой бота в Telegram, напиши `/start`. Должно прийти приветствие с
inline-кнопками: «📚 Весь список», «🏷 По категории», «📅 По месяцу».

Доступные команды:

- `/start` — главное меню
- `/list` — все skills (с пагинацией по 5)
- `/categories` — индекс категорий с переходом в подсписок
- `/months` — индекс месяцев первого появления

## Re-deploy

`git push` на `main` → Vercel автоматически ребилдит.

## Снять webhook

Если нужно вернуться на cron-only режим без бота:

```bash
curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
```

## Health check

`GET https://<your-vercel-url>/api/telegram` отвечает
`trendwatch bot is alive` — удобно для проверки, что функция жива.

## Архитектура (кратко)

- `api/telegram.py` — единственный файл функции (Vercel роутит файлы из
  `api/` на `/api/<name>`).
- `requirements.txt` в корне — `requests==2.32.3` (только для бота;
  существующий `trendwatch/requirements.txt` не трогаем).
- `vercel.json` — минимальный конфиг + rewrite `/webhook` →
  `/api/telegram`.
- `.vercelignore` — исключает `trendwatch/`, `digests/`, `.github/` и
  прочее, чтобы деплой был быстрым.
- Кэш `recommended.json` — 60 секунд in-process. Telegram пользователи
  могут жать кнопки часто, но GitHub раз в минуту максимум.
- На любое исключение webhook возвращает 200 (иначе Telegram будет
  ретраить).
