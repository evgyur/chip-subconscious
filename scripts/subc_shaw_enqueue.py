#!/usr/bin/env python3
"""Queue an approved SUBCONSCIOUS build packet for a Shaw-governed Hermes build.

This script is intentionally tiny and fast so Telegram callback handling can
return immediately. The actual work runs in subc_shaw_worker.py in a detached
process and reports back to the Approved Builds Telegram topic.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from subc_common import now_iso, write_json, load_json, redact, require_safe_intent_id, safe_child_path, latest_approval_event

DEFAULT_ROOM = Path('/home/hermes/.hermes/profiles/subc/room')
DEFAULT_PROJECT = Path('/home/hermes/workspace/chip-subconscious')
DEFAULT_HERMES = Path('/opt/hermes-agent/venv/bin/hermes')


def run_path(room: Path, intent_id: str) -> Path:
    return safe_child_path(room / 'shaw_runs', f'{require_safe_intent_id(intent_id)}.json')


def log_path(room: Path, intent_id: str) -> Path:
    return safe_child_path(room / 'shaw_runs', f'{require_safe_intent_id(intent_id)}.log')


def load_packet(room: Path, intent_id: str) -> tuple[Path, dict]:
    intent_id = require_safe_intent_id(intent_id)
    approved_path = safe_child_path(room / 'approved_builds', f'{intent_id}.yaml')
    if not approved_path.exists():
        raise SystemExit(f'approved intent not found for build enqueue: {approved_path}')
    event = latest_approval_event(room, intent_id)
    if not event or event.get('decision') != 'approved':
        raise SystemExit(f'approved event not found for build enqueue: {intent_id}')
    packet_path = safe_child_path(room / 'build_packets', f'{intent_id}.json')
    if not packet_path.exists():
        raise SystemExit(f'build packet not found: {packet_path}')
    packet = json.loads(packet_path.read_text())
    if packet.get('intent_id') != intent_id:
        raise SystemExit(f'build packet intent mismatch: {packet_path}')
    if str(approved_path) not in [str(x) for x in packet.get('source_evidence', [])]:
        raise SystemExit(f'build packet does not reference approved intent: {approved_path}')
    return packet_path, packet


def worker_command(project: Path, room: Path, intent_id: str, hermes_bin: Path) -> list[str]:
    return [
        sys.executable,
        str(project / 'scripts' / 'subc_shaw_worker.py'),
        '--room', str(room),
        '--intent-id', intent_id,
        '--hermes-bin', str(hermes_bin),
    ]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def _pid_alive_for_intent(pid: object, intent_id: str | None = None) -> bool:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
    except OSError:
        return False
    if not intent_id:
        return True
    cmdline = Path(f'/proc/{pid_int}/cmdline')
    try:
        raw = cmdline.read_bytes().decode('utf-8', errors='ignore').replace('\x00', ' ')
    except Exception:
        return False
    return 'subc_shaw_worker.py' in raw and intent_id in raw


@contextmanager
def enqueue_lock(room: Path, intent_id: str):
    lock_dir = room / '.locks'
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = safe_child_path(lock_dir, f'shaw_enqueue.{require_safe_intent_id(intent_id)}.lock')
    with lock_path.open('w') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def stale_run_reason(state: dict, *, now: datetime | None = None, stale_after_seconds: int = 900) -> str | None:
    """Return a reason when a queued/running Shaw run is not actually alive."""
    status = state.get('status')
    if status not in {'queued', 'running'}:
        return None
    now = now or datetime.now(timezone.utc)
    started = _parse_iso(state.get('worker_started_at') or state.get('started_at') or state.get('queued_at'))
    if started and (now - started).total_seconds() < stale_after_seconds:
        return None

    pid = state.get('worker_pid') or state.get('pid')
    if status == 'running':
        if pid and _pid_alive_for_intent(pid, state.get('intent_id')):
            return None
        return 'running_without_live_worker'
    if not pid:
        return 'queued_without_pid'
    if not _pid_alive_for_intent(pid, state.get('intent_id')):
        return 'queued_without_live_worker'
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--room', default=str(DEFAULT_ROOM))
    ap.add_argument('--project', default=str(DEFAULT_PROJECT))
    ap.add_argument('--intent-id', required=True)
    ap.add_argument('--hermes-bin', default=str(DEFAULT_HERMES))
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    room = Path(args.room)
    project = Path(args.project)
    hermes_bin = Path(args.hermes_bin)
    intent_id = require_safe_intent_id(args.intent_id)
    packet_path, packet = load_packet(room, intent_id)

    runs_dir = room / 'shaw_runs'
    runs_dir.mkdir(parents=True, exist_ok=True)
    state_path = run_path(room, intent_id)
    with enqueue_lock(room, intent_id):
        existing = load_json(state_path, {}) or {}
        if existing.get('status') == 'done' and not args.force:
            print(json.dumps({'ok': True, 'already': True, 'shaw_run': str(state_path), 'status': 'done'}, ensure_ascii=False, indent=2))
            return 0
        if existing.get('status') in {'queued', 'running'} and not args.force:
            stale_reason = stale_run_reason(existing)
            if not stale_reason:
                print(json.dumps({'ok': True, 'already': True, 'shaw_run': str(state_path), 'status': existing.get('status')}, ensure_ascii=False, indent=2))
                return 0
            existing['status'] = 'blocked'
            existing['blocked_reason'] = stale_reason
            existing['blocked_at'] = now_iso()
            write_json(state_path, existing)
        elif existing.get('status') in {'blocked', 'failed'} and not args.force:
            print(json.dumps({'ok': False, 'already': True, 'shaw_run': str(state_path), 'status': existing.get('status'), 'retry_requires_force': True}, ensure_ascii=False, indent=2))
            return 2

        cmd = worker_command(project, room, intent_id, hermes_bin)
        run_state = {
            'schema_version': '1.0',
            'intent_id': intent_id,
            'status': 'queued',
            'queued_at': now_iso(),
            'executor': 'shaw',
            'runner': 'hermes-cli',
            'build_packet': str(packet_path),
            'goal': redact(packet.get('goal', '')),
            'log': str(log_path(room, intent_id)),
            'command': cmd,
        }
        if existing.get('blocked_reason'):
            run_state['retry_of_blocked_reason'] = existing.get('blocked_reason')

        if args.dry_run:
            print(json.dumps({'ok': True, 'dry_run': True, 'shaw_run': str(state_path), 'command': cmd, 'state_written': False}, ensure_ascii=False, indent=2))
            return 0

        write_json(state_path, run_state)
        env = os.environ.copy()
        env.setdefault('PYTHONUNBUFFERED', '1')
        env['SUBC_SHAW_INTENT_ID'] = intent_id
        try:
            with log_path(room, intent_id).open('ab') as log:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(project),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except Exception as exc:
            run_state['status'] = 'failed'
            run_state['error'] = 'popen_failed:' + redact(str(exc))[:500]
            run_state['finished_at'] = now_iso()
            write_json(state_path, run_state)
            raise
        run_state['status'] = 'running'
        run_state['pid'] = proc.pid
        run_state['started_at'] = now_iso()
        write_json(state_path, run_state)
        print(json.dumps({'ok': True, 'shaw_run': str(state_path), 'pid': proc.pid, 'log': str(log_path(room, intent_id))}, ensure_ascii=False, indent=2))
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
