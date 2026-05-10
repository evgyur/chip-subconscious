---
name: chip-subconscious
description: Read-only sensing layer for Hermes/OpenClaw-style agent workspaces. Use when you want scheduled discovery walks, signal scoring, pending intents, Telegram topic escalation, and human approval buttons before any build work.
created_by: public-template
license: MIT
---

# chip-subconscious

A public, secret-free SUBCONSCIOUS skill for Hermes/OpenClaw-style workspaces.

It watches read-only surfaces, scores repeated signals, creates pending intents, and escalates them to chat topics for human approval. It does **not** build, deploy, restart services, edit configs, rotate keys, or approve itself.

## Trigger this skill when

- You want a separate read-only sensing layer for Hermes/OpenClaw/memory infrastructure.
- You want scheduled “walks” that notice repeated pains, blockers, and reusable opportunities.
- You want pending intents with `✅ Yes` / `❌ No` buttons before implementation starts.
- You need Telegram forum topics or equivalent chat branches for escalation lanes.

## State machine

`observed -> scored -> pending_intent -> pending_approval -> approved -> planned -> building -> qa -> done/rejected/archived`

SUBCONSCIOUS stops at `pending_approval`.

## Required room lanes

- `signal_board` — durable board of current signals.
- `walk_logs` — scheduled read-only walk summaries.
- `pending_intents` — cards awaiting human approval.
- `approved_builds` — approved intent files and build packets.
- `archive` — rejected/cooled/old items.

See [`references/telegram-escalation.md`](references/telegram-escalation.md).

## Quick start

```bash
git clone https://github.com/evgyur/chip-subconscious.git
cd chip-subconscious
python3 scripts/subc_init_room.py \
  --chat-id REPLACE_WITH_TELEGRAM_CHAT_ID \
  --topic-ids 1,2,3,4,5
python3 scripts/subc_walk.py --source all --no-publish
python3 scripts/subc_score.py
python3 scripts/subc_intents.py --max 3
python3 scripts/subc_validate.py
```

Optional Telegram publish requires `TELEGRAM_BOT_TOKEN` in the environment or `~/.hermes/.env` and a configured `telegram_topics.json`.

## Source adapters

- `HermesAdapter` checks Hermes config, skills, sessions, and the SUBCONSCIOUS room.
- `OpenClawAdapter` checks configured OpenClaw/GoClaw service names and skill paths with read-only `systemctl is-active`.
- `Mem0gAdapter` checks a localhost health URL, configured services, and configured evidence paths.
- `ProjectFlowAdapter` finds `STATE.yaml` files under the workspace root.

All adapter settings are environment-configurable. See [`references/openclaw-hermes-sources.md`](references/openclaw-hermes-sources.md).

## Guardrails

Forbidden for SUBCONSCIOUS:

- service restart/reload/start/stop
- deploy
- edit config
- key/grant/actor mutation
- writing production data
- reading/pasting raw secrets
- approval/self-approval
- build start

Allowed:

- read-only discovery
- redacted logs
- scoring
- pending intent creation
- escalation to chat topics

## Commands

```bash
# Initialize room
python3 scripts/subc_init_room.py --chat-id CHAT_ID --topic-ids BOARD,WALKS,INTENTS,BUILDS,ARCHIVE

# Run read-only discovery
python3 scripts/subc_walk.py --source all --no-publish --limit 25

# Score observations and create intents
python3 scripts/subc_score.py
python3 scripts/subc_intents.py --max 3

# Publish pending cards to Telegram topic
python3 scripts/subc_publish_pending.py

# Validate room and run tests
python3 scripts/subc_validate.py
python3 -m unittest discover -s tests -v
```

## References

- [`references/openclaw-hermes-sources.md`](references/openclaw-hermes-sources.md) — how source adapters collect info.
- [`references/telegram-escalation.md`](references/telegram-escalation.md) — chat branches, buttons, escalation flow.
- [`references/security.md`](references/security.md) — public-safe setup and redaction rules.
- [`references/operations.md`](references/operations.md) — scheduled runbook.
