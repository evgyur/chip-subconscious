# Phase 08 — PASS

Goal: `sg-20260710-subconscious-v3-product-reset`

## Result

Status: **PASS**

The bounded rollout lane was executed by the standard Hermes `/goal` executor. No nested `/goal`, planner, or custom SuperGoal production runner was added.

## Live rollout evidence

- Approval verifier passed against the package `STATE.md` approval event.
- Legacy job `fb2ae09c0d59` is paused, not deleted.
- Exactly one `SUBCONSCIOUS v3 Scout` replacement exists.
- Replacement job `03ca41b81ef0` is enabled on steady schedule `17 6 * * *`.
- Cron delivery is `local`; visible output uses the explicit verified self-send contract, so empty runs cannot auto-deliver a sentinel.
- Canary schedule `every 5m` completed with `last_status=ok`.
- A bounded non-product Telegram canary was sent through the Hermes bot and fetched back exactly; public evidence stores only target/content hashes and the message id.
- The product proposal transport now uses six inline actions (`accept`, `reject`, `skip`, `save`, `mute`, `deep_dive`); the live gateway callback handler was deployed, restarted, and passed its focused 27-test suite.
- Reapplying identical button markup is idempotent; the post-restart repair receipt reports `button_count=6`, `ok=true`, and `unchanged=true` for the existing proposal.
- The next scheduler cycle completed with `status=ok`, Scout `status=empty`, zero SUBCONSCIOUS v3 Telegram deliveries, and zero canonical-memory writes.
- The weekly delivery cap remains `3`; feedback remains candidate-only and cannot write canonical memory.

## Rollback drill

1. Paused the v3 job.
2. Resumed the old job.
3. Verified the old job active and v3 paused.
4. Paused the old job again.
5. Resumed v3 at steady schedule.
6. Verified the final state: old paused, v3 enabled, one replacement only.

No job was deleted and no provider configuration was changed.

## Verification

- Full suite: **65 tests passed**.
- Telegram gateway feedback callbacks: **27 focused tests passed**.
- Repository privacy scan: **clean**.
- Historical backtest gate: **PASS**.
- Live shadow/no-mutation gate: **PASS**.
- Rollout manifest validation: **PASS**.
- Telegram send/fetch-back verifier: **PASS**.
- Cron uniqueness/schedule/delivery verifier: **PASS**.
- Rollback verifier: **PASS**.

## Artifacts

- `reports/v3/rollout-manifest.md`
- `reports/v3/rollout-state.json`
- `reports/v3/rollout-receipt.json`
- `docs/v3/cron-prompt.md`

## Cleanliness override

The new CLI validators intentionally emit one bounded JSON result to stdout and use exit codes for automation. These are operational receipts, not debug prints.
