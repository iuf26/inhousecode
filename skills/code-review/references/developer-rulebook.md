# Team rulebook

> **This file belongs to the team, not to the agent.** Add, edit, or delete
> bullets freely. The reviewer re-reads it on **every** review and checks each
> active guideline against the code under review. There is no run where these
> are skipped, and the reviewer never edits this file.
>
> This is the **authoritative** source for concrete, citable rules. When a rule
> here overlaps the review checklist, this file wins.

## Contents

- [Why this file exists](#why-this-file-exists)
- [How the reviewer uses it](#how-the-reviewer-uses-it)
- [How to write a rule](#how-to-write-a-rule)
- [Active guidelines](#active-guidelines)

## Why this file exists

Every team has rules that live nowhere: in a senior engineer's head, in review
comments repeated for the fifth time, in a mistake that cost a weekend once.
A general-purpose reviewer cannot know any of them.

This is where they go. A rule written here is applied to every change, forever,
without anyone having to remember it.

## How the reviewer uses it

For every guideline below, the reviewer checks whether the reviewed code honors
it.

- A violation is a **HIGH** (blocking) finding, unless the rule is marked
  **(advisory)** — those are reported but do not block.
- Style, formatting, and house-convention rules are **never** HIGH. They cap at
  **MEDIUM**, even without the advisory marker. Nothing about formatting should
  ever block a commit.
- Each finding is cited by the rule's `id`.

## How to write a rule

Add a rule when a review comment is **general and repeatable** — something you
would want flagged on *any* future change, not a one-off. Good candidates: a
convention you keep re-explaining, a bug class that bit you before, a house
style that genuinely matters.

One line per rule:

```
- [ ] id (scope) — the rule
```

- **`id`** — short, kebab-case, unique. The reviewer cites it verbatim, so make
  it self-explanatory (`prefer-pathlib`, not `rule12`).
- **`scope`** — where it applies: `all`, or an area like `python`, `bash`,
  `scripts`, `tests`, `sql`, `frontend`. The reviewer applies it only to
  matching files.
- **`the rule`** — one imperative, checkable sentence. State what MUST hold.
  Add `(advisory)` after the scope to make it non-blocking.

Keep rules **specific and testable**. "Write clean code" is not a rule;
"functions do one thing; split long or multi-purpose functions" is.

Examples:

```
- [ ] prefer-pathlib (python) — use pathlib.Path for filesystem paths, not os.path
- [ ] no-print-logging (python) — use the logging module, not print(), in library code
- [ ] pin-versions (scripts) — pin dependency versions; do not install from latest
- [ ] tenant-scoped-queries (sql) — every query filters by tenant_id
- [ ] docstring-public-fns (python, advisory) — public functions have a short docstring
```

Delete a rule by deleting its line.

## Active guidelines

- [ ] constants-at-top (scripts, advisory) — magic values are named constants grouped near the top
- [ ] no-duplication (all, advisory) — reuse existing helpers instead of copy-pasting logic
- [ ] no-perf-regression (all) — do not degrade application-level performance; avoid adding blocking I/O, N+1 calls, repeated scans, or unbounded allocation on existing hot paths
- [ ] single-constant-definition (all) — define each constant exactly once; never redeclare the same constant value or name in a second place
- [ ] no-security-regression (all) — introduce no new security weakness: no injection, path traversal, unsafe deserialization, weakened authn/authz, or leaked credentials in logs
- [ ] manifest-processing-performance (all) — code that processes high-volume manifest services must stream or batch, reuse parsed state, and stay linear in manifest count; no per-manifest re-parsing, re-reading, or per-item network calls

<!-- Add your team's rules below this line. -->
