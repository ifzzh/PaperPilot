#!/usr/bin/env python3
"""Apply PaperPilot's narrow, expiring policy to pip-audit JSON reports."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


def load_exceptions(path: Path) -> list[dict]:
    entries = json.loads(path.read_text(encoding="utf-8")).get("exceptions", [])
    today = dt.date.today()
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        required = {"id", "package", "targets", "rationale", "expires"}
        if not required.issubset(entry):
            raise ValueError("vulnerability exception is missing required fields")
        if any("*" in str(entry[key]) for key in ("id", "package")):
            raise ValueError("wildcard vulnerability exceptions are forbidden")
        key = (entry["id"], entry["package"].lower())
        if key in seen:
            raise ValueError("duplicate vulnerability exception")
        seen.add(key)
        expires = dt.date.fromisoformat(entry["expires"])
        if expires < today:
            raise ValueError(f"expired vulnerability exception: {entry['id']}")
        if not entry["targets"] or not entry["rationale"].strip():
            raise ValueError("vulnerability exceptions require targets and rationale")
    return entries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exceptions", required=True, type=Path)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    exceptions = load_exceptions(args.exceptions)
    failures: list[str] = []
    unfixed: list[str] = []

    for report_path in args.reports:
        target = report_path.stem.removesuffix("-pip-audit")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for dependency in report.get("dependencies", []):
            package = dependency["name"].lower()
            for vulnerability in dependency.get("vulns", []):
                vuln_id = vulnerability["id"]
                identifiers = {vuln_id, *vulnerability.get("aliases", [])}
                allowed = any(
                    package == entry["package"].lower()
                    and target in entry["targets"]
                    and identifiers.intersection({entry["id"], *entry.get("aliases", [])})
                    for entry in exceptions
                )
                message = f"{target}: {package} {dependency['version']} {vuln_id}"
                if allowed:
                    print(f"EXCEPTION {message}")
                elif vulnerability.get("fix_versions"):
                    failures.append(message)
                else:
                    unfixed.append(message)

    for message in unfixed:
        print(f"UNFIXED {message}")
    for message in failures:
        print(f"BLOCKED {message}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
