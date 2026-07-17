# AI Radar — Architecture

## Основной поток

```text
Collection
  ↓
Normalize
  ↓
Analysis
  ↓
Validation
  ↓
Moderation
  ↓
Human Review
  ↓
Publication
```

## Оркестрация

`Pipeline` координирует вызовы этапов, но не подменяет их бизнес-логику.

`Scheduler` отвечает только за запуск Pipeline по расписанию.

## Наблюдаемость

`Operations` читает состояние компонентов и рассчитывает общий health. Operations не запускает Pipeline, не публикует и не изменяет данные.

## Правила изоляции

- Collection не анализирует.
- Normalize не собирает источники.
- Analysis не публикует.
- Validation не выполняет ручную модерацию.
- Moderation не является Publication.
- Human Review не запускает внешние интеграции.
- Publication не принимает аналитические решения.
- Scheduler не содержит бизнес-логику.
- Operations работает только на чтение.

## База данных

Изменения схемы выполняются только Alembic-миграциями с `upgrade` и `downgrade`.

## Тестирование

Каждый этап имеет собственные unit-тесты. После изменений должен проходить полный набор pytest.

## Публикационный контур

Phase 10 добавляет отдельный Publication Engine. Phase 12 должна использовать существующий Publication Engine для создания локальных Markdown-выпусков, не создавая параллельный механизм.
