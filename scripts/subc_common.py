#!/usr/bin/env python3
from __future__ import annotations
import json, re, subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_PATTERNS = [
    re.compile(r'(sk-[A-Za-z0-9_\-]{12,})'),
    re.compile(r'(gsk_[A-Za-z0-9_\-]{12,})'),
    re.compile(r'(pplx-[A-Za-z0-9_\-]{12,})'),
    re.compile(r'(gh[pousr]_[A-Za-z0-9_\-]{20,})'),
    re.compile(r'([A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,})'),
    re.compile(r'(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*([^\s]+)'),
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', re.S),
]
FORBIDDEN_COMMAND_RE = re.compile(r'\b(restart|reload|stop|start|enable|disable|install|cp|mv|rm|chmod|chown|tee|write|psql|update|insert|delete|grant|revoke|deploy)\b', re.I)
ALLOWED_PREFIXES = [
    ['systemctl','is-active'],
    ['systemctl','status'],
    ['curl','-fsS'],
    ['python3'],
]

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')

def redact(text: str) -> str:
    out = text or ''
    for pat in SECRET_PATTERNS:
        if pat.pattern.startswith('(?i)(api'):
            out = pat.sub(lambda m: f"{m.group(1)}=<REDACTED>", out)
        else:
            out = pat.sub('<REDACTED>', out)
    return out

def load_json(path: str | Path, default=None):
    p=Path(path)
    if not p.exists(): return default
    return json.loads(p.read_text())

def write_json(path: str | Path, data: Any):
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')

@dataclass
class Observation:
    schema_version: str
    id: str
    source: str
    source_adapter: str
    evidence_uri: str
    observed_at: str
    confidence: float
    redacted: bool
    summary: str
    metadata: dict[str, Any]

    def to_dict(self):
        return asdict(self)

class ReadOnlyCommandRunner:
    def assert_allowed(self, cmd: list[str]):
        if not cmd: raise ValueError('empty command')
        joined = ' '.join(cmd)
        if FORBIDDEN_COMMAND_RE.search(joined):
            raise PermissionError(f'forbidden read-only command: {joined}')
        ok = any(cmd[:len(prefix)] == prefix for prefix in ALLOWED_PREFIXES)
        if not ok:
            raise PermissionError(f'command not allowlisted: {joined}')

    def run(self, cmd: list[str], timeout=10) -> tuple[int,str]:
        self.assert_allowed(cmd)
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return p.returncode, redact((p.stdout or '') + (p.stderr or ''))
