# Phase 03 evidence — incremental identity-scoped ingestion

Status: PASS

## Acceptance evidence

- P03-C01 PASS — versioned cursor store persists per-source watermarks atomically; restart replay emitted zero new events; legacy cursor migration retained a backup.
- P03-C02 PASS — explicit registry covers Hermes session projections, commitments, project state, cron incidents and read-only memory projections; unknown/unavailable sources, wrong identity, cron prompt, subagent, compaction and transcript origins fail closed.
- P03-C03 PASS — coverage reports scanned/eligible/rejected counts, reason counts, source status and time range.
- P03-C04 PASS — generated events validate against the P02 schema; only safe summaries, source hashes and evidence fingerprints persist; privacy scan is clean.

## Fixture result

- Window: 2026-06-10T09:00:00Z .. 2026-07-01T17:05:00Z
- Scanned: 11
- Eligible: 6
- Rejected: 5
- Reasons: duplicate evidence 1, denied origin 3, wrong identity 1
- Lanes represented: Reflex, Scout, Guardian
- Unavailable source is reported explicitly rather than silently omitted.

## Commands

- `python3 -m unittest tests.test_v3_ingestion -v` — 4/4 passed.
- fixture dry-run context pack — exit 0; no cursor write.
- privacy scan over repository and generated `/tmp` report — clean.
- full suite — 24/24 passed.

## RPD_PHASE_REVIEW

- Focus: security.
- Mutation: replaced non-incremental global last-N behavior with allowlisted projection records, per-source watermarks, owner-identity hash and reject reasons.
- Stress tests: restart replay, duplicate fingerprint, foreign identity, unknown source, unavailable source, compaction, transcript, subagent, and legacy cursor migration.
- Integration: adapters consume projections and never claim source authority; live room and live cursor remain untouched.
- Senior Gate: PASS; deterministic local script and JSON state only.
- Overengineering budget: no SQLite mirror, new index, daemon, queue, service, model call, or generalized connector framework.
- Cleanliness: CLI output is intentional; no raw bodies or private identifiers in tracked artifacts.
