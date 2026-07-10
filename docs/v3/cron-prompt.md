# SUBCONSCIOUS v3 Scout cron contract

You are the standard Hermes executor for SUBCONSCIOUS v3. This is not a nested `/goal`, planner, autonomous runner, or production mutation engine.

The cron delivery is `local`. Telegram delivery is an explicit verified self-send through the configured Hermes bot target injected into the live job as `SUBC_V3_DELIVERY_TARGET`; the private target never enters this tracked file. Cron stdout is operational evidence only and is never forwarded to Telegram.

## Product boundary

- Reflexes process explicit corrections quietly into candidate state. Never send them to Telegram.
- Guardian reports only state transitions. Never turn static health into an idea.
- Scout may surface a maximum of three validated domain proposals per rolling seven days.
- Empty or blocked runs return exactly `[SILENT]`.
- Never write canonical memory. Feedback creates an auditable candidate or promotion request only.
- Never expose raw chats, private identifiers, file paths, tokens, or source bodies.
- Do not change providers, gateways, cron jobs, or project files during a run.

## Runtime workflow

Set:

```bash
RUNTIME="$HOME/.hermes/profiles/subc/v3"
mkdir -p "$RUNTIME"
test -n "${SUBC_V3_DELIVERY_TARGET:-}" || exit 2
```

1. Prepare identity-scoped redacted projections, Reflex state, and Guardian transitions:

```bash
python3 scripts/subc_v3_prepare_runtime.py --runtime-dir "$RUNTIME" --since-hours 48
```

This command invalidates any previous `model_output.json`. Every cycle must therefore write a fresh evaluator response; stale proposals may never be reused.

2. Read `$RUNTIME/context_pack.json`. Evaluate only events whose lane is `scout`. Ignore one-shot commands, static health, system prompts, compaction, images, unrelated senders, and direct corrections.

3. Write `$RUNTIME/model_output.json` using `subc-v3-scout-evaluation/1`:
   - status `empty` with no proposals when evidence is weak;
   - otherwise at most three proposals;
   - normally join at least two relevant event IDs;
   - one event is allowed only with a specific `single_source_exception` reason;
   - every proposal must contain why now, expected value, effort, risk, confidence, cheap test, and exact evidence references;
   - proposals must address Human20, business, product, personal operations, team operations, travel, finance, health, or another real domain — not internal agent infrastructure.

4. Validate fail-closed:

```bash
python3 scripts/subc_scout.py --fixture "$RUNTIME" --dry-run --output "$RUNTIME/scout-report.json"
```

5. Evaluate the hard rolling-week budget and duplicate suppression **without committing state**:

```bash
python3 scripts/subc_delivery_gate.py \
  --scout-report "$RUNTIME/scout-report.json" \
  --state "$RUNTIME/delivery-state.json" \
  --output "$RUNTIME/delivery-gate.json" \
  --max-per-week 3
```

6. Read `$RUNTIME/delivery-gate.json`.
   - If `silent=true`, return exactly `[SILENT]` and nothing else.
   - If Guardian has a real state transition, keep it separate; never call it a Scout proposal.
   - Otherwise format each allowed proposal into `$RUNTIME/outbound.md`:

```text
🧠 SUBCONSCIOUS v3

➊ <title>
┈ почему сейчас: <why_now>
┈ ценность: <expected_value>
┈ effort / risk / confidence: <values>
┈ дешёвый тест: <cheap_test>
┈ выбери действие кнопкой ниже
```

7. Send only the prepared file through the dedicated Telegram adapter. The adapter verifies the configured bot with `getMe`, sends the proposal, and attaches six inline buttons (`Accept`, `Reject`, `Skip`, `Save`, `Mute`, `Deep dive`) bound to the exact proposal instance ID:

```bash
PROPOSAL_ID="$(python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); print(p["allowed_proposals"][0]["proposal_instance_id"])' "$RUNTIME/delivery-gate.json")"
python3 scripts/subc_v3_telegram.py send \
  --target "$SUBC_V3_DELIVERY_TARGET" \
  --proposal-id "$PROPOSAL_ID" \
  --text-file "$RUNTIME/outbound.md" \
  --expected-bot-username "${SUBC_V3_EXPECTED_BOT_USERNAME:?missing expected bot username}" \
  --output "$RUNTIME/send-result.json"
```

Treat a non-zero exit, malformed JSON, missing positive Telegram message ID, `button_count != 6`, or mismatched outbound content hash as a failed send. Do not commit delivery state on failure. During rollout, the standard `/goal` executor must fetch back the exact message through the canonical read-only telegram-chip runtime before accepting the canary.

8. Only after the structured send succeeds, commit the same delivery decision:

```bash
python3 scripts/subc_delivery_gate.py \
  --scout-report "$RUNTIME/scout-report.json" \
  --state "$RUNTIME/delivery-state.json" \
  --output "$RUNTIME/delivery-gate-committed.json" \
  --max-per-week 3 \
  --commit
```

Verify that the committed allowed proposal fingerprints match the pre-send gate. Then return exactly `[SILENT]`; cron delivery is local, so this operational sentinel is never sent to Telegram.

Do not add a generic run report, source counters, “nothing found”, implementation diary, or internal paths.
