# ATLAS LAB REPORT - Telegram Moderation Real Smoke Test

**Date:** 2026-07-18
**Agent:** OpenCode
**Status:** BLOCKED
**Needs Review:** true
**Verified:** false

## CONTEXT_RESTORED

- `STATE.md`, `DECISIONS.md`, `LOG.md`: read.
- Graphify canonical fallback: read; Graphify remains read-only.
- Target repository and service status: inspected through SSH.

## Task

Safely deliver one moderation card, approve it through the dedicated Telegram bot, verify all database records and remove only the created test data.

## Precheck Results

| Check | Result |
|---|---|
| SSH and target branch | Available; `feature/telegram-moderation-publisher-v1` |
| Containers | `ai_radar_app`, `ai_radar_db`, `aroma-bot` are running |
| Worktree | Expected uncommitted moderation files present |
| `TELEGRAM_MODERATION_ENABLED` | `False` |
| Moderation token configured | `False` |
| Moderation chat ID | Default placeholder still active |
| Moderation allowlist | Empty (`0` valid IDs) |
| Generic token | Configured, but intentionally not used |

## Execution

Stopped before backup, migration, test DML, Telegram polling or Telegram sending. No production database row, schema, runtime configuration, service, pipeline, scheduler, Hermes resource or reader-channel post was changed.

## Blocker

The dedicated bot token previously verified in protected local storage has not been configured as `TELEGRAM_MODERATION_BOT_TOKEN` for the AI RADAR runtime. The required target chat and allowlisted Telegram user IDs are also absent. Using the configured generic token would violate the strict two-bot isolation requirement.

## Next Safe Step

Configure, in protected AI RADAR runtime environment only:

```text
TELEGRAM_MODERATION_ENABLED=true
TELEGRAM_MODERATION_BOT_TOKEN=<dedicated bot token>
TELEGRAM_MODERATION_CHAT_ID=<authorized moderation chat>
TELEGRAM_MODERATION_ALLOWED_USER_IDS=<allowlisted operator IDs>
```

Do not print these values. Once all four prechecks pass, rerun this exact smoke-test task from the backup step.

**Status:** BLOCKED
**Needs Review:** true
**Verified:** false
