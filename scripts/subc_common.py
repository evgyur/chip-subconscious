#!/usr/bin/env python3
from __future__ import annotations
import json, os, re, subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_PATTERNS = [
    re.compile(r'(sk-[A-Za-z0-9_\-]{12,})'),
    re.compile(r'(gsk_[A-Za-z0-9_\-]{12,})'),
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
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(p)

SAFE_INTENT_RE = re.compile(r'^intent_[a-z0-9][a-z0-9_-]{0,120}$')

def require_safe_intent_id(intent_id: str) -> str:
    if not SAFE_INTENT_RE.fullmatch(str(intent_id or '')):
        raise ValueError(f'unsafe intent id: {intent_id!r}')
    return str(intent_id)

def safe_child_path(base: str | Path, filename: str) -> Path:
    base_path = Path(base).resolve()
    path = (base_path / filename).resolve()
    if path.parent != base_path:
        raise ValueError(f'unsafe child path outside {base_path}: {filename!r}')
    return path

def latest_approval_event(room: Path, intent_id: str) -> dict[str, Any] | None:
    events_path = room / 'approval_events.jsonl'
    if not events_path.exists():
        return None
    latest = None
    for line in events_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        if event.get('intent_id') == intent_id:
            latest = event
    return latest


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_existing_final_report(room: Path, intent_id: str, state: dict[str, Any]) -> Path | None:
    runs_dir = (room / 'shaw_runs').resolve()
    raw = state.get('final_report') or str(safe_child_path(runs_dir, f'{intent_id}.final.md'))
    path = Path(str(raw))
    if not path.is_absolute():
        path = runs_dir / path.name
    try:
        resolved = path.resolve()
    except Exception:
        return None
    if resolved.parent != runs_dir:
        return None
    return resolved


def verify_shaw_run(room: Path, intent_id: str, *, now: datetime | None = None) -> tuple[bool, str, dict[str, Any]]:
    """Verify that an approved build has a real completed Shaw run.

    This is the promise/reality gate used before showing an approved signal as
    done/approved-ready: run status must be done, it must finish after approval,
    the final report must exist and contain a verification section, and the build
    packet must carry acceptance criteria.
    """
    intent_id = require_safe_intent_id(intent_id if str(intent_id).startswith('intent_') else f'intent_{intent_id}')
    room = Path(room)
    now = now or datetime.now(timezone.utc)
    state_path = safe_child_path(room / 'shaw_runs', f'{intent_id}.json')
    details: dict[str, Any] = {'intent_id': intent_id, 'shaw_run': str(state_path)}
    if not state_path.exists():
        return False, 'missing_shaw_run', details
    try:
        state = json.loads(state_path.read_text())
    except Exception:
        return False, 'malformed_shaw_run', details
    details['status'] = state.get('status')
    if state.get('status') != 'done':
        return False, f"shaw_run_not_done:{state.get('status') or 'unknown'}", details

    finished_at = parse_iso(state.get('finished_at'))
    if not finished_at:
        return False, 'missing_finished_at', details
    details['finished_at'] = state.get('finished_at')
    if finished_at > now.replace(microsecond=0):
        return False, 'finished_at_in_future', details

    approval = latest_approval_event(room, intent_id)
    if not approval or approval.get('decision') != 'approved':
        return False, 'missing_approved_event', details
    details['approval_event'] = {'timestamp': approval.get('timestamp'), 'approver': approval.get('approver')}
    approval_ts = parse_iso(approval.get('timestamp'))
    if not approval_ts:
        return False, 'missing_approval_timestamp', details
    if finished_at < approval_ts:
        details['approval_timestamp'] = approval.get('timestamp')
        return False, 'shaw_run_older_than_approval', details

    report_path = _safe_existing_final_report(room, intent_id, state)
    if not report_path:
        return False, 'unsafe_final_report_path', details
    details['final_report'] = str(report_path)
    if not report_path.exists():
        return False, 'missing_final_report', details
    started_at = parse_iso(state.get('worker_started_at') or state.get('started_at'))
    if started_at:
        try:
            report_mtime = datetime.fromtimestamp(report_path.stat().st_mtime, timezone.utc).replace(microsecond=0)
            details['final_report_mtime'] = report_mtime.isoformat().replace('+00:00', 'Z')
            if report_mtime < started_at.replace(microsecond=0):
                return False, 'final_report_older_than_run', details
        except Exception:
            return False, 'final_report_mtime_unreadable', details
    report_text = report_path.read_text(errors='ignore').strip()
    if not report_text:
        return False, 'empty_final_report', details
    lower_report = report_text.lower()
    negative_markers = [
        'не проверено',
        'проверки не запускал',
        'не запускал проверки',
        'не удалось проверить',
        'нужно проверить',
        'без проверк',
        'не проверял',
        'не проверяли',
        'без тест',
        'not verified',
        'tests not run',
        'no tests run',
        'verification not run',
        'verification missing',
    ]
    if any(marker in lower_report for marker in negative_markers):
        return False, 'negative_verification_evidence', details
    if 'как проверено' not in lower_report and 'провер' not in lower_report:
        return False, 'missing_verification_evidence', details

    packet_raw = state.get('build_packet') or str(safe_child_path(room / 'build_packets', f'{intent_id}.json'))
    packet_path = Path(str(packet_raw))
    if not packet_path.is_absolute():
        packet_path = room / 'build_packets' / packet_path.name
    if packet_path.resolve().parent != (room / 'build_packets').resolve():
        return False, 'unsafe_build_packet_path', details
    details['build_packet'] = str(packet_path)
    if not packet_path.exists():
        return False, 'missing_build_packet', details
    try:
        packet = json.loads(packet_path.read_text())
    except Exception:
        return False, 'malformed_build_packet', details
    if not packet.get('acceptance_criteria'):
        return False, 'missing_acceptance_criteria', details
    criteria = [str(item).strip().lower() for item in (packet.get('acceptance_criteria') or [])]
    if any(not item or item in {'tbd', 'todo', 'unknown'} or 'tbd' in item for item in criteria):
        return False, 'weak_acceptance_criteria', details
    tests = packet.get('tests') or []
    if tests and any(str(item).strip().lower() in {'tbd', 'todo', 'unknown'} for item in tests):
        return False, 'weak_test_plan', details
    details['acceptance_criteria_count'] = len(packet.get('acceptance_criteria') or [])
    return True, 'verified_shaw_run', details

def patch_yaml_scalar(text: str, key: str, value: str) -> str:
    escaped = str(value).replace('\\','\\\\').replace('"','\\"').replace('\n','\\n')
    line = f'{key}: "{escaped}"'
    pattern = rf'^{re.escape(key)}:\s*.*$'
    if re.search(pattern, text, re.M):
        return re.sub(pattern, line, text, count=1, flags=re.M)
    return text.rstrip() + '\n' + line + '\n'

TRUSTED_SINGLE_EVIDENCE_INTENTS = {
    'openclaw-session-corpus-unreachable',
    'mem0g-health-issue',
}

def intent_eligibility(sig: dict[str, Any]) -> tuple[bool, str]:
    """Return whether a scored signal is eligible for a human approval card.

    Default signals need two independent evidence items before they are shown as
    ready for approval. A tiny allowlist of infrastructure health signals may
    escalate with one evidence item when confidence is already maxed/high: these
    are actionable diagnostics, not mutating builds.
    """
    if sig.get('status') != 'pending_intent':
        return False, 'not_pending_intent'
    evidence_count = len(sig.get('evidence') or [])
    if evidence_count >= 2:
        return True, 'multi_evidence'
    if any((e or {}).get('chip_value_signal') for e in (sig.get('evidence') or [])) and float(sig.get('score') or 0) >= 6.5:
        return True, 'chip_value_signal'
    if (
        sig.get('id') in TRUSTED_SINGLE_EVIDENCE_INTENTS
        and evidence_count >= 1
        and float(sig.get('score') or 0) >= 8
    ):
        return True, 'trusted_single_evidence'
    return False, f'needs_more_evidence:{evidence_count}/2'

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
