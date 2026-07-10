# Phase 06 evidence — frozen historical backtest

Status: PASS
Window: 2026-06-10 through 2026-07-10
Report: `reports/v3/backtest.json`

## Frozen corpus

- 4 complaint labels
- 2 repeated-work labels
- 1 identical-evidence replay
- 5 Guardian snapshots
- 5 Scout context events
- raw chats: excluded
- private identifiers: excluded
- source evidence: SHA-256 pointers only

## v2 versus v3

- v2: 92 scheduled walks, 86 empty, 6 surfaced outputs, 3 distinct families, 50% duplicate rate, 0 proactive domain proposals, rollout gate FAIL.
- v3: complaint recall 100%, repeated-work recall 100%, identical-evidence score inflation 0, duplicate visible output rate 0%, 2/2 useful and approvable proposals, 2 proactive domain proposals, rollout gate PASS.

## Separation and safety

- Scout static-health inputs: 0
- Guardian visible proposals: 0
- Reflex Telegram deliveries: 0
- Telegram deliveries during backtest: 0
- canonical memory writes: 0
- privacy scan findings: 0

## Verification

- `python3 scripts/subc_v3_backtest.py --corpus evals/v3 --out reports/v3/backtest.json` — PASS
- `python3 -m unittest tests.test_v3_backtest -v` — 5 tests PASS
- full suite after phase — 42 tests PASS
- corpus and report privacy scans — clean

## Gate result

All quantitative thresholds passed without weakening. Historical v2 fails the same comparison because duplicate rate is 50% and proactive domain proposal count is zero.

RPD review: the corpus stays small and labeled; the runner reuses production lane engines and validators rather than adding a parallel architecture. No live room, cron, Telegram, provider, or canonical memory mutation occurred.
