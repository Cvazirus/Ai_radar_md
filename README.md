# AI Radar — News Aggregator & Analyzer Bot

AI Radar — это сервис для автоматического сбора, анализа, фильтрации и публикации новостей в сфере ИИ (ИИ-агенты, MCP-серверы, новые LLM, arxiv исследования, GitHub проекты, etc.) с предварительной модерацией через Telegram-бота.

## Стек технологий
- **Python 3.12+**
- **FastAPI / Uvicorn** — веб-сервер и API
- **SQLAlchemy 2 / Alembic** — ORM и миграции базы данных
- **PostgreSQL 16** — реляционная база данных
- **Structlog** — структурированное логирование
- **Pydantic v2** — валидация схем данных
- **Docker / Docker Compose** — контейнеризация

## Структура проекта
```
ai-radar/
├── app/
│   ├── main.py              # Точка входа в FastAPI приложение
│   ├── config.py            # Настройки конфигурации (Pydantic Settings)
│   ├── logging_config.py    # Настройка structlog
│   │
│   ├── collectors/          # Модули сбора данных (RSS, GitHub, arXiv, Hugging Face)
│   ├── pipeline/            # Этапы обработки данных (нормализация, дедупликация, рейтинг)
│   ├── database/            # Модели БД, сессии и репозитории
│   ├── llm/                 # Клиент и промпты для анализа через LLM
│   ├── publishers/          # Модерация и публикация в Telegram
│   ├── scheduler/           # Задачи по расписанию (APScheduler)
│   └── services/            # Бизнес-логика приложения
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── README.md
└── Makefile
```

## Запуск проекта

1. Склонируйте репозиторий и настройте файл переменных окружения:
   ```bash
   cp .env.example .env
   ```

2. Соберите и запустите контейнеры:
   ```bash
   make build
   make up
   ```

3. Проверьте работоспособность приложения (Health Check):
   ```bash
   curl http://localhost:8000/health
   ```
   Ответ должен быть в формате JSON:
   ```json
   {"status": "healthy", ...}
   ```

4. Посмотреть логи приложения:
   ```bash
   make logs
   ```

5. Остановить проект:
   ```bash
   make down
   ```

## Персональная обратная связь Telegram

Обратная связь выключена по умолчанию. Для включения задайте в `.env` только нужные значения:

```dotenv
TELEGRAM_FEEDBACK_ENABLED=true
TELEGRAM_ALLOWED_USER_IDS=123456789
TELEGRAM_FEEDBACK_POLL_TIMEOUT_SECONDS=20
TELEGRAM_FEEDBACK_BATCH_LIMIT=100
TELEGRAM_FEEDBACK_CALLBACK_PREFIX=feedback
```

`TELEGRAM_ALLOWED_USER_IDS` - CSV из числовых Telegram user ID. Пустой список никому не разрешает запись. После миграции запустите long polling отдельным процессом:

```bash
python scripts/run_telegram_feedback.py
python scripts/review_feedback.py --favorites 123456789
python scripts/review_feedback.py --stats
```

Ручная проверка: опубликуйте тестовый материал, убедитесь в четырёх inline-кнопках, затем нажмите `Нравится`, `Неинтересно`, дважды `Избранное` и `Скрыть`. Проверьте, что `like` заменяется на `dislike`, избранное переключается, скрытие не удаляет запись feedback, а повторная доставка одного Telegram update не меняет состояние второй раз.

## Автоматическое решение модерации

По умолчанию выключено (`MODERATION_AUTO_DECISION_ENABLED=false`). При включении в `true`: каждый материал сразу после расчёта правил модерации (`app/pipeline/moderation_rules.py`) автоматически переводится в `approved` (если решение не `blocked`) или `rejected` (если `blocked`) — без ожидания ручного решения в `review_moderation.py`. Одобренные материалы становятся доступны `PublicationService` для публикации так же, как если бы их одобрил человек. Каждое авто-решение пишется отдельной записью в `ModerationDecisionLog` с `actor="system-auto-policy"` — полная история сохраняется, как и при ручном ревью.

## Автоматическая публикация из шедулера

По умолчанию выключено (`SCHEDULER_AUTO_PUBLISH_ENABLED=false`). При включении в `true`: после каждого прохода `PipelineOrchestrator` (fetch → normalize → analysis → validation → moderation → review) `SchedulerService` сам вызывает `PublicationService.publish_batch(limit=SCHEDULER_PUBLISH_LIMIT)` — то есть уже одобренные материалы (вручную или через `MODERATION_AUTO_DECISION_ENABLED`) реально уходят в Telegram-канал без отдельного запуска `scripts/run_publication.py`. В `--dry-run` пайплайна публикация не запускается. Ошибка публикации логируется и не прерывает шедулер — следующий цикл пройдёт как обычно.

---

## Архитектурные решения (Этап 5.1)

### 1. История попыток и `--force`
- **Сохранение истории**: Использование аргумента `--force` (или `--force-reason <reason>`) больше не приводит к удалению старых записей из таблицы `item_analysis`. Вместо этого создается новая запись попытки анализа.
- **Поля отслеживания**: В структуре таблицы добавлены колонки `force_run` (BOOLEAN, по умолчанию `false`) и `force_reason` (TEXT, nullable). Для обычных запусков `force_run = false`, для запусков с параметром `--force` проставляется `force_run = true` и записывается причина перезапуска.
- **Полный Audit Trail**: Все предыдущие статусы (`success`, `failed`, `invalid_response`) сохраняются в истории БД, позволяя отслеживать все попытки анализа по каждому материалу.

### 2. Идемпотентность и уникальные ограничения
- **Отказ от UNIQUE(input_hash)**: Из схемы базы данных удален UNIQUE constraint на поле `input_hash` (или связку уникальности входа), что позволило записывать дублирующиеся хэши при принудительном анализе.
- **Сервисный контроль**: Идемпотентность обычных запусков контролируется на уровне бизнес-логики `AnalysisService`. Если для данного `input_hash` уже существует успешный анализ, повторный вызов LLM пропускается. При включенном `--force` вызов LLM выполняется принудительно и создается новая запись.

### 3. Безопасность миграций
- **Модификация in-place**: Все изменения схемы таблицы `item_analysis` осуществляются через безопасную миграцию Alembic (`a1b2c3d4e5f6`) на месте. Схема обновляется без выполнения разрушающих `DROP TABLE` команд, что гарантирует полную сохранность исторических данных (включая перенос legacy-записи с `item_id = 5`).

### 4. Сетевая изоляция (Docker Bridge & UFW)
- **Отказ от host-mode**: Сервис приложения переведен из небезопасного режима `network_mode: host` в стандартную изолированную bridge-сеть Docker.
- **Extra Hosts & Gateway**: Для обращения к OmniRoute на хост-системе используется `extra_hosts` с сопоставлением `host.docker.internal:host-gateway`. Внутри контейнера URL OmniRoute настраивается как `http://host.docker.internal:20128/v1`.
- **Конфигурация брандмауэра**: Доступ из контейнера разрешен на стороне хоста путем добавления правила UFW для подсети Docker (`ufw allow from 172.16.0.0/12`), что исключает блокировку пакетов при вызовах LLM.
