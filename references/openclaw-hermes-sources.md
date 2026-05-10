# Collecting Hermes/OpenClaw information

SUBCONSCIOUS collects **signals**, not authority. Every adapter is read-only and writes redacted observations into the room.

## HermesAdapter

Reads local Hermes surfaces:

- `$HERMES_HOME/config.yaml` exists — proves Hermes config is present, but the adapter does not dump secrets.
- `$HERMES_HOME/skills/` exists and counts top-level skills.
- `$HERMES_HOME/sessions/` exists and counts transcript files.
- `$SUBC_ROOM/telegram_topics.json` exists — proves escalation routing is configured.

Typical evidence URIs:

- `file:/home/user/.hermes/config.yaml`
- `file:/home/user/.hermes/skills`
- `file:/home/user/.hermes/sessions`

## OpenClawAdapter

Checks OpenClaw/GoClaw-style runtime and knowledge surfaces:

- `systemctl is-active <service>` for services in `SUBC_OPENCLAW_SERVICES`.
- Existence of related skill directories from `SUBC_OPENCLAW_SKILL_PATHS`.

Default services:

```text
openclaw-gateway,goclaw,goclaw-inbox
```

This is intentionally read-only. It does not call `restart`, `reload`, `status --full`, or commands that can reveal sensitive environment details.

## Mem0gAdapter

Checks a governed memory/control-plane style service:

- Localhost health URL from `SUBC_MEM0G_HEALTH_URL`.
- `systemctl is-active <service>` for `SUBC_MEM0G_SERVICES`.
- Existence of project/evidence paths from `SUBC_MEM0G_PATHS`.

The health URL is restricted to `127.0.0.1` or `localhost` by default to avoid accidental network probing.

## ProjectFlowAdapter

Scans `$HERMES_WORKSPACE/*/STATE.yaml` and records project names plus a small size/sample summary. It does not dump full state into chat.

## Adding your own adapter

1. Add a class in `scripts/subc_adapters.py` extending `BaseAdapter`.
2. Emit observations with `self.obs(...)`.
3. Only call commands through `ReadOnlyCommandRunner`.
4. Add the adapter to `ADAPTERS`.
5. Add tests proving it cannot mutate state.
