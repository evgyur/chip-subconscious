# Telegram / chat escalation lanes

The pattern works with Telegram forum topics, Discord threads, Slack channels, or any chat system with durable branches. Telegram forum topics are the reference implementation.

## Required lanes

| Lane | Purpose | Human action |
| --- | --- | --- |
| Signal Board | Current read-only signals and trends | Browse, no action required |
| Walk Logs | Scheduled walk digests | Check if something changed |
| Pending Intents | Approval cards | Tap `✅ Yes` or `❌ No` |
| Approved Builds | Approved intents and build packets | Main/Coder can pick up work |
| Archive | Rejected/cooled/old signals | Audit trail |

## Escalation flow

1. Walk creates observations in `walk_logs/`.
2. Score step updates `signals.json` and `summary.json`.
3. Intent step creates files in `pending_intents/` when score and evidence thresholds are met.
4. Publish step posts a card to the Pending Intents topic with buttons.
5. `✅ Yes` moves the intent to `approved_builds/` and creates a build packet.
6. `❌ No` moves the intent to `archive/` and cools/archives the source signal.

## Button callback contract

- `subc:y:<token>` — approve.
- `subc:n:<token>` — reject/archive.
- Token mapping is stored in `posted_pending_intents.json`.
- The same token is used for yes/no on the same intent.

Hermes Telegram callback support requires a small gateway handler. See [`patches/hermes-telegram-subc-callback.patch`](../patches/hermes-telegram-subc-callback.patch) for an example implementation.

## Example topic map

```json
{
  "schema_version": "1.0",
  "chat_id": "REPLACE_WITH_TELEGRAM_CHAT_ID",
  "topics": {
    "signal_board": {"message_thread_id": 101},
    "walk_logs": {"message_thread_id": 102},
    "pending_intents": {"message_thread_id": 103},
    "approved_builds": {"message_thread_id": 104},
    "archive": {"message_thread_id": 105}
  }
}
```

Do not commit real private chat IDs if you are publishing a template.
