# AI Radar — STATE

Дата актуализации: 2026-07-17

## Назначение

AI Radar — модульный конвейер обработки и публикации новостей об искусственном интеллекте.

## Архитектурный статус

Основные контуры:

- Collection
- Normalize
- Analysis
- Validation
- Moderation
- Human Review
- Publication
- Operations

Оркестрация:

- Pipeline только оркестрирует.
- Scheduler только запускает Pipeline.
- Publication публикует.
- Operations наблюдает.

## Завершённые этапы по представленным отчётам

### Phase 1–8

Реализованы базовые этапы конвейера, включая сбор, обработку, оркестрацию и Scheduler. Детали должны подтверждаться соответствующими отчётами и исходным кодом локальной рабочей копии.

### Phase 10 — Publication Engine

Статус разработчика:

```text
SUCCESS
Needs Review = true
Verified = false
```

Заявлено:

- отдельный `PublicationService`;
- CLI публикации;
- новые publication statuses;
- изоляция Publication от Pipeline и Scheduler;
- полный набор тестов: 135 passed.

### Phase 11 — Operations & Monitoring

Статус разработчика:

```text
SUCCESS
Needs Review = true
Verified = false
```

Заявлено:

- read-only `OperationsService`;
- CLI `scripts/system_status.py`;
- health: healthy / warning / degraded / critical;
- мониторинг Pipeline, Scheduler, Collection, Moderation и Publication;
- полный набор тестов: 147 passed.

## Текущий следующий этап

### Phase 12 — Production News Feed Activation

Цель:

- подключить реальные публичные AI-источники;
- использовать существующий Pipeline;
- удалять дубликаты;
- формировать русскоязычный Markdown-выпуск;
- публиковать его через существующий Publication Engine;
- запускать по расписанию 09:00 и 18:00 Europe/Moscow;
- предоставить CLI чтения последнего выпуска.

## Ограничение достоверности

В этот GitHub-репозиторий пока перенесена только проектная документация. Исходный код локальной реализации не загружен. Статусы фаз основаны на отчётах исполнителя и не должны автоматически трактоваться как независимая верификация.
