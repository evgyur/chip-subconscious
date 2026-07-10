#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

SKIP_PARTS = {".git", "__pycache__", ".pytest_cache"}
BINARY_SUFFIXES = {
    ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
    ".zip", ".gz", ".tar", ".sqlite", ".db",
}
PATTERNS = (
    ("secret", re.compile(r"\b(?:sk-|gsk_|pplx-|gh[pousr]_)[A-Za-z0-9_-]{16,}")),
    ("secret", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")),
    ("secret", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("private_id", re.compile(r"(?<!\d)-100\d{10,}(?!\d)")),
    ("absolute_private_path", re.compile(r"/home/" + "hermes" + r"(?:/|\b)")),
)


def _iter_files(root: Path, excludes: set[str]) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_PARTS or part in excludes for part in relative.parts):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        yield path


def scan_path(path: str | Path, excludes: set[str] | None = None) -> list[dict[str, object]]:
    root = Path(path).resolve()
    excluded = set(excludes or ())
    findings: list[dict[str, object]] = []
    for file_path in _iter_files(root, excluded):
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        display = file_path.name if root.is_file() else file_path.relative_to(root).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append({"path": display, "line": line_number, "kind": kind})
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed public-repository privacy scan")
    parser.add_argument("--path", default=".")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--fail-on-private", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    findings = scan_path(args.path, set(args.exclude))
    payload = {"ok": not findings, "finding_count": len(findings), "findings": findings}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif findings:
        for item in findings:
            print(f"{item['kind']} {item['path']}:{item['line']}")
    else:
        print("privacy-scan: clean")
    return 1 if findings and args.fail_on_private else 0


if __name__ == "__main__":
    raise SystemExit(main())
