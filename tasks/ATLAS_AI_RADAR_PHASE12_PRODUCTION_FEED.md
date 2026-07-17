# ATLAS AI RADAR — TASK — PHASE 12

## Production News Feed Activation

## Цель

Перевести AI Radar из режима разработки инфраструктуры в рабочий режим чтения новостей.

Система должна:

- получать реальные AI-новости;
- удалять дубликаты;
- обрабатывать материалы существующим Pipeline;
- формировать русскоязычный Markdown-выпуск;
- публиковать его через существующий Publication Engine;
- предоставлять CLI чтения последнего выпуска.

## Git

Рабочая ветка:

`mimo/ai-radar-phase12-production-feed`

Merge не выполнять.

## Источники

Минимальный whitelist:

Международные:

- OpenAI Blog
- Anthropic News
- Google AI Blog
- Hugging Face Blog
- arXiv cs.AI / cs.CL / cs.LG
- Hacker News
- GitHub Trending AI

Русскоязычные:

- Habr AI
- Habr ML
- Habr LLM
- OpenNET
- Tproger AI при наличии стабильного feed

## Source Registry

Создать `config/news_sources.yaml`.

Для каждого источника хранить id, name, url, feed_url, language, source_type, enabled, priority и tags.

## Collection

Сохранять URL, GUID, источник, время публикации, время получения, оригинальный заголовок, краткое описание, язык и уникальный идентификатор.

Ошибка одного источника не должна останавливать остальные.

## Дедупликация

Проверять canonical URL, normalized URL, GUID, нормализованный заголовок и существующий content hash.

## Фильтрация

Оставлять материалы по AI, LLM, ML, агентам, моделям, AI coding, open source, исследованиям, библиотекам, инструментам, safety, agent skills и harnesses.

Исключать рекламу, SEO, дубликаты и нерелевантные статьи.

## Выпуск

Файл:

`output/digests/YYYY-MM-DD_HH-MM_AI_RADAR.md`

Разделы:

- Главное
- Новые модели
- Агентные системы
- Исследования
- Open Source
- Русскоязычные материалы
- Skills и Harnesses

По умолчанию 10–20 лучших материалов. Пустые разделы не выводить.

## CLI

Создать `scripts/latest_digest.py`.

Поддержать:

```bash
python scripts/latest_digest.py
python scripts/latest_digest.py --list
python scripts/latest_digest.py --path
python scripts/latest_digest.py --json
```

## Scheduler

Использовать существующий Scheduler.

Расписание:

- 09:00 Europe/Moscow
- 18:00 Europe/Moscow

Scheduler только запускает Pipeline.

## Тесты

Добавить тесты registry, RSS/Atom, недоступного источника, битого feed, дедупликации, фильтрации, Markdown-выпуска, latest_digest CLI и Scheduler integration.

Сетевые запросы в unit-тестах мокировать. Полный pytest должен проходить.

## Запрещено

Не подключать Telegram, Discord, Email, REST API, Web UI, Prometheus и Grafana. Не использовать CAPTCHA bypass, обход paywall, платные API и destructive SQL.

## Acceptance

- работают минимум 5 источников;
- есть международные и русскоязычные источники;
- дубликаты исключаются;
- выпуск формируется на русском;
- Markdown создаётся;
- последний выпуск доступен через CLI;
- Scheduler запускает в 09:00 и 18:00 по Москве;
- архитектура не нарушена;
- все тесты проходят;
- выполнен один реальный безопасный прогон.

## Итоговый статус разработчика

```text
SUCCESS
Needs Review = true
Verified = false
```
