# Phase 05 evidence — bounded semantic Scout

Status: PASS

## Acceptance evidence

- P05-C01 PASS — each fixture proposal joins two eligible context events; single-event output requires an explicit long-form exception reason.
- P05-C02 PASS — visible proposals validate evidence, expected value, effort, risk, confidence and cheap test against the lane schema.
- P05-C03 PASS — schema and evaluator cap output at three; high-quality empty result returns `empty` with zero deliveries.
- P05-C04 PASS — malformed JSON, timeout, low confidence, privacy-unsafe strings, unknown/Guardian evidence and evidence-ref mismatch fail the whole batch closed.
- P05-C05 PASS — provider is the existing `hermes-approved-route/current-approved`; no API key, base URL, provider definition or live configuration was added.

## Bounded execution contract

- deterministic prefilter bounds redacted Scout events only;
- semantic output is supplied by the standard Hermes executor and validated as structured JSON;
- this repository does not spawn a nested `/goal`, agent daemon or provider client;
- fixture run selected 2 proposals from 4 eligible events; 1 Guardian event was excluded;
- token/time/proposal/confidence budgets are persisted in the run artifact;
- model output cannot write canonical memory or deliver Telegram directly.

## Commands

- `python3 -m unittest tests.test_v3_scout -v` — 7/7 passed.
- Scout fixture dry-run — `selected`, 2 proposals, 0 deliveries.
- repository privacy scan — clean.
- Scout output privacy scan — clean.
- full suite after integration — 37/37 passed.

## RPD_PHASE_REVIEW

- Focus: security.
- Mutation: replaced regex-as-brain with a bounded context prefilter plus structured semantic evaluator contract and independent gates.
- Stress tests: malformed output, timeout, low confidence, private path, over-cap output, unknown evidence, Guardian contamination, forged safe refs, weak single-source reasoning and empty result.
- Integration: consumes P03 event envelopes; rejects P04 Guardian lane; emits P02 Scout proposals only.
- Senior Gate: PASS; fail-closed behavior is deterministic and no provider/config secret changed.
- Overengineering budget: one validator/renderer script plus fixture; Hermes remains the executor and model route owner.
- Cleanliness: CLI print is final run status only; no debug paths or private content in artifacts.
