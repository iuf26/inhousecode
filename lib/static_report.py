#!/usr/bin/env python3
"""Render the static gate report from a static_scan.sh envelope.

Emits the shared finding contract:

    ##STATIC-FINDING##<TAB>SEVERITY<TAB>file:line<TAB>check-id<TAB>fix
    STATIC-CHECK: PASS|FAIL

Exit status: 0 pass, 1 blocking findings, 2 the gate could not run.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SEVERITY_MAP = {"ERROR": "CRITICAL", "WARNING": "MEDIUM", "INFO": "LOW"}
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
BLOCKING_SEVERITIES = {"CRITICAL", "HIGH"}
FINDING_MARKER = "##STATIC-FINDING##"
VERDICT_PREFIX = "STATIC-CHECK"
EXIT_PASS, EXIT_BLOCKING, EXIT_UNAVAILABLE = 0, 1, 2
DELETED_PLACEHOLDER = ("false", "none", "null")

# The finding contract is line-based and is parsed by awk. On Windows, Python
# would otherwise translate "\n" to "\r\n" on write, leaving a stray CR at the
# end of the `fix` field of every finding. Pin the newline so the contract is
# byte-identical on every platform.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(newline="\n")


class ReportFormatError(ValueError):
    """Raised when scanner output does not match the expected contract."""


def clean(value: object) -> str:
    return " ".join(str(value or "").replace("\t", " ").split())


def has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def source_path(value: object, scan_target: object) -> str:
    """Strip the isolated scan tree prefix so findings cite repo-relative paths."""
    path = str(value or "").replace("\\", "/")
    root = str(scan_target or "").replace("\\", "/").rstrip("/")
    if root and path.lower().startswith(f"{root.lower()}/"):
        path = path[len(root) + 1 :]
    return path


def load_json_object(path: Path, label: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReportFormatError(f"{label} must be a JSON object")
    return value


def trusted_report_path(report_value: object) -> Path:
    """Resolve the Semgrep report, refusing any path outside the scan cache."""
    if not isinstance(report_value, str) or report_value == "none":
        raise ReportFormatError("scan has no Semgrep report path")
    if has_control_characters(report_value):
        raise ReportFormatError("Semgrep report path contains control characters")
    configured_root = os.environ.get("INHOUSECODE_CACHE_ROOT")
    try:
        cache_root = Path(
            configured_root or Path.cwd() / ".inhousecode" / "cache"
        ).resolve()
        report_path = Path(report_value).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ReportFormatError("could not resolve the Semgrep report path") from error
    try:
        report_path.relative_to(cache_root)
    except ValueError as error:
        raise ReportFormatError(
            "Semgrep report path is outside the scan cache root"
        ) from error
    return report_path


def load_scan(scan_path: Path) -> dict:
    scan = load_json_object(scan_path, "scan envelope")
    status = scan.get("scan_status")
    if status not in {"completed", "skipped", "unavailable"}:
        raise ReportFormatError(f"invalid scan_status: {status!r}")
    if status == "completed":
        report_value = scan.get("semgrep_json")
        if not isinstance(report_value, str) or report_value == "none":
            raise ReportFormatError("completed scan has no Semgrep report path")
    return scan


def validate_report(report: dict) -> list[dict]:
    results = report.get("results")
    errors = report.get("errors")
    if not isinstance(results, list) or not isinstance(errors, list):
        raise ReportFormatError("Semgrep report requires results and errors arrays")
    if errors:
        raise ReportFormatError("Semgrep report contains scan errors")

    validated: list[dict] = []
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise ReportFormatError(f"result {index} must be an object")
        extra, start = result.get("extra"), result.get("start")
        if not isinstance(extra, dict) or not isinstance(start, dict):
            raise ReportFormatError(f"result {index} has an invalid shape")
        if str(extra.get("severity")).upper() not in SEVERITY_MAP:
            raise ReportFormatError(f"result {index} has an invalid severity")
        result_path = result.get("path")
        if (
            not isinstance(result_path, str)
            or not result_path
            or has_control_characters(result_path)
        ):
            raise ReportFormatError(f"result {index} has an invalid path")
        line = start.get("line")
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            raise ReportFormatError(f"result {index} has an invalid start.line")
        if not clean(result.get("check_id")):
            raise ReportFormatError(f"result {index} has no check_id")
        if not clean(extra.get("message")):
            raise ReportFormatError(f"result {index} has no message")
        validated.append(result)
    return validated


def short_rule(check_id: str) -> str:
    """Reduce a dotted Semgrep check id to its last, most specific segment.

    `python.lang.security.audit.subprocess-shell-true.subprocess-shell-true`
    carries one word of information; the rest is taxonomy. The table has to stay
    readable at terminal width, so only that word is kept.
    """
    segments = [segment for segment in check_id.split(".") if segment]
    return segments[-1] if segments else check_id


def short_fix(text: str, limit: int = 180) -> str:
    """First sentence of a Semgrep message, hard-capped."""
    sentence = text.strip()
    for terminator in (". ", "! ", "? "):
        head = sentence.split(terminator, 1)[0]
        if head != sentence:
            sentence = head + terminator.strip()
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rstrip() + "\u2026"
    return sentence


def build_findings(
    results: list[dict], scan_target: object
) -> list[tuple[str, str, str, str]]:
    findings: list[tuple[str, str, str, str]] = []
    for result in results:
        extra, start = result["extra"], result["start"]
        severity = SEVERITY_MAP[str(extra["severity"]).upper()]
        location = f"{source_path(result['path'], scan_target)}:{start['line']}"
        category = short_rule(clean(result["check_id"]))
        fix_value = extra.get("fix")
        if (
            not isinstance(fix_value, str)
            or not fix_value.strip()
            or fix_value.strip().lower() in DELETED_PLACEHOLDER
        ):
            fix_value = extra["message"]
        findings.append((severity, location, category, short_fix(clean(fix_value))))
    findings.sort(key=lambda item: SEVERITY_ORDER[item[0]])
    return findings


def print_findings(findings: list[tuple[str, str, str, str]]) -> int:
    blocking = sum(severity in BLOCKING_SEVERITIES for severity, *_ in findings)
    # Only contract lines are emitted. Counts and headings are the renderer's
    # job (print_findings_report); duplicating them here would leak scaffolding
    # into the terminal and give the summary two sources of truth.
    for severity, location, category, fix in findings:
        print(f"{FINDING_MARKER}\t{severity}\t{location}\t{category}\t{fix}")
    print(f"{VERDICT_PREFIX}: {'FAIL' if blocking else 'PASS'}")
    return EXIT_BLOCKING if blocking else EXIT_PASS


def print_report(scan: dict) -> int:
    status = scan.get("scan_status", "unavailable")
    if status != "completed":
        label = "skipped" if status == "skipped" else "unavailable"
        print(f"Static analysis {label}: {clean(scan.get('scan_reason'))}.")
        print(f"{VERDICT_PREFIX}: {'PASS' if status == 'skipped' else 'FAIL'}")
        return EXIT_PASS if status == "skipped" else EXIT_UNAVAILABLE

    report = load_json_object(
        trusted_report_path(scan["semgrep_json"]), "Semgrep report"
    )
    return print_findings(
        build_findings(validate_report(report), scan.get("scan_target"))
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: static_report.py <scan.json>", file=sys.stderr)
        return EXIT_UNAVAILABLE
    try:
        return print_report(load_scan(Path(sys.argv[1])))
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ReportFormatError,
    ) as error:
        print(f"static_report: {error}", file=sys.stderr)
        return EXIT_UNAVAILABLE


if __name__ == "__main__":
    raise SystemExit(main())
