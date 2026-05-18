# Architecture Decision Records

Каждый файл здесь — короткая запись (200-400 слов) про одно архитектурное
решение: что выбрали, почему, какие альтернативы рассмотрели, какие
последствия принимаем.

**Зачем это**: PR-описания на GitHub декаюят, чат-история не индексируется.
ADR — это agent-legible source-of-truth: и человек, и следующий ИИ-агент
смогут открыть один MD-файл и понять `WHY` решения, без реверс-инжиниринга
30 PR'ов.

## Конвенции

- Имена: `NNNN-kebab-case-title.md`, нумерация без пропусков.
- Стиль: 4 секции — `Context`, `Decision`, `Consequences`, `Alternatives Considered`.
- Один файл = одно решение. Не лепить несколько в один.
- Не редактировать после слияния: если решение пересмотрено — новый ADR
  со ссылкой на старый (`Supersedes 0003`).
- Дата — это `first_recommended` для агентов; не критично точно, но не
  оставлять пустым.

## Index

| # | Title | Decision date |
|---|---|---|
| 0001 | [Route as typed sum type](0001-route-as-sum-type.md) | 2026-05-17 |
| 0002 | [Items as deep module](0002-items-deep-module.md) | 2026-05-17 |
| 0003 | [Fail-closed admin gate](0003-fail-closed-admin-gate.md) | 2026-05-17 |
| 0004 | [Push-trigger sentinel for cron pipelines](0004-push-trigger-sentinel.md) | 2026-05-18 |
| 0005 | [stars≥100 bypass in dedup filter](0005-stars-100-dedup-bypass.md) | 2026-05-18 |
| 0006 | [sort=indexed in GitHub code search](0006-sort-indexed-code-search.md) | 2026-05-18 |
| 0007 | [Soft `not_a_skill` rule for verified high-star repos](0007-soft-not-a-skill-rule.md) | 2026-05-18 |
| 0008 | [Telegram-visible error reasons in fallback](0008-telegram-visible-errors.md) | 2026-05-18 |
