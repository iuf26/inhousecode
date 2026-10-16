# 2. Run your first review

No hooks yet. No commit gets blocked by anything in this page — the goal is
just to see the tool run once, on purpose, so the first time it fires
automatically isn't also the first time you've seen its output.

## Set up the repo

In the repository you want reviewed:

```bash
inhousecode init
```

This creates `.inhousecode/config.json` (see
[docs/configuration.md](../configuration.md)) and initializes the shared
OpenViking namespace. No memory is stored in the repository.

Optionally, let an agent propose a first set of repository knowledge:

```bash
inhousecode discover
```

It reads your manifest, linter/CI config, and existing docs, then writes a
handful of evidence-backed **candidates** — unverified until promoted. Run
`inhousecode discover --gate` to see proposals without writing anything.

## Make a small change

Edit something — anything. A real change is more useful than a placeholder
one, because you'll see what the output actually looks like against real
code.

## Review it

```bash
inhousecode review --worktree
```

`--worktree` reviews everything currently uncommitted, staged or not — the
easiest target for a first look. You'll see two phases run in order:

1. **Static** — Semgrep scans. It repairs and re-scans when static autofix,
   `--fix`, or `review.fixByDefault` enables the bounded loop.
2. **AI review** — reads your diff plus a frozen snapshot of approved
   OpenViking knowledge (likely empty right now) and reports findings with a
   suggested fix for each.

You'll end with a verdict — pass, or a list of findings split into
"fixed automatically" and "here's what we found, your call."

For a report-only first look, add `--no-fix`. To repair every static and AI
finding once, add `--fix`. Later, set `review.fixByDefault: true` in
`.inhousecode/config.json` if that should be the repository's normal behavior.

## Try the other targets

```bash
inhousecode review                   # staged changes only
inhousecode review --diff main       # everything this branch adds over main
inhousecode review --mode static     # skip the AI phase, just Semgrep
```

## Next

Right now the AI phase has only general judgment. Teach it what *your* team
cares about: [Add your first piece of team knowledge](03-first-rule.md).
