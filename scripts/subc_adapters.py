#!/usr/bin/env python3
from __future__ import annotations
import glob, json, os, re, sqlite3, subprocess, textwrap
from pathlib import Path
from subc_common import Observation, ReadOnlyCommandRunner, now_iso, redact, verify_shaw_run

ROOM = Path('/home/hermes/.hermes/profiles/subc/room')
WORKSPACE = Path('/home/hermes/workspace')

class BaseAdapter:
    name='BaseAdapter'; source='manual'
    def __init__(self): self.runner=ReadOnlyCommandRunner()
    def obs(self, id_suffix, evidence_uri, summary, confidence=0.8, **metadata):
        return Observation('1.0', f'{self.name}:{id_suffix}', self.source, self.name, evidence_uri, now_iso(), confidence, True, redact(summary), metadata).to_dict()
    def collect(self, limit=10): return []

class HermesAdapter(BaseAdapter):
    name='HermesAdapter'; source='hermes'
    def collect(self, limit=10):
        out=[]
        cfg=Path('/home/hermes/.hermes/config.yaml')
        if cfg.exists(): out.append(self.obs('config', f'file:{cfg}', 'Hermes config exists for read-only inspection', 0.7, path=str(cfg)))
        skills=Path('/home/hermes/.hermes/skills')
        if skills.exists():
            count=sum(1 for _ in skills.glob('*'))
            out.append(self.obs('skills-dir', f'file:{skills}', f'Hermes skills directory exists with {count} top-level entries', 0.7, count=count))
        topics=ROOM/'telegram_topics.json'
        if topics.exists(): out.append(self.obs('subc-room', f'file:{ROOM}', 'SUBCONSCIOUS room exists with Telegram topic mapping', 0.95, room=str(ROOM)))
        return out[:limit]

CHIP_CORRECTION_RE = re.compile(
    # Keep this intentionally narrow. Generic words like "опять" or "не то"
    # appear in long voice/video transcripts and should not create approval cards
    # unless the phrase is clearly agent-directed.
    r'(?i)(фуфел|не понимаю.{0,80}(почему|где|результат|сделал|сделали|ты|он|вы)|где реальн|где результат|почему (он|ты|вы) не|опять (нет результата|руками)|снова руками|не то (сделал|ответил|написал|прин[её]с)|не пиши так|я же говорил|надо было\s+(сначала\s+)?(спросить|проверить|сделать|показать|не писать|не отправлять|починить|запустить))'
)
STYLE_GUARD_RE = re.compile(r'(?i)(не пиши так|guard|eval|slop|стиль|поправил|поправь)')
PROMISE_GAP_RE = re.compile(r'(?i)(где результат|done без|без проверк|не проверил|claimed done|нет результата)')
SUBC_WALK_RE = re.compile(r'(?i)(subconscious|subc|walk|walks|гуляет|предложени)')
MANUAL_REPEAT_RE = re.compile(r'(?i)(каждый раз|снова руками|опять руками|повторя|автоматизир|сделай команд)')
MODEL_PROVIDER_RE = re.compile(
    r'(?i)(h20[-_ ]?fusion|human20[-_ ]?keys|model provider failed|provider failed|receiving stream response|'
    r'чини (эту )?модель|почему (ты|он|вы) не мог(ли)? отработать.*модел)'
)
RU_PROFANITY_RE = re.compile(r'(?i)\b(еб\w*|ху\w*|хер\w*|пизд\w*|бля\w*)\b')
PRIVATE_FAMILY_RE = re.compile(r'(?i)\b(жена|моя жена|дети|сын|дочь)\b')
LOCAL_PATH_RE = re.compile(r'(?i)(/home/hermes/[^\s\]"\']+|~/.hermes/[^\s\]"\']+)')
INJECTED_REFERENCE_MARKERS = (
    '[CONTEXT COMPACTION',
    'CONTEXT COMPACTION — REFERENCE ONLY',
    'Earlier turns were compacted into the summary below',
)
SLASH_COMMAND_RE = re.compile(r'(?i)(/[-a-z0-9_]+|slash|слэш|команд[ауые]|кнопк[ауи])')
CRON_RE = re.compile(r'(?i)(cron|кажд(ый|ое|ую)\s+(день|утро|вечер|час|недел)|ежеднев|расписан|дайджест)')
WATCHDOG_RE = re.compile(r'(?i)(watchdog|алерт|монитор|проверяй|следи|если .*то|сломал|падает|застрял)')
SKILL_RE = re.compile(r'(?i)(skill|скилл|процедур|runbook|рутин|повторяющ|шаблон|workflow)')


def _compact_text(text: str, limit: int = 260) -> str:
    text = re.sub(r'\s+', ' ', redact(text or '')).strip()
    text = RU_PROFANITY_RE.sub('<мат редактирован>', text)
    text = PRIVATE_FAMILY_RE.sub('<семейный контекст редактирован>', text)
    text = LOCAL_PATH_RE.sub('<локальный путь скрыт>', text)
    return text[:limit]


def _is_injected_reference_blob(content: str) -> bool:
    return any(marker in (content or '') for marker in INJECTED_REFERENCE_MARKERS)


def _is_long_media_transcript(content: str) -> bool:
    """Skip stored media transcript wrappers unless they are short direct messages.

    Session DB stores voice/video transcript payloads as user-role messages. Long
    webinar/trading transcripts contain generic phrases such as "надо было" that
    look like corrections but are not agent feedback.
    """
    stripped = (content or '').lstrip()
    return (
        len(stripped) > 2000
        and stripped.startswith(('[The user sent a voice message', '[The user sent an audio', '[The user sent a video'))
    )

def _manual_repeat_candidate(content: str) -> dict[str, str]:
    """Classify a repeated manual action into the safest automation shape.

    This does not execute automation. It only carries a redacted candidate into
    the approval/build packet so the human sees whether the likely artifact is a
    slash command, cron, watchdog, or reusable skill.
    """
    compact = _compact_text(content, 180)
    checks = [
        ('slash_command', SLASH_COMMAND_RE, 'сделать явную slash-команду или кнопку для ручного запуска'),
        ('cron', CRON_RE, 'сделать расписание/cron только после отдельного approval на live schedule'),
        ('watchdog', WATCHDOG_RE, 'сделать read-only watchdog с тихим режимом и алертом только при проблеме'),
        ('reusable_skill', SKILL_RE, 'сохранить процедуру как reusable skill/runbook с проверками'),
    ]
    for candidate_type, pattern, suggested in checks:
        if pattern.search(content):
            return {
                'type': candidate_type,
                'suggested_artifact': suggested,
                'trigger_phrase': compact,
            }
    return {
        'type': 'reusable_skill',
        'suggested_artifact': 'начать с reusable skill; cron/watchdog/slash-команду делать только если повторяемость подтвердится',
        'trigger_phrase': compact,
    }


class HermesSessionAdapter(BaseAdapter):
    """Read-only Chip-value pattern miner over Hermes local session DB.

    This is deliberately not a broad transcript dumper. It only emits redacted,
    compact evidence when Chip's own messages indicate repeated correction,
    lost value, missing verification, or automation opportunity.
    """
    name='HermesSessionAdapter'; source='hermes-sessions'

    def __init__(self):
        super().__init__()
        self.db_path = Path(os.environ.get('SUBC_HERMES_STATE_DB', '/home/hermes/.hermes/state.db'))

    def _rows(self, limit: int):
        if not self.db_path.exists():
            return []
        con = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        try:
            return con.execute(
                """
                SELECT m.id AS message_id, m.session_id, m.role, m.content, m.timestamp,
                       s.source, s.title
                FROM messages m
                LEFT JOIN sessions s ON s.id = m.session_id
                WHERE m.role IN ('user','assistant')
                  AND m.content IS NOT NULL
                  AND length(m.content) > 0
                ORDER BY m.timestamp DESC
                LIMIT ?
                """,
                (max(20, min(int(limit) * 12, 400)),),
            ).fetchall()
        finally:
            con.close()

    def _emit(self, proposal_id: str, title: str, pattern_type: str, row, summary: str, action: str, risk: str, score_delta: float, **extra_metadata):
        msg_id = row['message_id']
        session_id = row['session_id']
        return self.obs(
            proposal_id,
            f'session:{session_id}#msg:{msg_id}',
            summary,
            0.9,
            pattern_type=pattern_type,
            proposal_id=proposal_id,
            title=title,
            proposed_action=action,
            risk=risk,
            score_delta=score_delta,
            chip_value_signal=True,
            session_id=session_id,
            message_id=msg_id,
            **extra_metadata,
        )

    def collect(self, limit=10):
        out=[]
        seen=set()
        for row in self._rows(limit):
            content = row['content'] or ''
            if '[IMPORTANT:' in content:
                content = content.split('[IMPORTANT:', 1)[0]
            stripped = content.lstrip()
            # Only Chip/user correction messages are useful here. Skip injected
            # system/skill blobs and reply-only source quotes that are stored as
            # user-role messages by the gateway but are not Chip speaking.
            if (
                row['role'] != 'user'
                or stripped.startswith('[System note:')
                or _is_injected_reference_blob(stripped)
                or _is_long_media_transcript(stripped)
                or (stripped.startswith('[Replying to:') and '[Evgeny "Chip"]' not in stripped)
                or not CHIP_CORRECTION_RE.search(content)
            ):
                continue
            compact = _compact_text(content)
            if SUBC_WALK_RE.search(content):
                key='subconscious-useful-walks-v2'
                if key not in seen:
                    out.append(self._emit(
                        key,
                        'SUBCONSCIOUS walks должны давать реальные предложения',
                        'recurring_correction',
                        row,
                        f'Chip correction pattern: SUBCONSCIOUS walks не дают реальных предложений — {compact}',
                        'Добавить HermesSessionAdapter, semantic OpenClaw mining, OpportunityScorer и digest с 1–3 проверяемыми улучшениями вместо infra counters.',
                        'иначе SUBCONSCIOUS останется healthcheck-ом и будет тратить внимание Chip без пользы',
                        8.5,
                    )); seen.add(key)
            if PROMISE_GAP_RE.search(content):
                key='promise-reality-gate'
                if key not in seen:
                    out.append(self._emit(
                        key,
                        'Проверять done/результат перед отчётом',
                        'promise_gap',
                        row,
                        f'Chip correction pattern: done/результат без проверки — {compact}',
                        'Добавить promise→reality gate: любое “done/fixed” из Shaw/Subconscious должно иметь свежий тест, артефакт или final report.',
                        'агенты будут продолжать закрывать задачи словами без проверенного результата',
                        7.5,
                    )); seen.add(key)
            if STYLE_GUARD_RE.search(content):
                key='chip-correction-to-guard-eval'
                if key not in seen:
                    out.append(self._emit(
                        key,
                        'Превращать правки Chip в guard/eval/skill patch',
                        'style_guard',
                        row,
                        f'Chip correction pattern: style/guard correction — {compact}',
                        'Если Chip явно поправил стиль/формат/поведение, создавать candidate guard/eval или skill patch, а не терять правку в чате.',
                        'одни и те же правки будут повторяться вручную в новых сессиях',
                        7.0,
                    )); seen.add(key)
            if MANUAL_REPEAT_RE.search(content):
                key='manual-repeat-automation-opportunity'
                if key not in seen:
                    automation_candidate = _manual_repeat_candidate(content)
                    out.append(self._emit(
                        key,
                        'Автоматизировать повторяющиеся ручные операции',
                        'manual_repeat',
                        row,
                        f'Chip correction pattern: manual repeat / automation opportunity — {compact}',
                        f'Собрать повторяющуюся ручную операцию в automation candidate: {automation_candidate["type"]}. {automation_candidate["suggested_artifact"]}.',
                        'Chip продолжит платить вниманием за то, что агент должен был автоматизировать',
                        6.8,
                        automation_candidate=automation_candidate,
                    )); seen.add(key)
            if len(out) >= limit:
                break
        return out


CORRECTION_BUCKETS = [
    (
        'model_provider_routing_skill',
        MODEL_PROVIDER_RE,
        'skill',
        'Усилить skill/runbook для Hermes model/provider routing: проверять активный profile home, provider/env key, streaming flags и smoke `hermes chat` перед отчётом о фиксе модели.',
    ),
    (
        'promise_reality_guard',
        PROMISE_GAP_RE,
        'guard',
        'Добавить или усилить guard: отчёт done/fixed допускается только со свежей проверкой, артефактом или final report.',
    ),
    (
        'style_slop_eval',
        STYLE_GUARD_RE,
        'eval',
        'Добавить eval/skill patch на повторяющуюся стилевую правку Chip, чтобы будущие ответы не возвращались к тому же slop-паттерну.',
    ),
    (
        'manual_repeat_skill',
        MANUAL_REPEAT_RE,
        'skill',
        'Собрать повторяющуюся ручную операцию в reusable skill, slash command, cron или watchdog-кандидат.',
    ),
    (
        'subconscious_walk_quality',
        SUBC_WALK_RE,
        'guard',
        'Усилить digest/walk guard: выводить только проверяемые предложения с evidence, action и risk, а не vanity counters.',
    ),
]


def _classify_correction(content: str) -> tuple[str, str, str]:
    for bucket, pattern, patch_type, action in CORRECTION_BUCKETS:
        if pattern.search(content):
            return bucket, patch_type, action
    return 'general_correction', 'skill', 'Создать candidate guard/eval/skill patch из повторяющейся правки Chip и привязать его к redacted evidence.'


BUCKET_EVIDENCE_SUMMARIES = {
    'model_provider_routing_skill': 'Правка про model/provider routing failure; нужен skill/runbook с profile/env/streaming/smoke проверками.',
    'promise_reality_guard': 'Правка про преждевременный done/result без свежей проверки.',
    'style_slop_eval': 'Правка про стиль/формат ответа или анти-slop guard.',
    'manual_repeat_skill': 'Правка про повторяющуюся ручную операцию, которую нужно вынести в reusable workflow.',
    'subconscious_walk_quality': 'Правка про качество SUBCONSCIOUS walk/digest: нужны проверяемые предложения, а не счётчики.',
    'general_correction': 'Общая правка поведения агента; сырой текст скрыт, используйте session pointer.',
}


def _redacted_evidence_summary(bucket: str) -> str:
    return BUCKET_EVIDENCE_SUMMARIES.get(bucket, BUCKET_EVIDENCE_SUMMARIES['general_correction'])


def _candidate_patch(primary_item: dict, evidence_items: list[dict]) -> dict:
    patch_type = primary_item['patch_type']
    bucket = primary_item.get('bucket', '')
    titles = {
        'guard': 'Candidate guard from Chip correction',
        'eval': 'Candidate eval from Chip correction',
        'skill': 'Candidate skill patch from Chip correction',
    }
    targets = {
        'model_provider_routing_skill': 'project/human20-keys references/h20-fusion-hermes-profile-routing.md',
    }
    return {
        'schema_version': '1.0',
        'status': 'candidate',
        'patch_type': patch_type,
        'title': titles.get(patch_type, 'Candidate correction patch'),
        'target': targets.get(bucket, 'TBD by Shaw/Hermes after approval'),
        'action': primary_item['action'],
        'source': 'chip-explicit-correction',
        'evidence_items': evidence_items,
        'privacy': 'redacted_session_pointers_only',
    }


class CorrectionMiningAdapter(HermesSessionAdapter):
    """Aggregate clean Chip corrections into one guard/eval/skill proposal."""
    name='CorrectionMiningAdapter'; source='correction-mining'

    def collect(self, limit=10):
        corrections=[]
        max_corrections=max(2, min(int(limit or 10), 5))
        for row in self._rows(max(limit, 20)):
            content=row['content'] or ''
            if '[IMPORTANT:' in content:
                content=content.split('[IMPORTANT:', 1)[0]
            stripped=content.lstrip()
            if (
                row['role'] != 'user'
                or stripped.startswith('[System note:')
                or _is_injected_reference_blob(stripped)
                or _is_long_media_transcript(stripped)
                or (stripped.startswith('[Replying to:') and '[Evgeny "Chip"]' not in stripped)
                or not CHIP_CORRECTION_RE.search(content)
            ):
                continue
            bucket, patch_type, action = _classify_correction(content)
            corrections.append({
                'row': row,
                'bucket': bucket,
                'patch_type': patch_type,
                'action': action,
                'summary': _compact_text(content),
                'evidence_uri': f'session:{row["session_id"]}#msg:{row["message_id"]}',
            })
            if len(corrections) >= max_corrections:
                break
        if not corrections:
            return []

        counts={}
        for item in corrections:
            counts[item['bucket']]=counts.get(item['bucket'], 0)+1
        priority={name: idx for idx, (name, *_rest) in enumerate(CORRECTION_BUCKETS)}
        primary=max(counts, key=lambda key: (counts[key], -priority.get(key, 999)))
        primary_item=next(item for item in corrections if item['bucket'] == primary)
        grouped=', '.join(f'{bucket}:{count}' for bucket, count in sorted(counts.items()))
        evidence_items=[
            {
                'evidence_uri': item['evidence_uri'],
                'bucket': item['bucket'],
                'summary': _redacted_evidence_summary(item['bucket']),
            }
            for item in corrections
        ]
        row=primary_item['row']
        candidate_patch = _candidate_patch(primary_item, evidence_items)
        return [self.obs(
            'chip-correction-mining-loop',
            f'session:{row["session_id"]}#msg:{row["message_id"]}',
            f'Chip correction mining grouped {len(corrections)} clean recent correction(s): {grouped}. Proposed patch type: {primary_item["patch_type"]}. Evidence stays redacted via session pointers.',
            0.92,
            pattern_type='correction_mining',
            proposal_id='chip-correction-mining-loop',
            title='Превращать повторяющиеся правки Chip в guards/evals/skills',
            proposed_action=primary_item['action'],
            risk='без correction mining Chip будет снова руками повторять одни и те же правки агенту',
            score_delta=8.0,
            chip_value_signal=True,
            correction_count=len(corrections),
            correction_buckets=counts,
            primary_bucket=primary,
            suggested_patch_type=primary_item['patch_type'],
            candidate_patch=candidate_patch,
            evidence_items=evidence_items,
        )]

class OpenClawAdapter(BaseAdapter):
    name='OpenClawAdapter'; source='openclaw'
    def collect(self, limit=10):
        out=[]
        for svc in ['openclaw-gateway','goclaw','goclaw-inbox']:
            code, txt = self.runner.run(['systemctl','is-active',svc], timeout=5)
            out.append(self.obs(f'service-{svc}', f'service:{svc}', f'{svc} active check: {txt.strip() or "unknown"}', 0.6, exit_code=code))
        for p in ['/home/hermes/.hermes/skills/chip-claw-core','/home/hermes/.hermes/skills/chip-gigabrain','/home/hermes/.hermes/skills/chip-mem0g']:
            pp=Path(p)
            if pp.exists(): out.append(self.obs(f'path-{pp.name}', f'file:{pp}', f'OpenClaw-related skill path exists: {pp.name}', 0.75, path=str(pp)))
        return out[:limit]

OPENCLAW_SESSION_TARGETS = [
    {
        # 2026-06-03: Chip OpenClaw moved from intel64 to HEL1.  Keep this as a
        # single corpus target: the former chipdev lane now exists under
        # /home/chip/.openclaw/agents/chipdev on HEL1, not as /home/chipdev/.openclaw.
        'label': 'chip-hel1',
        'ssh': 'chip@157.180.97.244',
        'base': '/home/chip/.openclaw',
        'agents': [
            'chipdm', 'chiptg', 'chiptask', 'chipdev', 'chipcoder', 'chipcdx',
            'main', 'opscron', 'project-flow', 'project-storm', 'postcraft', 'shaw',
        ],
    },
]

ISSUE_RE = re.compile(
    r'(?i)\b(error|failed|failure|traceback|exception|permission denied|timed out|timeout|no[_ -]?reply|no response|http 4\d\d|http 5\d\d|conflict|not found|panic|refused|unauthorized|forbidden)\b'
)
SCHEMA_NOISE_RE = re.compile(r'(?i)("parameters"|"properties"|"items"|"type"\s*:\s*"object"|trajectory-depth-limit|pollOption|sourceMappingURL)')

def classify_ssh_failure(error: str, target: dict | None = None) -> dict:
    """Return a compact, operator-safe classification for SSH scan failures.

    The OpenClaw session scanner is intentionally read-only. When SSH fails we
    should not dump the whole ssh diagnostic into Telegram/room summaries: it is
    noisy, can contain local file paths, and hides whether the safe next step is
    host-key verification, auth repair, or path-permission review.
    """
    raw = redact(str(error or '').strip())
    target = target or {}
    host = str(target.get('ssh') or 'unknown-target')
    base = str(target.get('base') or '')
    fingerprint_match = re.search(r'(SHA256:[A-Za-z0-9+/=_-]+)', raw)
    fingerprint = fingerprint_match.group(1) if fingerprint_match else None

    if 'REMOTE HOST IDENTIFICATION HAS CHANGED' in raw or 'Host key verification failed' in raw:
        summary = f'SSH host key mismatch for {host}; read-only scan blocked before auth'
        if fingerprint:
            summary += f' (presented {fingerprint})'
        return {
            'failure_kind': 'ssh_host_key_mismatch',
            'summary': summary,
            'safe_next_step': 'verify the host fingerprint out-of-band, then update known_hosts only with explicit approval',
            'fingerprint': fingerprint,
        }
    if re.search(r'(?i)permission denied \(publickey\)', raw):
        return {
            'failure_kind': 'ssh_auth_failed',
            'summary': f'SSH auth failed for {host}; corpus path {base or "unknown"} was not reached',
            'safe_next_step': 'verify that the existing read-only key/account is available; do not create or change keys without explicit approval',
            'fingerprint': fingerprint,
        }
    if re.search(r'(?i)(connection timed out|operation timed out|connecttimeout|no route to host|connection refused)', raw):
        return {
            'failure_kind': 'ssh_network_unreachable',
            'summary': f'SSH network/connectivity failure for {host}; corpus path {base or "unknown"} was not reached',
            'safe_next_step': 'check network/host reachability read-only before changing services or credentials',
            'fingerprint': fingerprint,
        }
    if re.search(r'(?i)(no such file|not a directory)', raw):
        return {
            'failure_kind': 'path_missing',
            'summary': f'OpenClaw corpus path missing for {host}: {base or "unknown"}',
            'safe_next_step': 'confirm the current OpenClaw corpus path/topology before updating source targets',
            'fingerprint': fingerprint,
        }
    return {
        'failure_kind': 'ssh_or_scan_failed',
        'summary': f'OpenClaw session scan failed for {host}: {raw[:220] or "unknown error"}',
        'safe_next_step': 'inspect the redacted scanner error and choose auth/path/network remediation',
        'fingerprint': fingerprint,
    }

REMOTE_OPENCLAW_SESSION_SCAN = r'''
import json, os, pathlib, re, sys, time

ISSUE_RE = re.compile(r'(?i)\b(error|failed|failure|traceback|exception|permission denied|timed out|timeout|no[_ -]?reply|no response|http 4\d\d|http 5\d\d|conflict|not found|panic|refused|unauthorized|forbidden)\b')
SECRET_RE = re.compile(r'(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*([^\s,;]+)|sk-[A-Za-z0-9_\-]{12,}|gsk_[A-Za-z0-9_\-]{12,}|\b\d{6,}:[A-Za-z0-9_\-]{20,}\b')
SCHEMA_NOISE_RE = re.compile(r'(?i)("parameters"|"properties"|"items"|"type"\s*:\s*"object"|trajectory-depth-limit|pollOption|sourceMappingURL)')

def redact_local(text):
    return SECRET_RE.sub(lambda m: (m.group(1) + '=<REDACTED>') if m.group(1) else '<REDACTED>', str(text or ''))

def safe_read_tail(path, max_bytes=24000):
    try:
        size = path.stat().st_size
        with path.open('rb') as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            return f.read(max_bytes).decode('utf-8', 'replace')
    except Exception:
        return ''

def issue_summary(text, max_snippets=3):
    def normalized_line(raw):
        raw = str(raw or '').strip()
        if not raw:
            return None
        if raw.startswith('{'):
            try:
                obj = json.loads(raw)
            except Exception:
                obj = None
            if isinstance(obj, dict):
                event_type = obj.get('type') or obj.get('event') or obj.get('source') or 'json-event'
                status = obj.get('status') or obj.get('state')
                if str(status).lower() in {'failed', 'error'}:
                    return f'{event_type} status={status}'
                interesting = []
                def walk(value, depth=0):
                    if depth > 4 or len(interesting) >= 3:
                        return
                    if isinstance(value, dict):
                        for k, v in value.items():
                            lk = str(k).lower()
                            if lk in {'error', 'stderr', 'stdout', 'output', 'message', 'content', 'summary'} and isinstance(v, str) and ISSUE_RE.search(v):
                                interesting.append(v)
                            else:
                                walk(v, depth + 1)
                    elif isinstance(value, list):
                        for item in value[-10:]:
                            walk(item, depth + 1)
                walk(obj)
                if interesting:
                    return f'{event_type}: ' + ' | '.join(redact_local(x.strip())[:180] for x in interesting[:2])
                return None
            if len(raw) > 500:
                return None
        if SCHEMA_NOISE_RE.search(raw) and not re.search(r'(?i)(traceback|exception|permission denied|timed out|http 4\d\d|http 5\d\d|refused|unauthorized|forbidden)', raw):
            return None
        return redact_local(raw)[:260]

    snippets = []
    counts = {}
    for raw in str(text or '').splitlines():
        if not ISSUE_RE.search(raw):
            continue
        line = normalized_line(raw)
        if not line:
            continue
        key = ISSUE_RE.search(raw).group(1).lower()
        counts[key] = counts.get(key, 0) + 1
        if line and line not in snippets and len(snippets) < max_snippets:
            snippets.append(line)
    return {'count': sum(counts.values()), 'terms': counts, 'snippets': snippets}

def load_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return None

def interesting_text_from_json(data):
    parts = []
    def walk(obj, depth=0):
        if depth > 5 or len(parts) > 80:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                lk = str(k).lower()
                if lk in {'content', 'text', 'message', 'summary', 'error', 'stderr', 'stdout', 'preview'} and isinstance(v, str):
                    parts.append(v)
                else:
                    walk(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj[-20:]:
                walk(item, depth + 1)
        elif isinstance(obj, str) and ISSUE_RE.search(obj):
            parts.append(obj)
    walk(data)
    return '\n'.join(parts)

def session_file_candidates(meta, root):
    out = []
    if isinstance(meta, dict):
        for key in ('sessionFile', 'runtimeFile'):
            value = meta.get(key)
            if isinstance(value, str) and value.startswith('/home/'):
                out.append(pathlib.Path(value))
    if root.exists():
        out.extend(sorted(root.glob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[:2])
    return out[:3]

base = pathlib.Path(sys.argv[1])
agents = [a for a in sys.argv[2].split(',') if a]
limit = int(sys.argv[3])
now = time.time()
result = {'ok': True, 'base': str(base), 'agents': [], 'scanned_at': int(now)}

for agent in agents:
    root = base / 'agents' / agent / 'sessions'
    item = {'agent': agent, 'root': str(root), 'exists': root.exists(), 'files_seen': 0, 'recent_sessions': [], 'issue_count': 0}
    if not root.exists():
        result['agents'].append(item)
        continue
    files = []
    for pattern in ('*.codex-app-server.json', '*.trajectory-path.json', '*.jsonl', '*.json'):
        files.extend(p for p in root.glob(pattern) if p.is_file() and p.name != 'sessions.json.telegram-sent-messages.json')
    files = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)[:max(2, limit)]
    item['files_seen'] = len(files)
    index = root / 'sessions.json'
    if index.exists():
        data = load_json(index)
        if isinstance(data, dict):
            item['index_sessions'] = len(data)
            item['index_mtime'] = int(index.stat().st_mtime)
    for path in files[:limit]:
        meta = load_json(path)
        text = safe_read_tail(path)
        if meta is not None:
            text += '\n' + interesting_text_from_json(meta)
        for candidate in session_file_candidates(meta, root):
            try:
                if candidate.exists() and candidate.is_file():
                    text += '\n' + safe_read_tail(candidate)
            except Exception:
                pass
        issues = issue_summary(text)
        item['issue_count'] += issues['count']
        age_hours = round((now - path.stat().st_mtime) / 3600, 2)
        rec = {
            'file': path.name,
            'age_hours': age_hours,
            'mtime': int(path.stat().st_mtime),
            'issue_count': issues['count'],
            'issue_terms': issues['terms'],
            'snippets': issues['snippets'],
        }
        if isinstance(meta, dict):
            rec['model'] = meta.get('model') or meta.get('modelProvider') or ''
            rec['cwd'] = meta.get('cwd') or ''
            rec['thread_id'] = meta.get('threadId') or meta.get('sessionId') or ''
        item['recent_sessions'].append(rec)
    result['agents'].append(item)

print(json.dumps(result, ensure_ascii=False))
'''

def summarize_session_text(text: str) -> dict:
    snippets=[]; counts={}
    for raw in str(text or '').splitlines():
        match=ISSUE_RE.search(raw)
        if not match: continue
        if SCHEMA_NOISE_RE.search(raw) and not re.search(r'(?i)(traceback|exception|permission denied|timed out|http 4\d\d|http 5\d\d|refused|unauthorized|forbidden)', raw):
            continue
        if raw.strip().startswith('{') and len(raw.strip()) > 500:
            continue
        term=match.group(1).lower()
        counts[term]=counts.get(term,0)+1
        line=redact(raw.strip())[:260]
        if line and line not in snippets and len(snippets) < 3:
            snippets.append(line)
    return {'count': sum(counts.values()), 'terms': counts, 'snippets': snippets}

NO_REPLY_RE = re.compile(r'(?i)\b(no[_ -]?reply|no response|empty response|нет ответа|без ответа)\b')
HANDOFF_RE = re.compile(r'(?i)\b(handoff|handover|delegate|delegat|subagent|worker|enqueue|queued|callback|taskflow|project flow)\b')
NOISE_RE = re.compile(
    r'(?i)(## Decisions|## Open TODOs|## Constraints|Exact identifiers|Turn Context|'
    r'"parameters"|"properties"|sourceMappingURL|quality criteria|acceptance criteria|'
    r'grep -v|find /home|low priority|низкий приоритет|isError[\\": ]+false|'
    r'<available_skills>|available_skills|skill file|tokens profile|profile is set|OpenClaw Default)'
)
FRESH_FAILURE_HOURS = 96


def _issue_terms(rec: dict) -> dict:
    return {str(k).lower(): int(v) for k, v in (rec.get('issue_terms') or {}).items()}


def _record_noise_score(rec: dict) -> int:
    snippets = '\n'.join(str(s or '') for s in (rec.get('snippets') or []))
    score = 0
    if rec.get('file') == 'sessions.json':
        score += 2
    if NOISE_RE.search(snippets):
        score += 2
    if rec.get('age_hours') is not None and float(rec.get('age_hours') or 0) > 24 * 14:
        score += 1
    return score


def _classify_issue_record(rec: dict) -> str:
    """Classify a session issue record into an operator-actionable group.

    This keeps the semantic adapter from treating every literal word `failed` or
    `timeout` in prompts, summaries, or old sessions as the same live handoff
    failure. The categories are intentionally coarse; they are used for read-only
    prioritization, not for automated remediation.
    """
    terms = _issue_terms(rec)
    snippets = '\n'.join(str(s or '') for s in (rec.get('snippets') or []))
    low = snippets.lower()
    strong_terms = ('permission denied', 'forbidden', 'unauthorized', 'timeout', 'timed out', 'no_reply', 'no response', 'not found', 'refused', 'conflict', 'traceback', 'exception', 'panic')
    has_http = any(term.startswith('http 4') or term.startswith('http 5') for term in terms)
    if _record_noise_score(rec) >= 3:
        return 'scanner_noise_or_stale_history'
    if NOISE_RE.search(snippets) and not has_http and not any(term in terms for term in strong_terms):
        return 'scanner_noise_or_stale_history'
    if any(term in terms for term in ('permission denied', 'forbidden', 'unauthorized')):
        return 'access_permission_failure'
    if any(term in terms for term in ('timeout', 'timed out', 'no_reply', 'no response')) or NO_REPLY_RE.search(snippets):
        if HANDOFF_RE.search(snippets) or 'timeout' in low or 'timed out' in low or NO_REPLY_RE.search(snippets):
            return 'timeout_no_reply_handoff'
    if has_http or any(term in terms for term in ('not found', 'refused', 'conflict')):
        return 'integration_endpoint_failure'
    if any(term in terms for term in ('traceback', 'exception', 'panic')):
        return 'runtime_exception'
    if any(term in terms for term in ('failed', 'failure', 'error')):
        runtime_error_hint = re.search(r'(?i)(isError[\\": ]+true|traceback|exception|command failed|failed to|exit code|returned non-zero|status=failed|panic)', snippets)
        if not runtime_error_hint:
            return 'scanner_noise_or_stale_history'
        return 'generic_failed_error'
    return 'unclassified_issue'


def _semantic_failure_groups(payload: dict) -> list[dict]:
    groups: dict[str, dict] = {}
    for agent in payload.get('agents') or []:
        agent_name = agent.get('agent') or 'unknown'
        for rec in agent.get('recent_sessions') or []:
            count = int(rec.get('issue_count') or 0)
            if count <= 0:
                continue
            category = _classify_issue_record(rec)
            group = groups.setdefault(category, {
                'id': category,
                'count': 0,
                'fresh_count': 0,
                'agents': {},
                'samples': [],
                'noise_records': 0,
            })
            group['count'] += count
            group['agents'][agent_name] = group['agents'].get(agent_name, 0) + count
            age = float(rec.get('age_hours') or 999999)
            if age <= FRESH_FAILURE_HOURS:
                group['fresh_count'] += count
            if category == 'scanner_noise_or_stale_history':
                group['noise_records'] += 1
            if len(group['samples']) < 3:
                group['samples'].append({
                    'agent': agent_name,
                    'file': rec.get('file'),
                    'age_hours': rec.get('age_hours'),
                    'issue_count': count,
                    'issue_terms': _issue_terms(rec),
                    'snippets': (rec.get('snippets') or [])[:2],
                })
    out = []
    for group in groups.values():
        group['agent_count'] = len(group['agents'])
        group['agents'] = dict(sorted(group['agents'].items(), key=lambda item: (-item[1], item[0])))
        if group['id'] == 'scanner_noise_or_stale_history':
            group['evidence_quality'] = 'blocked_by_noise'
        elif group['fresh_count'] > 0:
            group['evidence_quality'] = 'fresh_read_only_evidence'
        else:
            group['evidence_quality'] = 'stale_or_low_context'
        out.append(group)
    return sorted(out, key=lambda g: (g['id'] == 'scanner_noise_or_stale_history', -g['fresh_count'], -g['agent_count'], -g['count'], g['id']))


def _select_root_cause(groups: list[dict]) -> dict:
    actionable = [g for g in groups if g.get('id') != 'scanner_noise_or_stale_history' and g.get('fresh_count', 0) > 0]
    if actionable:
        group = actionable[0]
        if group['id'] == 'timeout_no_reply_handoff':
            title = 'Повторяющиеся timeout/no_reply handoff-сбои'
            hypothesis = 'несколько OpenClaw lanes показывают свежие timeout/no_reply признаки в handoff/session файлах; сначала нужен read-only разбор конкретного handoff пути, а не рестарт сервисов'
        elif group['id'] == 'access_permission_failure':
            title = 'Повторяющиеся access/permission сбои'
            hypothesis = 'свежие session-файлы указывают на отказ доступа; чинить ключи/гранты нельзя без отдельного approval, поэтому нужен read-only аудит владельца пути и текущих прав'
        else:
            title = f'Повторяющийся кластер: {group["id"]}'
            hypothesis = 'свежие session-файлы дают повторяющийся кластер; нужен узкий read-only triage до любых runtime изменений'
        return {
            'id': group['id'],
            'title': title,
            'hypothesis': hypothesis,
            'selected_group': group,
            'verified_fix_plan': [
                'Сохранить raw scan payload в reports/*.raw.json без секретов и без Telegram-публикации.',
                'Для 2–3 свежих samples открыть только соответствующие session-файлы read-only и отделить реальные handoff failures от prompt/schema mentions.',
                'Если root cause подтверждён, создать отдельный Shaw task на точечный фикс; рестарт/деплой/ключи — только после отдельного approval.',
            ],
        }
    noisy = next((g for g in groups if g.get('id') == 'scanner_noise_or_stale_history'), None)
    if noisy:
        return {
            'id': 'semantic_scanner_false_positive_noise',
            'title': 'Semantic scanner считает prompt/history noise как failures',
            'hypothesis': 'текущий root cause в наблюдении — не доказанный runtime outage, а шумный issue_hits: sessions.json, старые trajectory-файлы и текст инструкций содержат слова error/failed/timeout',
            'selected_group': noisy,
            'verified_fix_plan': [
                'Сначала усилить scanner: не выбирать sessions.json/prompt/history snippets как primary evidence для handoff failures.',
                'Повторно прогнать read-only semantic walk и требовать fresh samples <= 96h перед approval-card.',
                'Только после чистого fresh cluster заводить отдельный безопасный fix task на runtime/root cause.',
            ],
        }
    return {
        'id': 'no_repeated_root_cause_verified',
        'title': 'Повторяющийся root cause не подтверждён',
        'hypothesis': 'read-only scan не нашёл достаточно свежих повторяющихся evidence across agents',
        'selected_group': None,
        'verified_fix_plan': [
            'Оставить сигнал в watching.',
            'Повторить read-only scan на следующем walk.',
        ],
    }

class OpenClawSessionAdapter(BaseAdapter):
    name='OpenClawSessionAdapter'; source='openclaw-sessions'

    def _scan_target(self, target, limit):
        cmd = [
            'ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'StrictHostKeyChecking=yes',
            target['ssh'], 'python3', '-',
            target['base'], ','.join(target['agents']), str(max(1, min(limit, 8))),
        ]
        try:
            proc = subprocess.run(cmd, input=REMOTE_OPENCLAW_SESSION_SCAN, text=True, capture_output=True, timeout=25)
        except Exception as exc:
            return {'ok': False, 'error': redact(str(exc)), 'failure': classify_ssh_failure(str(exc), target)}
        if proc.returncode != 0:
            err = redact((proc.stderr or proc.stdout or '').strip()[:1000])
            return {'ok': False, 'error': err, 'failure': classify_ssh_failure(err, target), 'exit_code': proc.returncode}
        try:
            return json.loads(proc.stdout)
        except Exception as exc:
            return {'ok': False, 'error': f'invalid scanner json: {redact(str(exc))}', 'raw': redact(proc.stdout[:1000])}

    def collect(self, limit=10):
        out=[]
        per_target_limit=max(2, min(limit, 6))
        for target in OPENCLAW_SESSION_TARGETS:
            payload=self._scan_target(target, per_target_limit)
            label=target['label']
            if not payload.get('ok'):
                failure = payload.get('failure') or classify_ssh_failure(payload.get('error', 'unknown error'), target)
                out.append(self.obs(f'{label}-unreachable', f'ssh:{target["ssh"]}:{target["base"]}', f'OpenClaw session corpus unreachable for {label}: {failure["summary"]}', 0.9, target=label, target_status='unreachable', error_summary=failure.get('summary'), failure_kind=failure.get('failure_kind'), safe_next_step=failure.get('safe_next_step'), fingerprint=failure.get('fingerprint'), exit_code=payload.get('exit_code')))
                continue
            agents=payload.get('agents', [])
            total_index=sum(int(a.get('index_sessions') or 0) for a in agents)
            total_files=sum(int(a.get('files_seen') or 0) for a in agents)
            total_issues=sum(int(a.get('issue_count') or 0) for a in agents)
            out.append(self.obs(f'{label}-coverage', f'ssh:{target["ssh"]}:{target["base"]}', f'OpenClaw session corpus reachable for {label}: agents={len(agents)}, indexed_sessions={total_index}, recent_files={total_files}, issue_hits={total_issues}', 0.95, target=label, target_status='reachable', agents=len(agents), indexed_sessions=total_index, recent_files=total_files, issue_count=total_issues))
            for agent in agents:
                if not agent.get('exists'):
                    out.append(self.obs(f'{label}-{agent.get("agent")}-missing', f'ssh:{target["ssh"]}:{agent.get("root")}', f'OpenClaw agent session root missing on {label}: {agent.get("agent")}', 0.55, target=label, agent=agent.get('agent'), target_status='missing'))
                    continue
                issue_count=int(agent.get('issue_count') or 0)
                recent=agent.get('recent_sessions') or []
                snippets=[]
                terms={}
                for rec in recent:
                    for key,value in (rec.get('issue_terms') or {}).items():
                        terms[key]=terms.get(key,0)+int(value)
                    for snippet in rec.get('snippets') or []:
                        if snippet not in snippets and len(snippets) < 3:
                            snippets.append(snippet)
                if issue_count:
                    detail='; '.join(snippets) if snippets else 'issue terms observed in recent session files'
                    out.append(self.obs(f'{label}-{agent.get("agent")}-issues', f'ssh:{target["ssh"]}:{agent.get("root")}', f'OpenClaw recent sessions show issue patterns on {label}/{agent.get("agent")}: hits={issue_count}; {detail}', 0.9, target=label, agent=agent.get('agent'), issue_count=issue_count, issue_terms=terms, recent_files=len(recent), snippets=snippets))
                else:
                    out.append(self.obs(f'{label}-{agent.get("agent")}-baseline', f'ssh:{target["ssh"]}:{agent.get("root")}', f'OpenClaw recent session baseline for {label}/{agent.get("agent")}: files_seen={agent.get("files_seen", 0)}, indexed_sessions={agent.get("index_sessions", 0)}, issue_hits=0', 0.7, target=label, agent=agent.get('agent'), issue_count=0, recent_files=len(recent), indexed_sessions=agent.get('index_sessions', 0)))
        return out[:limit]


class OpenClawSemanticAdapter(OpenClawSessionAdapter):
    """Semantic layer over OpenClaw sessions: one proposal per repeated failure class."""
    name='OpenClawSemanticAdapter'; source='openclaw-semantic'

    def collect(self, limit=10):
        affected=[]; snippets=[]; terms={}; total_issues=0; failure_groups=[]
        for target in OPENCLAW_SESSION_TARGETS:
            payload=self._scan_target(target, max(2, min(limit, 8)))
            if not payload.get('ok'):
                continue
            groups = _semantic_failure_groups(payload)
            failure_groups.extend(groups)
            for agent in payload.get('agents') or []:
                issue_count=int(agent.get('issue_count') or 0)
                if not issue_count:
                    continue
                total_issues += issue_count
                affected.append(agent.get('agent'))
                for rec in agent.get('recent_sessions') or []:
                    for key, value in (rec.get('issue_terms') or {}).items():
                        terms[key]=terms.get(key, 0)+int(value)
                    if _classify_issue_record(rec) == 'scanner_noise_or_stale_history':
                        continue
                    for snippet in rec.get('snippets') or []:
                        if snippet not in snippets and len(snippets) < 4:
                            snippets.append(snippet)
        # Merge groups from multiple targets by id. Today there is one target,
        # but keeping this merge avoids double cards if another read-only corpus
        # is added later.
        merged={}
        for group in failure_groups:
            gid = group['id']
            if gid not in merged:
                merged[gid] = {**group, 'agents': dict(group.get('agents') or {}), 'samples': list(group.get('samples') or [])[:3]}
                continue
            cur=merged[gid]
            cur['count'] += group.get('count', 0)
            cur['fresh_count'] += group.get('fresh_count', 0)
            cur['noise_records'] += group.get('noise_records', 0)
            for agent, count in (group.get('agents') or {}).items():
                cur['agents'][agent] = cur['agents'].get(agent, 0) + count
            cur['samples'] = (cur.get('samples') or [])[:3]
            for sample in group.get('samples') or []:
                if len(cur['samples']) < 3:
                    cur['samples'].append(sample)
        failure_groups=list(merged.values())
        for group in failure_groups:
            group['agent_count']=len(group.get('agents') or {})
        failure_groups=sorted(failure_groups, key=lambda g: (g['id'] == 'scanner_noise_or_stale_history', -g.get('fresh_count', 0), -g.get('agent_count', 0), -g.get('count', 0), g['id']))
        root_cause=_select_root_cause(failure_groups)
        if total_issues < 2 or (not failure_groups and len(set(affected)) < 2):
            return []
        cluster=root_cause['id']
        detail=f'issue_terms={terms}'
        agents=[]
        for agent in affected:
            if agent and agent not in agents:
                agents.append(agent)
        summary = (
            f'OpenClaw handoff/session failures grouped: selected_root_cause={root_cause["id"]}; '
            f'agents={", ".join(agents)}; hits={total_issues}; {detail}'
        )
        return [self.obs(
            'openclaw-semantic-session-failures',
            'openclaw-semantic:recent-sessions',
            summary,
            0.91,
            pattern_type='openclaw_semantic_cluster',
            proposal_id='openclaw-semantic-session-failures',
            title='Сгруппировать повторяющиеся OpenClaw handoff/session failures',
            proposed_action='Сгруппировать NO_REPLY/timeout/failed handoffs по агентам, выбрать один повторяющийся root cause и оформить маленький read-only verified fix plan.',
            risk='без semantic clustering SUBCONSCIOUS будет показывать счётчики issue_hits, но не предложит, какой повторяющийся сбой чинить первым',
            score_delta=8.2,
            chip_value_signal=True,
            cluster=cluster,
            issue_terms=terms,
            issue_count=total_issues,
            affected_agents=agents,
            failure_groups=failure_groups[:5],
            selected_root_cause=root_cause,
            verified_fix_plan=root_cause.get('verified_fix_plan') or [],
            snippets=snippets[:3],
        )]


def _yaml_scalar_simple(text: str, key: str) -> str:
    m = re.search(rf'^{re.escape(key)}:\s*(.*)$', text or '', re.M)
    if not m:
        return ''
    value=m.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value=value[1:-1].replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
    return value


class PromiseRealityAdapter(BaseAdapter):
    """Detect approved/claimed builds that lack a verified Shaw run outcome."""
    name='PromiseRealityAdapter'; source='promise-reality'

    def __init__(self):
        super().__init__()
        self.room=Path(os.environ.get('SUBC_ROOM', str(ROOM)))

    def _verified_intents(self) -> set[str]:
        out=set()
        runs=self.room/'shaw_runs'
        if not runs.exists():
            return out
        for path in runs.glob('*.json'):
            iid=path.stem
            ok, _reason, details = verify_shaw_run(self.room, iid)
            if ok:
                verified_id = details.get('intent_id') or iid
                out.add(str(verified_id).replace('intent_', '', 1))
                out.add(str(verified_id))
        return out

    def collect(self, limit=10):
        approved=self.room/'approved_builds'
        if not approved.exists():
            return []
        verified=self._verified_intents()
        stale=[]
        for path in sorted(approved.glob('*.yaml')):
            text=path.read_text(errors='replace')
            status=_yaml_scalar_simple(text, 'status')
            if status != 'approved':
                continue
            iid=_yaml_scalar_simple(text, 'id') or path.stem
            if iid in verified or iid.replace('intent_', '', 1) in verified:
                continue
            stale.append((iid, _yaml_scalar_simple(text, 'title') or iid, path))
            if len(stale) >= limit:
                break
        if not stale:
            return []
        iid, title, path=stale[0]
        return [self.obs(
            'promise-reality-gate',
            f'file:{path}',
            f'Promise/reality gap: approved build has no verified Shaw run — {title}',
            0.9,
            pattern_type='promise_reality_gap',
            proposal_id='promise-reality-gate',
            title='Проверять approved/done через verified Shaw run',
            proposed_action='Перед отчётом “done/approved build готов” проверять, что есть свежий shaw_run со status=done, final report и acceptance checks; иначе держать задачу в blocked_ready.',
            risk='без promise/reality gate агенты будут выглядеть занятыми, но Chip не получит проверенный результат',
            score_delta=8.0,
            chip_value_signal=True,
            missing_verified_count=len(stale),
        )]

class Mem0gAdapter(BaseAdapter):
    name='Mem0gAdapter'; source='mem0g'
    def collect(self, limit=10):
        out=[]
        code, txt = self.runner.run(['curl','-fsS','http://127.0.0.1:8081/health'], timeout=5)
        out.append(self.obs('health', 'http://127.0.0.1:8081/health', f'mem0g health check: {txt.strip() or "no response"}', 0.95 if code==0 else 0.5, exit_code=code))
        code, txt = self.runner.run(['curl','-fsS','http://127.0.0.1:8081/ready'], timeout=5)
        out.append(self.obs('ready', 'http://127.0.0.1:8081/ready', f'mem0g ready check: {txt.strip() or "no response"}', 0.95 if code==0 else 0.5, exit_code=code))
        code, txt = self.runner.run(['curl','-fsS','http://127.0.0.1:18792/health'], timeout=5)
        out.append(self.obs('goclaw-inbox-health', 'http://127.0.0.1:18792/health', f'GoClaw Inbox health check: {txt.strip() or "no response"}', 0.9 if code==0 else 0.55, exit_code=code))
        for svc in ['mem0g-api','goclaw-inbox-media-worker.timer']:
            code, txt = self.runner.run(['systemctl','is-active',svc], timeout=5)
            out.append(self.obs(f'service-{svc}', f'service:{svc}', f'{svc} active check: {txt.strip() or "unknown"}', 0.85, exit_code=code))

        # HEL1 is now the canonical memory-stack host. After the 2026-05-25
        # migration, the source plane is served by the GoClaw Inbox container;
        # the old mem0g-inbox-adapter unit may be disabled and should not, by
        # itself, create a mem0g-health-issue approval card.
        code, txt = self.runner.run(['systemctl','is-active','mem0g-inbox-adapter'], timeout=5)
        legacy_state = (txt.strip() or 'unknown')
        if code == 0:
            summary = f'legacy mem0g-inbox-adapter active check: {legacy_state}'
        else:
            summary = 'legacy mem0g-inbox-adapter not part of HEL1 canonical health; current source plane is covered by GoClaw Inbox probe'
        out.append(self.obs('legacy-service-mem0g-inbox-adapter', 'service:mem0g-inbox-adapter.service', summary, 0.65, exit_code=code, legacy_state=legacy_state))

        for p in ['/home/hermes/workspace/chip-mem0g','/home/hermes/workspace/mem0g-recovery/STATE.yaml','/home/hermes/workspace/mem0g-recovery/evidence']:
            pp=Path(p)
            if pp.exists(): out.append(self.obs(f'path-{pp.name}', f'file:{pp}', f'mem0g discovery path exists: {pp}', 0.8, path=str(pp)))
        return out[:limit]

class ProjectFlowAdapter(BaseAdapter):
    name='ProjectFlowAdapter'; source='project-flow'
    def collect(self, limit=10):
        out=[]
        for path in glob.glob('/home/hermes/workspace/*/STATE.yaml')[:limit]:
            text=Path(path).read_text(errors='ignore')[:2000]
            project=Path(path).parent.name
            summary=f'project-flow state found for {project}; size={len(text)} bytes sample'
            out.append(self.obs(f'state-{project}', f'file:{path}', summary, 0.8, project=project, path=path))
        return out[:limit]

ADAPTERS = {
    'hermes': HermesAdapter,
    'hermes-sessions': HermesSessionAdapter,
    'correction-mining': CorrectionMiningAdapter,
    'openclaw': OpenClawAdapter,
    'openclaw-sessions': OpenClawSessionAdapter,
    'openclaw-semantic': OpenClawSemanticAdapter,
    'promise-reality': PromiseRealityAdapter,
    'mem0g': Mem0gAdapter,
    'project-flow': ProjectFlowAdapter,
}

def collect_sources(source='all', limit=10):
    names = list(ADAPTERS) if source == 'all' else [source]
    observations=[]
    for name in names:
        if name not in ADAPTERS: raise SystemExit(f'unknown source {name}; choose {list(ADAPTERS)} or all')
        observations.extend(ADAPTERS[name]().collect(limit=limit))
    return observations[:limit] if source != 'all' else observations
