#!/usr/bin/env python3
"""Render one saved inhousecode finding with a focused source excerpt."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

HEADING = re.compile(
    r"^## \[(?P<number>\d+)] (?P<severity>[A-Z]+) - "
    r"(?P<location>.+:\d+) - (?P<category>.+)$"
)
RED_HIGHLIGHT = "\x1b[1;97;41m"
RESET = "\x1b[0m"


def select_finding(briefing: str, number: int) -> str:
    """Return one numbered Markdown section from the saved briefing."""
    lines = briefing.splitlines()
    start = None
    for index, line in enumerate(lines):
        match = HEADING.match(line)
        if match and int(match.group("number")) == number:
            start = index
            break
    if start is None:
        raise ValueError(f"finding {number} is not available in the last review")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index] == "---" or HEADING.match(lines[index]):
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def render_finding(briefing: str, number: int, *, color: bool) -> str:
    """Render a focused finding; highlight the exact source line."""
    section = select_finding(briefing, number)
    lines = section.splitlines()
    heading = HEADING.match(lines[0])
    if not heading:
        raise ValueError(f"finding {number} has a malformed heading")

    output = [
        f"[{number}] {heading.group('severity')} — {heading.group('location')}",
        f"Category: {heading.group('category')}",
        "",
    ]
    in_code = False
    source_started = False
    for line in lines[1:]:
        if line.startswith("Source, "):
            output.extend([line.replace("`", ""), ""])
            source_started = True
            continue
        if line == "```text":
            in_code = True
            continue
        if line == "```":
            in_code = False
            continue
        if in_code:
            if line.startswith(">"):
                marked = f"{RED_HIGHLIGHT}{line}{RESET}" if color else f"🔴 {line}"
                output.append(marked)
            else:
                output.append(f"   {line}")
            continue
        if line.startswith("- "):
            output.append(line[2:].replace("`", ""))
        elif line.strip() and not source_started:
            output.append(line.replace("`", ""))

    return "\n".join(output).rstrip() + "\n"


def render_findings(briefing: str, *, color: bool) -> str:
    """Render every saved finding in its stable review order."""
    numbers = [
        int(match.group("number"))
        for line in briefing.splitlines()
        if (match := HEADING.match(line))
    ]
    if not numbers:
        raise ValueError("no findings are available in the last review")
    return "\n".join(
        render_finding(briefing, number, color=color).rstrip()
        for number in numbers
    ) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--briefing", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--finding", type=int)
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        briefing = Path(args.briefing).read_text(encoding="utf-8", errors="replace")
        use_color = args.color == "always" or (
            args.color == "auto" and sys.stdout.isatty() and "NO_COLOR" not in os.environ
        )
        rendered = (
            render_findings(briefing, color=use_color)
            if args.all
            else render_finding(briefing, args.finding, color=use_color)
        )
        sys.stdout.write(rendered)
    except (OSError, ValueError) as error:
        print(f"inhousecode show: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
