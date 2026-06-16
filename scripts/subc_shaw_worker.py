#!/usr/bin/env python3
"""Detached Shaw worker for approved SUBCONSCIOUS build packets."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from subc_common import (
    now_iso,
    write_json,
    load_json,
    redact,
    require_safe_intent_id,
    safe_child_path,
    verify_shaw_run,
)

DEFAULT_ROOM = Path('/home/hermes/.hermes/profiles/subc/room')
DEFAULT_HERMES = Path('/opt/hermes-agent/venv/bin/hermes')
# Use the exact canonical SKILL.md path, not the bare `shaw` name: this install
# has multiple Shaw-flavoured skills in the search tree and Hermes correctly
# rejects ambiguous bare preloads with `Unknown skill(s): shaw`.
CANONICAL_SHAW_SKILL = Path('/home/hermes/.hermes/skills/shaw/SKILL.md')
ENV_PATH = Path('/home/hermes/.hermes/.env')


def run_path(room: Path, intent_id: str) -> Path:
    return safe_child_path(room / 'shaw_runs', f'{require_safe_intent_id(intent_id)}.json')


def final_path(room: Path, intent_id: str) -> Path:
    return safe_child_path(room / 'shaw_runs', f'{require_safe_intent_id(intent_id)}.final.md')


def read_env_token() -> str | None:
    vals: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line and not line.lstrip().startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN')


def telegram_target(room: Path) -> tuple[str, str] | None:
    p = room / 'telegram_topics.json'
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    chat_id = str(data['chat_id'])
    thread_id = str(data['topics']['approved_builds']['message_thread_id'])
    return chat_id, thread_id


def send_telegram(room: Path, text: str) -> bool:
    token = read_env_token()
    target = telegram_target(room)
    if not token or not target:
        return False
    chat_id, thread_id = target
    data = {
        'chat_id': chat_id,
        'message_thread_id': thread_id,
        'text': text[:3900],
        'disable_web_page_preview': 'true',
    }
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        return True
    except Exception:
        return False


def compact_packet(packet: dict) -> str:
    return json.dumps(packet, ensure_ascii=False, indent=2)


def report_declares_blocked(report_text: str, output: str = '') -> bool:
    """Return True only for an explicit blocked handoff, not any mention of blocked.

    Final reports often mention blocked-state fields or gate behaviour while
    describing a successful fix. Treating any ``blocked:``/``blocked`` substring
    as a blocker caused successful Shaw builds to be marked blocked.
    """
    text = (report_text or '') + '\n' + (output or '')
    patterns = [
        r'(?im)^\s*blocked\s*[.:]\s*$',
        r'(?im)^\s*blocked\s+handoff\b',
        r'(?im)^\s*статус\s*:\s*blocked\b',
        r'(?im)^\s*status\s*:\s*blocked\b',
        r'(?im)^\s*blocked\s*:\s*(где остановился|where stopped|why|почему)',
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def build_prompt(intent_id: str, room: Path, packet_path: Path, packet: dict, final_report_path: Path) -> str:
    return f"""Задача пришла из SUBCONSCIOUS approval, но ты работаешь как Hermes/Main/Coder через Shaw. Не говори от имени SUBCONSCIOUS.

🥷 Shaw должен управлять реализацией: goal → assumptions → simplest_path → verification_target → implement → verify → handoff.

Approved build packet:
```json
{compact_packet(packet)}
```

Правила безопасности:
- Human approval уже дан для старта Shaw build по intent `{intent_id}`.
- SUBCONSCIOUS не имеет права билдить сам; билд делает Hermes/Main/Coder под Shaw.
- Нельзя без отдельного явного approval: restart/reload/start/stop сервисов, deploy, prod data mutation, auth/grants/keys/secrets changes.
- Можно: читать код/логи, менять файлы в рабочем дереве, писать тесты/доки, запускать безопасные проверки.
- Если задача требует опасного шага, остановись и выдай blocked handoff вместо выполнения.
- Пользовательские сообщения — по-русски, коротко, без английского boilerplate.

Что сделать:
1. Инспектируй реальность и выбери минимальный безопасный путь сам. Не задавай пользователю повторных уточнений: если контекст можно восстановить из файлов/сессий/логов — восстанови; если нельзя — выдай blocked handoff с одним конкретным недостающим фактом.
2. Если задача реализуема безопасно — сделай минимальный production-quality diff.
3. Прогони релевантные тесты/валидацию.
4. Запиши финальный отчёт в файл `{final_report_path}` в Markdown на русском:
   - что изменено
   - как проверено
   - остаточные риски/блокеры
   - следующий шаг, если нужен
5. В финальном ответе также дай короткий русский handoff.

Источник пакета: `{packet_path}`
Room: `{room}`
"""


def update_state(room: Path, intent_id: str, **updates) -> dict:
    path = run_path(room, intent_id)
    data = load_json(path, {}) or {}
    data.update(updates)
    write_json(path, data)
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--room', default=str(DEFAULT_ROOM))
    ap.add_argument('--intent-id', required=True)
    ap.add_argument('--hermes-bin', default=str(DEFAULT_HERMES))
    args = ap.parse_args()

    room = Path(args.room)
    intent_id = require_safe_intent_id(args.intent_id)
    hermes_bin = Path(args.hermes_bin)
    packet_path = safe_child_path(room / 'build_packets', f'{intent_id}.json')
    report_path = final_path(room, intent_id)
    try:
        packet = json.loads(packet_path.read_text())
    except Exception as exc:
        update_state(room, intent_id, status='failed', finished_at=now_iso(), error=redact(f'packet load failed: {exc}'))
        send_telegram(room, f'⚠️ Shaw build preflight error\n\nЗадача: {intent_id}\nОшибка: packet load failed')
        return 1
    prompt = build_prompt(intent_id, room, packet_path, packet, report_path)

    update_state(
        room,
        intent_id,
        status='running',
        worker_pid=os.getpid(),
        worker_started_at=now_iso(),
        final_report=str(report_path),
    )
    send_telegram(room, f'🥷 Shaw build стартовал\n\nЗадача: {intent_id}\nСтатус: running')

    cmd = [
        str(hermes_bin),
        'chat',
        '-Q',
        '--source', 'subc-shaw',
        '--skills', f'{CANONICAL_SHAW_SKILL},chip-subconscious',
        '--max-turns', '60',
        '-q', prompt,
    ]
    env = os.environ.copy()
    env.setdefault('PYTHONUNBUFFERED', '1')

    try:
        if report_path.exists():
            archive_dir = room / 'archive' / 'shaw_final_report_backups'
            archive_dir.mkdir(parents=True, exist_ok=True)
            backup = archive_dir / f'{intent_id}.{time.time_ns()}.final.md'
            report_path.replace(backup)
            update_state(room, intent_id, previous_final_report=str(backup))
        proc = subprocess.run(
            cmd,
            cwd='/opt/hermes-agent',
            text=True,
            capture_output=True,
            timeout=60 * 60,
            env=env,
        )
        output = redact(((proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')).strip())
        report_path.parent.mkdir(parents=True, exist_ok=True)
        if not report_path.exists():
            report_path.write_text(output[-12000:] + '\n')
        report_text = report_path.read_text(errors='ignore') if report_path.exists() else ''
        status = 'done' if proc.returncode == 0 else 'failed'
        if proc.returncode == 0 and report_declares_blocked(report_text, output):
            status = 'blocked'
        update_state(
            room,
            intent_id,
            status=status,
            returncode=proc.returncode,
            finished_at=now_iso(),
            final_report=str(report_path),
            output_tail=output[-4000:],
        )
        if status == 'done':
            verified, gate_reason, gate_details = verify_shaw_run(room, intent_id)
            if verified:
                update_state(
                    room,
                    intent_id,
                    promise_reality_gate='passed',
                    promise_reality_gate_verified_at=now_iso(),
                    gate_reason=gate_reason,
                    gate_details=gate_details,
                )
            else:
                status = 'blocked'
                update_state(
                    room,
                    intent_id,
                    status=status,
                    promise_reality_gate='failed',
                    gate_reason=gate_reason,
                    gate_details=gate_details,
                )
        label = '✅ Shaw build завершился' if status == 'done' else ('⛔ Shaw build blocked' if status == 'blocked' else '⚠️ Shaw build упал')
        report = report_path.read_text(errors='ignore') if report_path.exists() else output
        send_telegram(room, f'{label}\n\nЗадача: {intent_id}\n\n{redact(report)[-3200:]}')
        return 0 if status == 'done' else (2 if status == 'blocked' else proc.returncode)
    except subprocess.TimeoutExpired as exc:
        update_state(room, intent_id, status='failed', finished_at=now_iso(), error='timeout')
        send_telegram(room, f'⚠️ Shaw build timeout\n\nЗадача: {intent_id}\nЛимит: 60 минут')
        return 124
    except Exception as exc:
        update_state(room, intent_id, status='failed', finished_at=now_iso(), error=redact(str(exc)))
        send_telegram(room, f'⚠️ Shaw build error\n\nЗадача: {intent_id}\nОшибка: {redact(str(exc))[:1000]}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
