# chip-subconscious

Public, secret-free SUBCONSCIOUS skill for Hermes/OpenClaw-style agent workspaces.

It creates a **read-only sensing layer** that periodically walks your agent environment, turns repeated observations into scored signals, and escalates high-confidence ideas as **pending intents** in chat. Humans approve with buttons before any build work starts.

## What it does

- Collects read-only observations from Hermes, OpenClaw/GoClaw, mem0g-like memory services, and project-flow state files.
- Redacts common secrets before writing logs or cards.
- Scores signals with decay and cooldown.
- Creates pending intent YAML files.
- Publishes approval cards to Telegram forum topics with `✅ Yes` / `❌ No` buttons.
- Produces build packets after approval.

## What it never does

- No restarts.
- No deploys.
- No config edits.
- No key rotation or grant mutation.
- No production writes.
- No self-approval.

## Install as a Hermes skill

```bash
hermes skills install https://raw.githubusercontent.com/evgyur/chip-subconscious/main/SKILL.md --name chip-subconscious
```

Or clone directly:

```bash
git clone https://github.com/evgyur/chip-subconscious.git
cd chip-subconscious
```

## Initialize a room

Create five chat topics/branches first:

1. Signal Board
2. Walk Logs
3. Pending Intents
4. Approved Builds
5. Archive

Then initialize local state:

```bash
python3 scripts/subc_init_room.py \
  --chat-id REPLACE_WITH_TELEGRAM_CHAT_ID \
  --topic-ids 101,102,103,104,105
```

This creates `~/.hermes/profiles/subc/room/` by default. Override with `SUBC_ROOM=/path/to/room`.

## Run one walk

```bash
python3 scripts/subc_walk.py --source all --no-publish --limit 25
python3 scripts/subc_score.py
python3 scripts/subc_intents.py --max 3
python3 scripts/subc_publish_pending.py
python3 scripts/subc_validate.py
```

## Schedule

Use Hermes cron or any scheduler:

```bash
SUBC_BASE=$PWD SUBC_ROOM=$HOME/.hermes/profiles/subc/room ./scripts/subc_cron_walk.sh
```

Hermes cron example:

```text
Schedule: 0 6,12,18 * * *
Script: scripts/subc_cron_walk.sh
Deliver: Telegram Walk Logs topic
Skill: chip-subconscious
```

## Configuration

Environment variables:

- `HERMES_HOME` — default `~/.hermes`.
- `HERMES_WORKSPACE` — default `~/workspace`.
- `SUBC_ROOM` — default `$HERMES_HOME/profiles/subc/room`.
- `SUBC_OPENCLAW_SERVICES` — default `openclaw-gateway,goclaw,goclaw-inbox`.
- `SUBC_OPENCLAW_SKILL_PATHS` — comma-separated paths to OpenClaw-related skill directories.
- `SUBC_MEM0G_HEALTH_URL` — default `http://127.0.0.1:8081/health`; localhost only by default.
- `SUBC_MEM0G_SERVICES` — default `mem0g-api,mem0g-inbox-adapter`.
- `SUBC_MEM0G_PATHS` — comma-separated project/evidence paths.
- `TELEGRAM_BOT_TOKEN` — only needed to publish cards.

## Docs

- [Collecting Hermes/OpenClaw info](references/openclaw-hermes-sources.md)
- [Telegram escalation lanes](references/telegram-escalation.md)
- [Security and secret hygiene](references/security.md)
- [Operations runbook](references/operations.md)

## Development

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT
