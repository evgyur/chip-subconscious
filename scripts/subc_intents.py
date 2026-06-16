#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from subc_common import now_iso, load_json, write_json, redact, intent_eligibility

def yaml_quote(s):
    return '"' + str(s).replace('\\','\\\\').replace('"','\\"').replace('\n','\\n') + '"'

def write_intent_yaml(path: Path, intent: dict):
    lines=[]
    for k in ['schema_version','id','title','problem','suggested_build','risk','confidence','approval_required','status']:
        v=intent[k]
        if isinstance(v,bool): val='true' if v else 'false'
        elif isinstance(v,(int,float)): val=str(v)
        else: val=yaml_quote(v)
        lines.append(f'{k}: {val}')
    for k in ['source_adapters','non_goals','acceptance_criteria','related_intents']:
        lines.append(f'{k}:')
        for item in intent.get(k,[]): lines.append(f'  - {yaml_quote(item)}')
    lines.append('duplicate_of: null')
    lines.append('evidence:')
    for ev in intent['evidence']:
        lines.append(f'  - evidence_uri: {yaml_quote(ev.get("evidence_uri",""))}')
        lines.append(f'    summary: {yaml_quote(ev.get("summary",""))}')
        if ev.get('source_adapter'): lines.append(f'    source_adapter: {yaml_quote(ev.get("source_adapter"))}')
    candidate = intent.get('candidate_patch') or {}
    if candidate:
        lines.append('candidate_patch:')
        for key in ['schema_version','status','patch_type','title','target','action','source','privacy']:
            if key in candidate:
                lines.append(f'  {key}: {yaml_quote(candidate.get(key, ""))}')
        lines.append('  evidence_items:')
        for item in candidate.get('evidence_items', []):
            lines.append(f'    - evidence_uri: {yaml_quote(item.get("evidence_uri", ""))}')
            lines.append(f'      bucket: {yaml_quote(item.get("bucket", ""))}')
            lines.append(f'      summary: {yaml_quote(item.get("summary", ""))}')
    path.write_text('\n'.join(lines)+'\n')

def build_intent(sig):
    sid=sig['id']
    if sid == 'openclaw-runtime-inactive':
        title='Проверить, почему OpenClaw/GoClaw выглядит неактивным'
        problem='Простыми словами: слой наблюдения видит, что часть OpenClaw/GoClaw будто спит или не отвечает. Нужно понять: это нормальная схема на ryzen64 или реальная поломка.'
        suggested='Сделать только безопасный аудит схемы OpenClaw/GoClaw без изменений: какие сервисы должны быть живыми, какие могут быть выключены, где фактическое расхождение. Ничего не перезапускать без отдельного решения.'
    elif sid == 'mem0g-health-issue':
        title='Проверить здоровье mem0g'
        problem='Простыми словами: слой наблюдения заметил сигнал, что mem0g может быть нездоров или сервис отвечает не так, как должен.'
        suggested='Запустить безопасную диагностику mem0g без изменений, собрать факты и, если проблема подтвердится, предложить отдельную задачу восстановления.'
    elif sid == 'hermes-cross-session-recall-gap':
        title='Сделать автоподхват контекста между Telegram-сессиями Hermes'
        problem='Простыми словами: Hermes всё ещё иногда начинает новую Telegram-сессию без нужного прошлого контекста. Это ровно та боль, из-за которой Чипу приходится повторять, что уже обсуждали.'
        suggested='Сделать безопасную предварительную проверку: перед ответом основной Hermes компактно собирает релевантные прошлые сессии и открытые обещания в короткий контекст, не притворяясь слоем наблюдения.'
    elif sid == 'secret-hygiene-transcript-surface':
        title='Проверить, не светятся ли секреты в памяти и транскриптах'
        problem='Простыми словами: ключи и токены могут попадать в память, пересказы или рабочие файлы. Главный риск — случайно снова показать секрет в чате.'
        suggested='Сделать отчёт со скрытыми значениями и выдать точный список: что удалить, что ротировать, что закрыть. Самостоятельно секреты не удалять и не ротировать.'
    elif sid == 'openclaw-session-error-pattern':
        title='Разобрать повторяющиеся ошибки в OpenClaw-сессиях Chip'
        problem='Простыми словами: SUBCONSCIOUS видит в свежих OpenClaw-сессиях Chip повторяющиеся error/friction patterns. Это источник будущих поломок и ручных повторов.'
        suggested='Сделать безопасный read-only разбор OpenClaw session corpus: сгруппировать ошибки по агентам, найти первопричины, предложить маленькие исправления с тестами. Ничего не менять без отдельного approved build.'
    elif sid == 'openclaw-session-corpus-unreachable':
        title='Починить доступ SUBCONSCIOUS к OpenClaw session corpus'
        problem='Простыми словами: SUBCONSCIOUS не может стабильно читать OpenClaw-сессии Chip, поэтому не увидит проблемы до того, как они повторятся.'
        suggested='Проверить read-only SSH/path доступ к текущему HEL1 corpus (`chip@157.180.97.244:/home/chip/.openclaw`), включая `chipdev` как agent lane, зафиксировать минимальные права чтения и health check. Не добавлять новые секреты в repo или room.'
    elif sid == 'manual-repeat-automation-opportunity':
        first_ev = (sig.get('evidence') or [{}])[0]
        candidate = first_ev.get('automation_candidate') or {}
        ctype = candidate.get('type') or 'reusable_skill'
        artifact = candidate.get('suggested_artifact') or 'начать с reusable skill и не включать live automation без отдельного approval'
        trigger = candidate.get('trigger_phrase') or 'повторяющаяся ручная операция'
        title='Собрать повторяющуюся ручную операцию в automation candidate'
        problem=f'Простыми словами: найден повтор ручной операции. Нужно не сразу автоматизировать прод, а оформить безопасный candidate типа {ctype} с evidence и проверкой.'
        suggested=f'Сделать минимальный безопасный automation candidate: {artifact}. Evidence/trigger: {trigger}. Cron/watchdog/live slash-command включать только отдельным approval, если это меняет расписание, сервисы или пользовательские каналы.'
    else:
        title=sig['title']
        first_ev = (sig.get('evidence') or [{}])[0]
        candidate = first_ev.get('candidate_patch') or {}
        if candidate:
            patch_type = candidate.get('patch_type', 'skill')
            problem=f'Простыми словами: найден явный repeat-паттерн в правках Chip. Его нужно не терять в чате, а превратить в candidate {patch_type} с redacted evidence.'
            suggested=f'Создать candidate {patch_type}: {candidate.get("action") or first_ev.get("proposed_action")}. Цель уточняет Shaw/Hermes после approval; evidence — только session pointers и редактированные summaries.'
        else:
            problem=f'Простыми словами: SUBCONSCIOUS нашёл повторяющийся паттерн в сессиях — {sig["title"]}.'
            suggested=first_ev.get('proposed_action') or 'Посмотреть сигнал и нажать: делать из него задачу или убрать в архив.'
    first_ev = (sig.get('evidence') or [{}])[0]
    risk = first_ev.get('risk') or 'Может быть ложная тревога: сервис выглядит неактивным, но это может быть нормальная топология.'
    return {
        'schema_version':'1.0', 'id':'intent_'+sid, 'title':title, 'problem':redact(problem),
        'evidence':sig.get('evidence',[]), 'source_adapters':sorted({e.get('source_adapter','ManualAdapter') for e in sig.get('evidence',[])}),
        'suggested_build':redact(suggested),
        'candidate_patch': first_ev.get('candidate_patch') or {},
        'non_goals':['Слой наблюдения не меняет прод','Без рестартов сервисов','Без изменений секретов, доступов и ключей'],
        'acceptance_criteria':['Факты проверены только безопасным чтением','Решение записано: да / нет / отложить','Если одобрено, пакет задачи содержит проверки и откат'],
        'risk':redact(risk),
        'confidence':min(1.0, round(sig.get('score',0)/10,2)), 'duplicate_of':None, 'related_intents':[], 'approval_required':True, 'status':'pending_approval'
    }

def _intent_sort_key(sig):
    evidence = sig.get('evidence') or []
    chip_value = any((e or {}).get('chip_value_signal') for e in evidence)
    repeat = 'repeat' in set(sig.get('signal_types') or [])
    return (1 if chip_value else 0, 1 if repeat else 0, float(sig.get('score', 0) or 0))


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--room', default='/home/hermes/.hermes/profiles/subc/room'); ap.add_argument('--max', type=int, default=3); ap.add_argument('--force', action='store_true')
    args=ap.parse_args(); room=Path(args.room); data=load_json(room/'signals.json', {'signals':{}}); out=[]; blocked=[]
    d=room/'pending_intents'; d.mkdir(exist_ok=True)
    for sig in sorted(data.get('signals',{}).values(), key=_intent_sort_key, reverse=True):
        if len(out)>=args.max: break
        if sig.get('status')!='pending_intent' and not args.force: continue
        eligible, reason = intent_eligibility(sig)
        if not eligible and not args.force:
            blocked.append({'id': sig.get('id'), 'reason': reason})
            continue
        intent=build_intent(sig); path=d/(intent['id']+'.yaml')
        if path.exists(): continue
        write_intent_yaml(path, intent); out.append(str(path))
    if blocked:
        summary=load_json(room/'summary.json', {'schema_version':'1.0','lanes':{}})
        lanes=summary.setdefault('lanes', {})
        ready_ids={Path(p).stem.replace('intent_', '', 1) for p in out}
        lanes['blocked_ready']=[
            {
                'id': item['id'],
                'title': (data.get('signals',{}).get(item['id']) or {}).get('title', item['id']),
                'score': (data.get('signals',{}).get(item['id']) or {}).get('score'),
                'status': 'blocked_ready',
                'reason': item['reason'],
            }
            for item in blocked
            if item.get('id') not in ready_ids
        ]
        write_json(room/'summary.json', summary)
    print(json.dumps({'created':out, 'blocked': blocked}, ensure_ascii=False, indent=2))
if __name__ == '__main__': raise SystemExit(main())
