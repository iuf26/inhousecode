#!/usr/bin/env python3
"""Build the explain briefing from a normalized finding list.

The briefing is the deterministic half of ``inhousecode explain``: no model is
involved in producing it. It restates every finding with the review category
and the source lines it points at.

Input is a tab-separated record per finding, already de-duplicated by the shared
``select_findings`` helper so the markers stay defined in exactly one place:

    gate<TAB>SEVERITY<TAB>file:line<TAB>category<TAB>one-line fix

Usage:  explain.py --findings <tsv> --out <briefing.md> [options]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
BLOCKING_SEVERITIES = {"CRITICAL", "HIGH"}
FINDING_FIELDS = 5
# Excerpts are context, not the file. A wide window buries the marked line.
MAX_CONTEXT_LINES = 25
LOCATION = re.compile(r"^(?P<path>.+):(?P<line>\d+)$")
GATE_LABELS = {"static": "Semgrep (phase 1)", "review": "AI review (phase 2)"}
MEMORY_HEADING_SCOPES = {
    "## Promoted project knowledge": "project",
    "## Promoted global knowledge": "global",
}
MEMORY_RECORD = re.compile(r"^- \[(?P<id>[^]]+)] (?P<content>.+)$")
MEMORY_URI = re.compile(r"^\s+URI: (?P<uri>[^;]+);")


class Finding:
    """One normalized gate finding, plus whatever context we could resolve."""

    def __init__(self, gate: str, severity: str, location: str, category: str, fix: str):
        self.gate = gate
        self.severity = severity
        self.location = location
        self.category = category
        self.fix = fix
        self.path = ""
        self.line = 0
        match = LOCATION.match(location.strip())
        if match:
            self.path = match.group("path").strip().replace("\\", "/")
            self.line = int(match.group("line"))

    @property
    def blocking(self) -> bool:
        return self.severity in BLOCKING_SEVERITIES

    @property
    def rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, len(SEVERITY_ORDER))


def read_findings(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    for row in raw.splitlines():
        if not row.strip():
            continue
        fields = row.split("\t")
        if len(fields) != FINDING_FIELDS:
            continue
        findings.append(Finding(*(field.strip() for field in fields)))
    findings.sort(key=lambda item: item.rank)
    return findings


def parse_memory_rules(context: str) -> dict[str, dict[str, str]]:
    """Extract promoted rule provenance from the frozen prompt context."""
    rules: dict[str, dict[str, str]] = {}
    scope = ""
    current_id = ""
    for line in context.splitlines():
        if line.startswith("## "):
            scope = MEMORY_HEADING_SCOPES.get(line.strip(), "")
            current_id = ""
            continue
        match = MEMORY_RECORD.match(line)
        if match and scope:
            current_id = match.group("id")
            rules[current_id] = {
                "scope": scope,
                "content": match.group("content").strip(),
                "uri": "",
            }
            continue
        uri_match = MEMORY_URI.match(line)
        if uri_match and current_id:
            rules[current_id]["uri"] = uri_match.group("uri").strip()
    return rules



def read_source(finding: Finding, args: argparse.Namespace) -> list[str] | None:
    """Read the reviewed content of a file, from wherever the gate judged it.

    Staged mode judges the index, not the working tree (invariant 6), so an
    excerpt taken from disk could show lines that were never under review.

    finding.path comes from a gate finding's location field, which for the AI
    gate is model output over reviewed (and possibly adversarial) diff content.
    It must resolve to a path inside the repository before anything reads it -
    otherwise an absolute path or a '..' escape lets a crafted finding pull
    arbitrary local file content (e.g. ~/.ssh/id_rsa) into the explain briefing
    that gets sent to the model.
    """
    if not finding.path:
        return None
    repo_root = Path(args.repo_root).resolve()
    resolved = (repo_root / finding.path).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        return None
    revision = ""
    if args.target_mode == "staged":
        revision = ""
    elif args.target_mode == "diff" and args.diff_source == "commit":
        revision = args.diff_head

    if args.target_mode in {"staged", "diff"}:
        spec = f"{revision}:{finding.path}"
        try:
            completed = subprocess.run(
                ["git", "show", spec],
                cwd=args.repo_root,
                capture_output=True,
                check=False,
            )
        except (OSError, ValueError):
            return None
        if completed.returncode == 0:
            return completed.stdout.decode("utf-8", errors="replace").splitlines()
        # A file the index does not have (a worktree-only repair) still has a
        # readable copy on disk; fall through rather than dropping the excerpt.

    try:
        if not resolved.is_file():
            return None
        return resolved.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return None


def build_excerpt(finding: Finding, lines: list[str] | None, context: int) -> list[str]:
    if not lines or finding.line < 1:
        return []
    if finding.line > len(lines):
        return []
    first = max(1, finding.line - context)
    last = min(len(lines), finding.line + context)
    width = len(str(last))
    rendered: list[str] = []
    for number in range(first, last + 1):
        marker = ">" if number == finding.line else " "
        body = lines[number - 1].replace("\t", "    ").rstrip()
        rendered.append(f"{marker} {str(number).rjust(width)} | {body}")
    return rendered


def render(findings: list[Finding], rules: dict, args: argparse.Namespace) -> str:
    blocking = sum(1 for finding in findings if finding.blocking)
    advisory = len(findings) - blocking
    out: list[str] = []
    out.append("# inhousecode findings")
    out.append("")
    out.append(
        f"{len(findings)} finding(s) to explain - {blocking} blocking, "
        f"{advisory} advisory."
    )
    out.append("")
    out.append(f"- Repository: `{args.repo_root}`")
    out.append(f"- Review target: {args.target_mode}")
    out.append("")
    out.append("Each finding below is stated as the gate produced it; excerpts are the reviewed content.")
    out.append("")

    for index, finding in enumerate(findings, start=1):
        gate = GATE_LABELS.get(finding.gate, finding.gate)
        blocking_label = "blocking" if finding.blocking else "advisory"
        out.append("---")
        out.append("")
        out.append(
            f"## [{index}] {finding.severity} - "
            f"{finding.location} - {finding.category}"
        )
        out.append("")
        out.append(f"- Found by: {gate} ({blocking_label})")
        out.append(f"- Gate's one-line fix: {finding.fix}")

        rule = rules.get(finding.category)
        if finding.gate == "static":
            out.append(
                f"- Rule violated: Semgrep rule `{finding.category}`"
            )
            out.append("- Rule source: static analysis")
        elif rule:
            out.append(f"- Rule source: promoted {rule['scope']} knowledge")
            out.append(f"- Rule: {rule['content']}")
            out.append(f"- Memory record: `{finding.category}`")
            if rule.get("uri"):
                out.append(f"- Memory URI: `{rule['uri']}`")
        else:
            out.append(f"- Review category `{finding.category}`")
            out.append("- Rule source: built-in AI review guidance")
        out.append("")

        excerpt = build_excerpt(
            finding, read_source(finding, args), args.context
        )
        if excerpt:
            out.append(f"Source, `{finding.path}` (`>` marks line {finding.line}):")
            out.append("")
            out.append("```text")
            out.extend(excerpt)
            out.append("```")
        else:
            out.append(f"Source excerpt unavailable for `{finding.location}`.")
        out.append("")

    return "\n".join(out) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the explain briefing.")
    parser.add_argument("--findings", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo-root", default=".")

    parser.add_argument("--target-mode", default="staged")
    parser.add_argument("--diff-head", default="HEAD")
    parser.add_argument("--diff-source", default="commit")
    parser.add_argument("--context", type=int, default=5)
    args = parser.parse_args(argv)
    args.context = max(0, min(MAX_CONTEXT_LINES, args.context))
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    findings = read_findings(Path(args.findings))
    if not findings:
        print("explain: no findings to brief", file=sys.stderr)
        return 1
    rules = parse_memory_rules(os.environ.get("AI_MEMORY_CONTEXT", ""))
    briefing = render(findings, rules, args)
    out_path = Path(args.out)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(briefing)
    except OSError as error:
        print(f"explain: could not write the briefing: {error}", file=sys.stderr)
        return 1
    print(len(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
