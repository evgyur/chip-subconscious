# SUBCONSCIOUS v3 bounded rollout manifest

This manifest authorizes only the reversible v2-to-v3 scheduler swap described below. The private delivery target is represented by an alias plus a live-validated SHA-256, never a raw Telegram identifier.

```json
{
  "schema_version": "subc-v3-rollout-manifest/1",
  "old_job": {
    "id": "fb2ae09c0d59",
    "action": "pause",
    "delete": false,
    "expected_enabled": true
  },
  "replacement": {
    "name": "SUBCONSCIOUS v3 Scout",
    "provider": "minimax",
    "model": "MiniMax-M2.7-highspeed",
    "provider_change": false,
    "canary_schedule": "every 5m",
    "steady_schedule": "17 6 * * *",
    "delivery_target_alias": "subconscious-supervisor-topic",
    "delivery_target_sha256": "sha256:6729fafa762a7e71df500c13e9b9d54b68180a6e276abdd876a32746297329b2",
    "cron_delivery": "local",
    "delivery_mode": "verified_self_send",
    "workdir": "${HOME}/workspace/chip-subconscious-v3",
    "prompt_file": "docs/v3/cron-prompt.md",
    "scripts": [
      "scripts/subc_live_projection.py",
      "scripts/subc_v3_prepare_runtime.py",
      "scripts/subc_reflexes.py",
      "scripts/subc_guardian.py",
      "scripts/subc_scout.py",
      "scripts/subc_delivery_gate.py",
      "scripts/subc_v3_feedback.py",
      "scripts/subc_v3_telegram.py",
      "scripts/subc_verify_rollout_approval.py",
      "scripts/subc_v3_rollout.py",
      "scripts/subc_v3_verify_cron.py",
      "scripts/subc_v3_verify_delivery.py",
      "scripts/subc_final_audit.py"
    ],
    "weekly_proposal_cap": 3
  },
  "activation_steps": [
    "pause_old",
    "create_disabled",
    "enable_canary",
    "test_delivery",
    "readback",
    "second_scheduler_cycle",
    "set_steady_schedule"
  ],
  "rollback_commands": [
    "hermes cron pause ${NEW_JOB_ID}",
    "hermes cron resume fb2ae09c0d59"
  ],
  "recovery_owner": "Chip/Hermes operator lane",
  "approval_scope": "pause-old/activate-new/test-readback/rollback only"
}
```

## Stop conditions

Rollback immediately if the test delivery cannot be fetched back, the first additional scheduler cycle is red, the job emits an empty-run message, the privacy gate blocks, or the rolling-week cap is bypassed.

## Recovery proof

The old job is paused, never deleted. Rollback pauses the new job first, resumes `fb2ae09c0d59`, verifies its next run, and leaves v3 state available for diagnosis without touching canonical memory.
