#!/usr/bin/env python3
from __future__ import annotations
import os
from pathlib import Path


def _path_env(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


def hermes_home() -> Path:
    return _path_env('HERMES_HOME', '~/.hermes')


def workspace_root() -> Path:
    return _path_env('HERMES_WORKSPACE', '~/workspace')


def room_path() -> Path:
    return _path_env('SUBC_ROOM', str(hermes_home() / 'profiles' / 'subc' / 'room'))


def split_env(name: str, default: str = '') -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(',') if x.strip()]


def openclaw_services() -> list[str]:
    return split_env('SUBC_OPENCLAW_SERVICES', 'openclaw-gateway,goclaw,goclaw-inbox')


def mem0g_services() -> list[str]:
    return split_env('SUBC_MEM0G_SERVICES', 'mem0g-api,mem0g-inbox-adapter')


def mem0g_health_url() -> str:
    return os.getenv('SUBC_MEM0G_HEALTH_URL', 'http://127.0.0.1:8081/health')


def openclaw_skill_paths() -> list[Path]:
    default = ','.join([
        str(hermes_home() / 'skills' / 'chip-claw-core'),
        str(hermes_home() / 'skills' / 'chip-gigabrain'),
        str(hermes_home() / 'skills' / 'chip-mem0g'),
    ])
    return [Path(x).expanduser() for x in split_env('SUBC_OPENCLAW_SKILL_PATHS', default)]


def mem0g_paths() -> list[Path]:
    default = ','.join([
        str(workspace_root() / 'chip-mem0g'),
        str(workspace_root() / 'mem0g-recovery' / 'STATE.yaml'),
        str(workspace_root() / 'mem0g-recovery' / 'evidence'),
    ])
    return [Path(x).expanduser() for x in split_env('SUBC_MEM0G_PATHS', default)]
