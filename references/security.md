# Security and public-safe setup

## Public-safe defaults

This repository contains no private chat IDs, API keys, service credentials, or host IPs. Use placeholders in committed files and configure real values locally via environment variables or room JSON files ignored by git.

## Redaction

`subc_common.redact()` masks common token patterns before observations and cards are written:

- OpenAI-style `sk-...`
- Groq-style `gsk_...`
- Perplexity-style `pplx-...`
- GitHub token-style `ghp_...`, `gho_...`, etc.
- JWT-like strings
- `api_key=...`, `token=...`, `secret=...`, `password=...`
- PEM private keys

Redaction is a guardrail, not a substitute for avoiding secrets in inputs.

## Command allowlist

The command runner only allows narrow read-only prefixes:

- `systemctl is-active ...`
- `systemctl status ...`
- `curl -fsS ...`
- `python3 ...`

It blocks mutation verbs such as `restart`, `reload`, `rm`, `chmod`, `psql`, `grant`, `revoke`, `deploy`, etc.

## Publishing checklist

Before making a fork public:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/subc_validate.py --room /path/to/sanitized/example-room
```

Also scan for private identifiers:

```bash
grep -RInE 'TELEGRAM_BOT_TOKEN|api[_-]?key|secret|password|gh[pousr]_|gsk_|pplx-|BEGIN .*PRIVATE KEY' . --exclude-dir=.git
```

Never commit:

- `.env`
- actual `telegram_topics.json` for private chats
- `posted_pending_intents.json` from a live room
- session transcripts
- raw logs
- build packets containing private paths
