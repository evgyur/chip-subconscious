# Operations runbook

## One-shot local run

```bash
python3 scripts/subc_walk.py --source all --no-publish --limit 25
python3 scripts/subc_score.py
python3 scripts/subc_intents.py --max 3
python3 scripts/subc_publish_pending.py
python3 scripts/subc_validate.py
```

## Scheduled run

Run `scripts/subc_cron_walk.sh` at your preferred cadence, commonly 06:00, 12:00, and 18:00.

## Manual signal injection

Use this when a human or agent review finds a repeated issue from sessions or logs:

```bash
python3 scripts/subc_add_signal.py \
  --id stable-slug \
  --title "Short signal title" \
  --summary "Redacted evidence summary" \
  --evidence-uri "session:<id-or-url>" \
  --source hermes \
  --adapter HermesSessionSearchAdapter \
  --types friction,repeat \
  --score-delta 2.0
```

Then regenerate intents:

```bash
python3 scripts/subc_intents.py --max 3
python3 scripts/subc_publish_pending.py
```

## Approval hygiene

If a demo/test intent was posted:

1. Delete old Telegram message if possible.
2. Remove that intent from `posted_pending_intents.json`.
3. Move the source signal to `cooling` or `archived` so it does not immediately repost.
4. Validate the room.

## Handoff after approval

Approved intents become build packets in `build_packets/`. A separate Main/Coder/QA workflow should pick those up. SUBCONSCIOUS does not build them.
