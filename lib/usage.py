#!/usr/bin/env python3
"""Extract the assistant's answer and the run's cost from a Copilot CLI JSONL log.

The gate runs its agents with --output-format json for one reason: text mode
reports what the model said but not what it cost, and a review that quietly
spends a developer's budget is a review they cannot make an informed decision
about. JSONL carries both on the same stream.

Two modes, deliberately separate:

  text   the assistant's answer, reconstructed as text mode would have printed
         it. This feeds the gate's own parsing, so it must be exact.
  usage  the cost of the run. This is a report line, never a gate input.

Cost is reported as nano-AIU because that is the unit the CLI emits; converting
to a currency here would be inventing precision the CLI never claimed.
"""

from __future__ import annotations

import argparse
import json
import sys

# The CLI emits several assistant messages per turn while it works. Only the
# final answer is what text mode prints, and only it carries the gate contract.
FINAL_PHASE = "final_answer"
ASSISTANT_EVENT = "assistant.message"
USAGE_EVENT = "session.usage_checkpoint"
RESULT_EVENT = "result"
NANO_PER_AIU = 1_000_000_000


def read_events(path: str) -> list[dict]:
    events = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            # The CLI prefixes warnings and other chatter on stdout; anything
            # that is not a JSON object simply is not an event.
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def extract_text(events: list[dict]) -> str:
    """The answer, as text mode would have printed it.

    Falls back to every assistant message when none is flagged final: a model
    that never emits a final_answer phase has still said something, and an empty
    result here would be read as a malformed report rather than as a parse bug.
    """
    final, every = [], []
    for event in events:
        if event.get("type") != ASSISTANT_EVENT:
            continue
        data = event.get("data") or {}
        content = data.get("content")
        if not isinstance(content, str) or not content:
            continue
        every.append(content)
        if data.get("phase") == FINAL_PHASE:
            final.append(content)
    return "\n".join(final or every)


def extract_usage(events: list[dict]) -> tuple[int, int]:
    """Total nano-AIU and premium requests for the run.

    Checkpoints are cumulative within a session, so the last one is the total --
    summing them would count every earlier checkpoint again.
    """
    nano = premium = 0
    for event in events:
        kind = event.get("type")
        if kind == USAGE_EVENT:
            data = event.get("data") or {}
            nano = max(nano, int(data.get("totalNanoAiu") or 0))
            premium = max(premium, int(data.get("totalPremiumRequests") or 0))
        elif kind == RESULT_EVENT:
            usage = event.get("usage") or {}
            premium = max(premium, int(usage.get("premiumRequests") or 0))
    return nano, premium


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--mode", choices=("text", "usage"), required=True)
    args = parser.parse_args()

    try:
        events = read_events(args.log)
    except OSError:
        return 1

    if args.mode == "text":
        sys.stdout.write(extract_text(events))
        return 0

    nano, premium = extract_usage(events)
    print(f"{nano}\t{premium}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
