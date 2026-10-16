#!/usr/bin/env python3
"""Extract the assistant's answer and the run's cost from an agent CLI log.

The gate runs its agents with a JSON output mode for one reason: text mode
reports what the model said but not what it cost, and a review that quietly
spends a developer's budget is a review they cannot make an informed decision
about. JSON carries both on the same stream.

Two harness shapes are supported, auto-detected per event:

  Copilot CLI    JSONL: one streaming event per line. The final answer is the
                 assistant.message event flagged phase=final_answer. Cost is
                 reported as nano-AIU on a session.usage_checkpoint event.
  Claude Code /
  Hermes CLI     A single JSON object of type "result", carrying the answer
                 in "result" and cost in USD under "total_cost_usd".
  Codex CLI      JSONL whose completed agent_message item carries the final
                 answer. Codex reports tokens, not a price; cost stays unknown.

Two modes, deliberately separate:

  text   the assistant's answer, reconstructed as text mode would have printed
         it. This feeds the gate's own parsing, so it must be exact.
  usage  the cost of the run. This is a report line, never a gate input.

Cost is reported in whatever unit the CLI emitted -- nano-AIU for Copilot,
USD for Claude Code and Hermes -- because converting between them here would
be inventing an exchange rate the CLI never claimed.
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
CODEX_ITEM_EVENT = "item.completed"
CODEX_AGENT_MESSAGE = "agent_message"
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

    Claude Code and Hermes emit a single "result" event instead of a stream of
    assistant.message events; its "result" field IS the final answer.
    """
    final, every = [], []
    for event in events:
        kind = event.get("type")
        if kind == CODEX_ITEM_EVENT:
            item = event.get("item") or {}
            content = item.get("text")
            if item.get("type") == CODEX_AGENT_MESSAGE and isinstance(content, str) and content:
                final.append(content)
            continue
        if kind == RESULT_EVENT:
            result = event.get("result")
            if isinstance(result, str) and result:
                final.append(result)
            continue
        if kind != ASSISTANT_EVENT:
            continue
        data = event.get("data") or {}
        content = data.get("content")
        if not isinstance(content, str) or not content:
            continue
        every.append(content)
        if data.get("phase") == FINAL_PHASE:
            final.append(content)
    return "\n".join(final or every)

def extract_usage(events: list[dict]) -> tuple[int, int, float]:
    """Total nano-AIU, premium requests, and USD cost for the run.

    Checkpoints are cumulative within a session, so the last one is the total --
    summing them would count every earlier checkpoint again. nano and usd are
    mutually exclusive in practice (one harness reports one or the other); both
    are returned so the caller can print whichever is non-zero without having
    to know which harness produced the log.
    """
    nano = premium = 0
    usd = 0.0
    for event in events:
        kind = event.get("type")
        if kind == USAGE_EVENT:
            data = event.get("data") or {}
            nano = max(nano, int(data.get("totalNanoAiu") or 0))
            premium = max(premium, int(data.get("totalPremiumRequests") or 0))
        elif kind == RESULT_EVENT:
            usage = event.get("usage") or {}
            premium = max(premium, int(usage.get("premiumRequests") or 0))
            try:
                usd = max(usd, float(event.get("total_cost_usd") or 0.0))
            except (TypeError, ValueError):
                pass
    return nano, premium, usd

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

    nano, premium, usd = extract_usage(events)
    print(f"{nano}\t{premium}\t{usd}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
