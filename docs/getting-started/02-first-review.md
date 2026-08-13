# 2. Run your first review

No hooks yet. No commit gets blocked by anything in this page — the goal is
just to see the tool run once, on purpose, so the first time it fires
automatically isn't also the first time you've seen its output.

## Set up the repo

In the repository you want reviewed:

```bash
inhousecode init
```

This creates `.inhousecode/` with two things:

- `config.json` — the tool's settings for this repo (defaults are sane; see
  [docs/configuration.md](../configuration.md) when you want to change one)
- `developer-rulebook.md` — empty for now. That's page 3.

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

1. **Static** — Semgrep scans, and if it finds something fixable, a bounded
   repair loop fixes it and re-scans before reporting.
2. **AI review** — reads your diff (and your rulebook, which is empty right
   now, so this pass has nothing team-specific to check yet) and reports
   findings with a suggested fix for each.

You'll end with a verdict — pass, or a list of findings split into
"fixed automatically" and "here's what we found, your call."

## Try the other targets

```bash
inhousecode review                   # staged changes only
inhousecode review --diff main       # everything this branch adds over main
inhousecode review --mode static     # skip the AI phase, just Semgrep
```

## Next

Right now the AI phase is checking your code against nothing but general
judgment — it has no idea what *your* team cares about. That's what the
rulebook fixes: [Write your first rule](03-first-rule.md).
