# SUBCONSCIOUS v3 architecture contracts

## Product boundary

SUBCONSCIOUS v3 is three small products sharing a redacted event envelope, not one scoring monolith.

- **Reflexes owns** event-driven reactions to explicit corrections and repeated operator work. It emits candidate memory, skill, eval, or workflow artifacts. It never writes canonical memory directly and has no periodic heartbeat.
- **Subconscious Scout owns** bounded cross-source synthesis over incremental, identity-scoped projections. It emits at most three domain proposals per weekly run. A visible proposal must include evidence fingerprints, why now, expected value, effort, risk, and a cheap test.
- **Guardian owns** static health, service, config, SSH, path, cron, and delivery telemetry. Guardian may emit incidents, but static health can never enter Scout scoring or masquerade as proactive insight.

The three output shapes are disjoint in `schemas/v3_lane_output.schema.json`: `reflex_candidate`, `scout_proposal`, and `guardian_incident`.

## Source authority and identity

Every event uses `schemas/v3_event.schema.json` and carries:

- deterministic event identity derived from source class, redacted source reference, evidence fingerprint, and observed state;
- source authority (`operator`, `canonical_state`, `projection`, or `probe`);
- privacy classification and an immutable hash reference;
- one or more evidence fingerprints;
- an explicit lane and event type.

Repeated polling of the same evidence fingerprint does not create new evidence. A proposal instance is keyed by its actual problem fingerprint, not by a broad closed category, so fresh underlying issues cannot be swallowed by a resolved family.

## Proposal lifecycle

Scout lifecycle is `candidate -> surfaced -> feedback -> archived|promotion_request`. Feedback follows `schemas/v3_feedback.schema.json`.

`promote` creates a governed promotion request only. Search and Scout do not promote directly. mem0g remains the canonical memory authority and any later write must use its API, ACL/lifecycle policy, idempotency key, audit reference, and explicit approval path. `writes_canonical_memory` is therefore fixed to `false` in every v3 lane output and feedback record.

## Data minimization

Raw private content is denied in v3 events and evidence artifacts. Projections expose safe summaries, counts, state transitions, hashes, and redacted references only. Missing privacy classification fails closed as red/quarantine at the adapter boundary.

Evidence reports may store IDs, classes, counts, scores, hashes, safe reasons, and pass/fail. They must not store private chat bodies, transcript bodies, credentials, tokens, actor keys, or full memory content.

## Model egress

Model egress is explicit per event:

- `disabled` for deterministic routing and Guardian;
- `local_redacted_only` for fixture and local synthesis;
- `approved_governed_api` only after source classification, redaction, minimum-necessary context packing, and an approved provider boundary.

Red/private raw bodies never leave the source plane. Model failure, malformed output, missing classification, or policy uncertainty yields an empty/blocked Scout result and no visible proposal.

## Operational shape

Standard Hermes `/goal` remains the executor. There is **no production runner**, nested `/goal`, new daemon, queue, orchestrator, database, or control plane in this repository. The minimum implementation is deterministic scripts plus local JSON state owned by the existing room until rollout proves value.

Reflexes and Scout can read governed projections; Guardian reads probes. None owns mem0g, project state, Hermes sessions, or Telegram history. They retain only cursors, hashes, candidate/proposal state, and redacted audit evidence required for replay and feedback.
