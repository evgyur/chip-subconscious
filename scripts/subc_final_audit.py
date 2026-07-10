#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def audit_artifacts(repo_root: str | Path) -> tuple[list[str], dict[str, Any]]:
    root = Path(repo_root)
    report_dir = root / "reports/v3"
    errors: list[str] = []
    passed = 0
    for number in range(1, 9):
        path = report_dir / f"phase-{number:02d}.md"
        if not path.is_file():
            errors.append(f"phase_report_missing:{number:02d}")
        elif "PASS" not in path.read_text():
            errors.append(f"phase_report_not_pass:{number:02d}")
        else:
            passed += 1
    backtest = json.loads((report_dir / "backtest.json").read_text()) if (report_dir / "backtest.json").is_file() else {}
    shadow = json.loads((report_dir / "shadow-run.json").read_text()) if (report_dir / "shadow-run.json").is_file() else {}
    receipt = json.loads((report_dir / "rollout-receipt.json").read_text()) if (report_dir / "rollout-receipt.json").is_file() else {}
    if backtest.get("rollout_gate_pass") is not True:
        errors.append("backtest_gate_not_green")
    if shadow.get("shadow_gate_pass") is not True or shadow.get("live_mutation_detected") is not False:
        errors.append("shadow_gate_not_green")
    if receipt.get("fetched_back") is not True:
        errors.append("rollout_readback_missing")
    if receipt.get("second_cycle", {}).get("telegram_delivery_count") != 0:
        errors.append("second_cycle_not_silent")
    if receipt.get("rollback_drill", {}).get("restored_to_v3_steady") is not True:
        errors.append("rollback_not_restored")
    evidence: dict[str, Any] = {
        "schema_version": "subc-v3-final-audit/1",
        "phase_reports_passed": passed,
        "backtest_gate_pass": backtest.get("rollout_gate_pass") is True,
        "shadow_gate_pass": shadow.get("shadow_gate_pass") is True,
        "delivery_fetched_back": receipt.get("fetched_back") is True,
        "second_cycle_silent": receipt.get("second_cycle", {}).get("telegram_delivery_count") == 0,
        "rollback_restored": receipt.get("rollback_drill", {}).get("restored_to_v3_steady") is True,
    }
    return errors, evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit SUBCONSCIOUS v3 rollout artifacts")
    parser.add_argument("--package", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default="reports/v3/final-audit.json")
    args = parser.parse_args()
    errors, evidence = audit_artifacts(args.repo_root)
    evidence["package_present"] = Path(args.package).is_dir()
    if not evidence["package_present"]:
        errors.append("package_missing")
    evidence["errors"] = errors
    evidence["passed"] = not errors
    Path(args.output).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": not errors, "errors": errors}, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
