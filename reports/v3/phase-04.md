# Phase 04 evidence — Reflexes and Guardian separation

Status: PASS

## Acceptance evidence

- P04-C01 PASS — identical evidence fingerprint is a no-op: no score/state gain and no new candidate.
- P04-C02 PASS — fresh matching correction enriches an open instance; the same broad family creates a new evidence-keyed instance after the old one closes.
- P04-C03 PASS — Guardian stores baseline state and emits only transitions; repeated healthy and repeated failed snapshots produce no heartbeat.
- P04-C04 PASS — redacted June/July complaint fixtures recover no-results, repeated-question, prevention-request and no-value classes.

## Fixture result

- Reflexes: 5 correction events -> 4 quiet candidates + 1 enrichment, 0 deliveries.
- Guardian: 5 snapshots -> 1 baseline + 2 changes, 0 healthy heartbeats, 0 deliveries.
- Persistent Guardian replay -> 0 changes.

## Commands

- `python3 -m unittest tests.test_v3_reflexes_guardian -v` — 6/6 passed.
- Guardian dry-run — 2 state-change incidents only.
- Reflex dry-run — 4 candidate records, 0 Telegram delivery.
- privacy scan — clean.
- full suite — 30/30 passed.

## RPD_PHASE_REVIEW

- Focus: integration.
- Mutation: removed correction learning and health telemetry from the proactive scoring path; each now has a small state machine and disjoint output schema.
- Stress tests: repeated evidence, open-instance enrichment, closed-family fresh evidence, repeated health, failure transition, recovery transition, and persistent replay.
- Integration: outputs conform to P02 contracts; Reflexes remain candidate-only, Guardian remains probe-only, Scout receives neither as score inflation.
- Senior Gate: PASS; no cron, room, Telegram, mem0g or production mutation.
- Overengineering budget: two deterministic scripts and fixture state; no event bus, daemon, scheduler or database.
- Cleanliness: explicit `print` is CLI output only; fixture text is redacted regression data.
