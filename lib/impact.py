#!/usr/bin/env python3
"""Extract the definitions a diff changes, so their consumers can be found.

A reviewer asked "does this break anything?" needs to know two things the diff
alone never shows: which *named contracts* the change touched, and who else in
the repository depends on them. This script answers the first half. It reads a
unified diff and reports every definition that appears on a changed line,
classified by how the change treats it:

    removed    the definition line only ever appears on a '-' line. Either
               deleted or renamed -- the highest-risk case, because every
               existing caller is now wrong.
    modified   it appears on both sides. The name survived; the signature,
               the value, or the shape may not have.
    added      it appears only on a '+' line. New surface, no existing callers,
               but it may collide with or duplicate something already there.

Detection is deliberately syntactic and language-agnostic. A parser per
language would be more precise and would cover a fraction of the repositories
this runs in; a regex that recognizes the definition idioms of the common
languages covers nearly all of them and degrades to "found nothing", which is
a safe answer.

Usage:  impact.py <diff-path>
Output: ``kind<TAB>change<TAB>name`` lines, one per definition, sorted with the
        riskiest first.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Definition idioms, by kind. Each pattern must capture the declared name in
# group 1. Anchored at the start of the (indent-stripped) line so a mere mention
# inside an expression is not mistaken for a declaration.
DEFINITION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("function", r"(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("),
    ("class", r"class\s+([A-Za-z_]\w*)\s*[\(:{ ]"),
    ("function", r"(?:export\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$]\w*)\s*[\(<]"),
    ("function", r"func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*[\(\[]"),
    ("interface", r"(?:export\s+)?interface\s+([A-Za-z_$]\w*)"),
    ("type", r"(?:export\s+)?type\s+([A-Za-z_$]\w*)\s*[=<]"),
    ("struct", r"(?:public\s+|private\s+|internal\s+)?struct\s+([A-Za-z_]\w*)"),
    ("enum", r"(?:export\s+)?enum\s+([A-Za-z_$]\w*)"),
    ("trait", r"trait\s+([A-Za-z_]\w*)"),
    # const NAME = (...) => / const NAME = function — a function by another name.
    ("function", r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$]\w*)\s*=\s*"
                 r"(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$]\w*\s*=>)"),
    # Bash: name() { — the only definition form the shell has.
    ("function", r"([A-Za-z_][\w-]*)\s*\(\)\s*\{"),
    # A named constant. Upper snake case only: lower-case assignment is a
    # variable, and reporting every one of those would bury the real contracts.
    ("constant", r"(?:export\s+)?(?:const\s+|readonly\s+|final\s+)?"
                 r"([A-Z][A-Z0-9_]{2,})\s*[:=]"),
)
COMPILED = tuple((kind, re.compile(pattern)) for kind, pattern in DEFINITION_PATTERNS)

# Names carrying no contract of their own: matching them would flood the report
# with noise from every language's boilerplate.
IGNORED_NAMES = frozenset(
    """
    if else elif for while switch case try catch except finally with return
    function class def func const let var type interface enum struct trait
    main test setUp tearDown __init__ __main__ TODO FIXME NOTE HACK XXX
    GET POST PUT PATCH DELETE HEAD OPTIONS TRUE FALSE NULL NONE EOF EOL
    IFS PATH HOME PWD OLDPWD PS1 PS2 LANG LC_ALL SHELL USER TERM
    CRITICAL HIGH MEDIUM LOW PASS FAIL WARN INFO DEBUG ERROR
    """.split()
)
# A one- or two-character name is almost always a loop variable or a false
# match, and is far too common to grep for usefully.
MIN_NAME_LENGTH = 3
# Only source files declare contracts. A prose table cell reading "MEDIUM: a
# real weakness" parses as a constant, and a report full of definitions mined
# out of Markdown is worse than no report at all.
NON_SOURCE_SUFFIXES = frozenset(
    """
    .md .markdown .rst .txt .adoc .html .csv .tsv .svg .png .jpg .gif .pdf
    .json .yaml .yml .toml .ini .cfg .lock .snap .patch .diff .min.js .map
    """.split()
)
# The report is prompt context, not an inventory. Past a few dozen contracts a
# reviewer is not reading it and the model is losing the signal in the volume.
MAX_SYMBOLS = 40
# Order the report by how likely each class of change is to break a caller.
CHANGE_RANK = {"removed": 0, "modified": 1, "added": 2}


def definitions_in(line: str) -> set[tuple[str, str]]:
    """Every (kind, name) declared on a single line of source."""
    stripped = line.strip()
    found: set[tuple[str, str]] = set()
    for kind, pattern in COMPILED:
        match = pattern.match(stripped)
        if not match:
            continue
        name = match.group(1)
        if name in IGNORED_NAMES or len(name) < MIN_NAME_LENGTH:
            continue
        found.add((kind, name))
    return found


def is_source_path(path: str) -> bool:
    """Whether a diffed path is source code worth mining for definitions."""
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return True  # extensionless: a script, most likely. Keep it.
    suffix = name[name.index(".") :].lower()
    if suffix in NON_SOURCE_SUFFIXES:
        return False
    return "." + name.rsplit(".", 1)[-1].lower() not in NON_SOURCE_SUFFIXES


def parse(diff_text: str) -> list[tuple[str, str, str]]:
    added: dict[tuple[str, str], None] = {}
    removed: dict[tuple[str, str], None] = {}
    in_source = True
    for line in diff_text.splitlines():
        # '+++ b/<path>' names the file the following hunks belong to. Track it
        # so definitions are only mined out of files that can declare one.
        if line.startswith("+++ "):
            target = line[4:].strip()
            in_source = target == "/dev/null" or is_source_path(
                target[2:] if target[:2] in ("a/", "b/") else target
            )
            continue
        # Skip the remaining headers, whose '---' would parse as content.
        if line.startswith(("---", "diff ", "index ", "@@")):
            continue
        if not in_source:
            continue
        if line.startswith("+"):
            for definition in definitions_in(line[1:]):
                added[definition] = None
        elif line.startswith("-"):
            for definition in definitions_in(line[1:]):
                removed[definition] = None

    results: list[tuple[str, str, str]] = []
    for kind, name in {**removed, **added}:
        in_added = (kind, name) in added
        in_removed = (kind, name) in removed
        if in_added and in_removed:
            change = "modified"
        elif in_removed:
            change = "removed"
        else:
            change = "added"
        results.append((kind, change, name))

    results.sort(key=lambda row: (CHANGE_RANK.get(row[1], 9), row[2].lower()))
    return results[:MAX_SYMBOLS]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: impact.py <diff-path>", file=sys.stderr)
        return 2
    try:
        diff_text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        print(f"impact.py: could not read the diff: {error}", file=sys.stderr)
        return 1
    for kind, change, name in parse(diff_text):
        print(f"{kind}\t{change}\t{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
