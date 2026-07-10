# Phase 02 evidence — v3 product contracts

Status: PASS

## Acceptance evidence

- P02-C01 PASS — Reflexes, Subconscious Scout, and Guardian own disjoint event/output types and lifecycles.
- P02-C02 PASS — Scout proposal schema requires a domain, evidence, why-now, expected value, effort, risk, and cheap test.
- P02-C03 PASS — event schema forces service/config/cron health into Guardian; health cannot validate as Scout.
- P02-C04 PASS — raw content is forbidden; classification, redacted source hash and model-egress mode are mandatory; all outputs fix canonical-memory writes to false.

## Artifacts

- `docs/v3/architecture.md`
- `schemas/v3_event.schema.json`
- `schemas/v3_lane_output.schema.json`
- `schemas/v3_feedback.schema.json`
- `tests/test_v3_contracts.py`

## Commands

- `python3 -m unittest discover -s tests -v` — 20/20 passed.
- privacy scan over `docs`, `schemas`, `tests`, and repository — clean.

## RPD_PHASE_REVIEW

- Focus: integration.
- Boundary finding: old score path mixed static health and product insight; mutation split ownership at the schema boundary before runtime work.
- Source authority: projections are evidence, mem0g remains canonical memory, probes remain Guardian, Hermes `/goal` remains executor.
- Stress tests: health-as-Scout, raw-content event, missing privacy class, direct canonical-memory write, and incomplete visible proposal all fail validation.
- Senior Gate: PASS; no extra daemon, queue, database, service, runner, or nested goal.
- Overengineering budget: three schemas and one architecture note are sufficient; rejected a new orchestration layer.
- Cleanliness: schemas validate under JSON Schema 2020-12; no debug residue or raw private evidence.
