#!/usr/bin/env python3
from __future__ import annotations
import glob
from pathlib import Path
from urllib.parse import urlparse
from subc_common import Observation, ReadOnlyCommandRunner, now_iso, redact
from subc_paths import hermes_home, workspace_root, room_path, openclaw_services, mem0g_services, mem0g_health_url, openclaw_skill_paths, mem0g_paths

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
        home=hermes_home()
        cfg=home/'config.yaml'
        if cfg.exists(): out.append(self.obs('config', f'file:{cfg}', 'Hermes config exists for read-only inspection', 0.7, path=str(cfg)))
        skills=home/'skills'
        if skills.exists():
            count=sum(1 for _ in skills.glob('*'))
            out.append(self.obs('skills-dir', f'file:{skills}', f'Hermes skills directory exists with {count} top-level entries', 0.7, count=count))
        sessions=home/'sessions'
        if sessions.exists():
            count=sum(1 for _ in sessions.glob('*.jsonl'))
            out.append(self.obs('sessions-dir', f'file:{sessions}', f'Hermes session transcript directory exists with {count} JSONL files', 0.65, count=count))
        room=room_path()
        topics=room/'telegram_topics.json'
        if topics.exists(): out.append(self.obs('subc-room', f'file:{room}', 'SUBCONSCIOUS room exists with chat topic mapping', 0.95, room=str(room)))
        return out[:limit]

class OpenClawAdapter(BaseAdapter):
    name='OpenClawAdapter'; source='openclaw'
    def collect(self, limit=10):
        out=[]
        for svc in openclaw_services():
            code, txt = self.runner.run(['systemctl','is-active',svc], timeout=5)
            out.append(self.obs(f'service-{svc}', f'service:{svc}', f'{svc} active check: {txt.strip() or "unknown"}', 0.6, exit_code=code))
        for pp in openclaw_skill_paths():
            if pp.exists(): out.append(self.obs(f'path-{pp.name}', f'file:{pp}', f'OpenClaw-related skill path exists: {pp.name}', 0.75, path=str(pp)))
        return out[:limit]

class Mem0gAdapter(BaseAdapter):
    name='Mem0gAdapter'; source='mem0g'
    def collect(self, limit=10):
        out=[]
        url = mem0g_health_url()
        parsed = urlparse(url)
        if parsed.scheme in {'http','https'} and parsed.hostname in {'127.0.0.1','localhost'}:
            code, txt = self.runner.run(['curl','-fsS',url], timeout=5)
            out.append(self.obs('health', url, f'mem0g health check: {txt.strip() or "no response"}', 0.95 if code==0 else 0.5, exit_code=code))
        else:
            out.append(self.obs('health-skipped', url, 'mem0g health check skipped: only localhost URLs are allowed by default', 0.3))
        for svc in mem0g_services():
            code, txt = self.runner.run(['systemctl','is-active',svc], timeout=5)
            out.append(self.obs(f'service-{svc}', f'service:{svc}.service', f'{svc}.service active check: {txt.strip() or "unknown"}', 0.85, exit_code=code))
        for pp in mem0g_paths():
            if pp.exists(): out.append(self.obs(f'path-{pp.name}', f'file:{pp}', f'mem0g discovery path exists: {pp}', 0.8, path=str(pp)))
        return out[:limit]

class ProjectFlowAdapter(BaseAdapter):
    name='ProjectFlowAdapter'; source='project-flow'
    def collect(self, limit=10):
        out=[]
        pattern=str(workspace_root()/'*'/'STATE.yaml')
        for path in glob.glob(pattern)[:limit]:
            text=Path(path).read_text(errors='ignore')[:2000]
            project=Path(path).parent.name
            summary=f'project-flow state found for {project}; size={len(text)} bytes sample'
            out.append(self.obs(f'state-{project}', f'file:{path}', summary, 0.8, project=project, path=path))
        return out[:limit]

ADAPTERS = {
    'hermes': HermesAdapter,
    'openclaw': OpenClawAdapter,
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
