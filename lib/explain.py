#!/usr/bin/env python3
"""Build the explain briefing from a normalized finding list.

The briefing is the deterministic half of ``inhousecode explain``: no model is
involved in producing it. It restates every finding with two things the terminal
table has no room for -- the team rule it violates, quoted verbatim from the
rulebook, and the source lines it points at.

Quoting the rule verbatim matters: "which rule did I break" is then answered by
the file the team wrote, not paraphrased by a model that may drift from it.

Input is a tab-separated record per finding, already de-duplicated by the shared
``select_findings`` helper so the markers stay defined in exactly one place:

    gate<TAB>SEVERITY<TAB>file:line<TAB>category<TAB>one-line fix

Usage:  explain.py --findings <tsv> --out <briefing.md> [options]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
BLOCKING_SEVERITIES = {"CRITICAL", "HIGH"}
FINDING_FIELDS = 5
# A rulebook entry: "- [ ] id (scope) — the rule".
RULEBOOK_ENTRY = re.compile(
    r"^\s*-\s*\[[^\]]*\]\s*"
    r"(?P<id>[A-Za-z0-9][A-Za-z0-9._-]*)\s*"
    r"\((?P<scope>[^)]*)\)\s*"
    r"[\u2014\u2013-]+\s*"
    r"(?P<rule>.+?)\s*$"
)
# Below this length an id match on a substring is noise rather than a signal.
MIN_FUZZY_RULE_ID = 4
# Excerpts are context, not the file. A wide window buries the marked line.
MAX_CONTEXT_LINES = 25
LOCATION = re.compile(r"^(?P<path>.+):(?P<line>\d+)$")
GATE_LABELS = {"static": "Semgrep (phase 1)", "review": "AI review (phase 2)"}


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


def parse_rulebook(path: Path) -> dict[str, dict[str, str]]:
    """Map rule id -> {line, scope, rule} for every entry in the rulebook."""
    rules: dict[str, dict[str, str]] = {}
    if not path or not path.is_file():
        return rules
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rules
    for row in raw.splitlines():
        match = RULEBOOK_ENTRY.match(row)
        if not match:
            continue
        rule_id = match.group("id").strip()
        rules[rule_id.lower()] = {
            "id": rule_id,
            "scope": match.group("scope").strip(),
            "rule": match.group("rule").strip(),
            "line": row.strip(),
        }
    return rules


def normalize_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def match_rule(category: str, rules: dict[str, dict[str, str]]) -> dict[str, str] | None:
    """Resolve a finding's category to a rulebook entry.

    The reviewer is asked to cite the rule id in the category field, so an exact
    match is the common case. The fuzzy pass catches a category that wrapped the
    id in extra words ("violates no-broad-except").
    """
    if not rules:
        return None
    normalized = normalize_id(category)
    if not normalized:
        return None
    if normalized in rules:
        return rules[normalized]
    for rule_id, entry in rules.items():
        if len(rule_id) < MIN_FUZZY_RULE_ID:
            continue
        if rule_id in normalized or normalized in rule_id:
            return entry
    return None


def read_source(finding: Finding, args: argparse.Namespace) -> list[str] | None:
    """Read the reviewed content of a file, from wherever the gate judged it.

    Staged mode judges the index, not the working tree (invariant 6), so an
    excerpt taken from disk could show lines that were never under review.
    """
    if not finding.path:
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

    candidate = Path(args.repo_root) / finding.path
    try:
        if not candidate.is_file():
            return None
        return candidate.read_text(encoding="utf-8", errors="replace").splitlines()
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
    if args.rulebook_path:
        out.append(f"- Team rulebook: `{args.rulebook_path}`")
    else:
        out.append("- Team rulebook: none in this repository")
    out.append("")
    out.append(
        "Each finding below is stated as the gate produced it. Rule text is "
        "quoted verbatim from the rulebook; excerpts are the reviewed content."
    )
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

        entry = match_rule(finding.category, rules)
        if entry:
            out.append(f"- Rule violated (verbatim from the rulebook): `{entry['id']}`")
            out.append("")
            out.append(f"  > {entry['line']}")
        elif finding.gate == "static":
            out.append(
                f"- Rule violated: Semgrep rule `{finding.category}` "
                "(no matching team rule)"
            )
        else:
            out.append(
                "- Rule violated: no team rule matched; this is a general "
                "review criterion"
            )
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
    parser.add_argument("--rulebook", default="")
    parser.add_argument("--rulebook-path", default="")
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
    rules = parse_rulebook(Path(args.rulebook)) if args.rulebook else {}
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
