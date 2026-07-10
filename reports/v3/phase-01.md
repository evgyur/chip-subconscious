# Phase 01 evidence — reproducible baseline

Status: PASS
Execution checkout: local clean clone (path withheld from public artifacts)
Public baseline: `4bc52a2e23c46b5dd660eb2a13c3ee0c244d58d4`
Branch: `supergoal/subconscious-v3-reset`
Live source boundary: non-git, read-only inventory source; no bulk import

## Acceptance evidence

- P01-C01 PASS — fresh clone matches the verified public HEAD; live workspace remains non-git and untouched.
- P01-C02 PASS — `subc_privacy_scan.py` passes on the clean checkout and detects synthetic secret, private-id and private-home fixtures.
- P01-C03 PASS — `reports/v3/phase-1-baseline.json` freezes the 2026-06-10..2026-07-10 aggregate audit, public SHA, hashed/redacted cron snapshot, aggregate room schema and source-drift hashes.

## Commands

- `git rev-parse HEAD && git status --short --branch` — exit 0; expected phase files are untracked.
- `python3 scripts/subc_privacy_scan.py --path . --exclude .supergoal --fail-on-private` — `privacy-scan: clean`.
- `python3 -m unittest tests.test_v3_baseline -v` — 3/3 passed.
- `python3 -m unittest discover -s tests -v` — 15/15 passed.

## Source drift

- live-only reviewed paths: 16
- same-path changed files: 20
- identical files: 1
- policy: source drift is evidence, not an instruction to copy. Later phases implement v3 on the public baseline and port only reviewed behavior.

## RPD_PHASE_REVIEW

- Focus: security.
- Pattern: the prior live tree was non-reproducible; mutation applied by using a fresh public clone and hash inventory.
- Assumption: source drift can be bulk-copied — false; checked by public visibility and private-data boundary.
- Stress test: scanner catches synthetic secret, Telegram-style private id and absolute private home path.
- Integration: public repo, live room and Hermes cron remain separate; only aggregate/hash evidence crosses into the checkout.
- Senior Gate: PASS; no production, cron, Telegram or room mutation.
- Overengineering budget: one scanner, one baseline fixture, one report; no new service/store/runner.
- Cleanliness: CLI `print` calls are required command output, not debug residue; no TODO/FIXME or dead imports added.
