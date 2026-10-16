# AGENTS.md — inhousecode
Governed memory lives only in OpenViking, under the canonical namespace:

```text
viking://resources/inhousecode/memory-policy/
├── _schema/                 Memory types, required fields, statuses
├── global/                  Approved knowledge shared across all repositories
├── projects/<repository-id>/   Approved knowledge scoped to one repository
└── candidate_memory/
    ├── inbox/               Unclassified feedback, pending triage
    ├── classified/          Scoped and confidence-rated, pending promotion
    └── quarantine/          Unrelated or prompt-injection-like content
```

There is no repository-local memory store. `.inhousecode/` holds configuration
and transient cache only — never memory records. If OpenViking is
unavailable, memory operations fail clearly; they never fall back to a local
store.

## What this is

A two-phase review gate for AI-generated code: deterministic Semgrep analysis
with a bounded repair loop, then an AI code review against governed
project/global knowledge stored in OpenViking. Triggered from a git
pre-commit hook, the Copilot CLI `agentStop` hook, or an explicit
`inhousecode review` call from Hermes or Codex.

Read [README.md](README.md) for the reasoning and
[docs/architecture.md](docs/architecture.md) for the pipeline.

## Layout

| Path | Purpose |
|---|---|
| `bin/inhousecode` | CLI entry point: target resolution, orchestration, verdict |
| `lib/` | Gate implementations and shared helpers |
| `lib/pr.sh` | Pull-request resolution via `gh` / `az`, with a pull-ref fallback |
| `lib/usage.py` | Reads the agent's answer and the run's cost from the CLI's JSONL |
| `lib/impact.{py,sh}` | Blast radius: what the change declares, and who depends on it |
| `lib/memory_policy.py`, `lib/memory.sh` | OpenViking-only governed memory: candidates, promotion, retrieval |
| `lib/finding_view.py` | Renders numbered findings with source excerpts and highlighting |
| `lib/integrations.py` | Installs/updates/removes the managed Hermes and Codex Agent Skills |
| `hooks/` | Trigger handlers (git pre-commit shim, Copilot `agentStop`) |
| `skills/code-review/` | The reviewer skill: `SKILL.md` + `references/` |
| `skills/inhousecode/` | The thin harness adapter skill shipped to Hermes and Codex |
| `config/` | Default configuration and its JSON schema |
| `docs/` | Architecture, configuration, team customization |

## Invariants

Break any of these and the tool is unsound:

1. **A malformed gate report is `unavailable`, never a pass.** `validate_gate_output`
   is the only thing standing between a crashed scanner and a waved-through commit.
2. **The review agent never gets write access.** It judges the tree; it must not
   be able to modify it, and it runs with `--no-custom-instructions` so reviewed
   code cannot rewrite the reviewer's brief.
3. **Fixer agents never stage, commit, or push.** The only exception is the
   deliberate re-staging of *already staged* paths in `static_restage`.
4. **Every repair loop is bounded and stops on no progress.** Each round costs a
   model invocation.
5. **The `agentStop` hook fails open.** Any error exits 0. A broken hook must
   never trap a user inside a session.
6. **Staged mode scans the index, not the working tree.** Files are materialized
   from git blobs into an isolated directory. `--diff` and `--pr` do the same
   from the reviewed commit, are report-only unless `--fix` is passed or
   `review.fixByDefault` is enabled, and never repair when that commit is not
   the one checked out. Explicit `--no-fix` always wins.
7. **Non-blocking findings need an explicit repair opt-in.** The opt-in is a
   typed picker selection, `--fix`, or `review.fixByDefault: true`. The picker
   applies only the numbers the developer typed. Findings are numbered once per
   run, in one table, so the number on screen is the number you may type.
8. **Any fix is followed by a re-review before the verdict stands.** This holds
   for automatic repair, hand-picked fixes, and explain sessions alike. A fix
   edits the tree, so an un-re-reviewed verdict describes code that no longer
   exists — a `PASS` carrying edits no gate ever saw. A blocked run stays
   blocked; a passing run is downgraded only if the tree actually moved.
9. **Optional review inputs never block, and never bluff.** A missing PR
   description or an unbuildable blast-radius map drops that section from the
   prompt and the review continues. They are evidence, not gates. Equally, the
   reviewer must never claim to have checked what it was not given.
10. **Only findings carry severity.** Intent-checklist lines are reported in
    their own table and are never numbered with findings — invariant 7 requires
    the number on screen to be the number you may type, and one table owns
    those. An actionable claim gap becomes a finding in its own right.
11. **The second opinion only ever subtracts.** The critique model may drop or
    downgrade a finding; it may never add one or raise a severity, because a
    finding it invented would reach the developer critiqued by nobody. It drops
    only what it read and disproved — an unopenable file leaves the finding
    confirmed — and a critique that fails, times out, or comes back malformed
    keeps the drafts it was judging. Every one of these closes the same
    direction: a check that failed must not empty the report into a pass.
12. **Cost is reported, never estimated, and never gates anything.** The figures
    come from the CLI's own usage events; a number this tool guessed at would be
    worse than none, because it would be believed. A run whose cost cannot be
    read says so and prints the rest — being unable to price a review is not a
    reason to block a commit.

## Conventions

- Bash for orchestration, Python 3 for anything parsing JSON. No other runtime.
- Keep code and documentation simple, clear, and easy to read.
- Magic values are named constants grouped at the top of the file.
- Keep `config/review.config.schema.json` in sync with
  `config/review.config.default.json` and with `INTEGER_BOUNDS` in `lib/config.py`.
- Adding a config key means touching all three, plus `docs/configuration.md`.
- Shell variables derived from config are `INHOUSECODE_<SECTION>_<KEY>` in upper
  snake case, generated by `lib/config.py`.
- Guidance given to *every* code-touching agent lives in `craft_standard()` in
  `lib/copilot.sh` and nowhere else. Add it there, not to an individual prompt:
  two copies of a standard are two standards.
