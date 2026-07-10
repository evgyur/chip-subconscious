# Phase 07 evidence — current local shadow and bounded rollout manifest

Status: PASS

## Shadow execution

- Two independent read-only observation passes completed.
- Live owner messages queried: 40; eligible redacted events after system/compaction/duplicate/one-shot filters: 6.
- Lane result: 5 Reflex corrections, 1 Scout signal.
- Semantic shadow selected one finance-domain proposal with explicit single-source exception and confidence 0.82.
- Candidate review: privacy PASS, novelty PASS, value PASS, duplication PASS.
- Room checksum unchanged.
- Old cron target semantic checksum unchanged.
- Provider config checksum unchanged.
- Telegram deliveries: 0.
- Cron changes: 0.
- State writes: 0.
- Canonical memory writes: 0.
- Backtest gate remained green.

## Product fixes made during shadow

The first live projection exposed the same contamination class that broke v2: continuation prompts, compaction/system text, duplicated gateway echoes, image descriptions, unrelated one-shot commands, and other-user group text. The projector now fails closed on those classes, deduplicates normalized evidence, extracts voice text safely, and only sends recurring/automation/freshness signals to Scout. Explicit reply-context, context-mismatch, immediate-recording, and stale-source complaints route to Reflexes.

## Rollout manifest

- Old job: exact id `fb2ae09c0d59`; action is pause, never delete.
- Replacement: `SUBCONSCIOUS v3 Scout`.
- Canary cadence: every 5 minutes for test and one additional scheduler cycle.
- Steady cadence: `17 6 * * *`.
- Delivery target: private alias plus live-validated SHA-256; raw Telegram identifier excluded from public artifacts.
- Provider/model: unchanged approved MiniMax route.
- Weekly visible proposal cap: 3.
- Rollback: pause new job, resume old job.
- Recovery owner: Chip/Hermes operator lane.

## Verification

- `subc_v3_shadow.py --read-only` — PASS.
- `subc_assert_no_live_mutation.py` — PASS.
- `subc_validate_rollout_manifest.py` — PASS.
- privacy scan — clean.
- full suite — 50 tests PASS.

RPD security review: live reads are identity-scoped, private context stays outside the public checkout, public reports hold only aggregates/hashes, and activation is limited to a reversible scheduler swap plus one test/readback/canary cycle.
