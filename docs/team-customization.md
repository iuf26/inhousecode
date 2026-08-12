# Making it your team's reviewer

A general-purpose reviewer catches general-purpose problems. The reason your
senior engineers are valuable in review is that they know things this repository
never wrote down.

There are three places to write those things down.

## 1. The team rulebook — start here

`.inhousecode/developer-rulebook.md`, created by `inhousecode init`. Plain
markdown, owned by the team, re-read on **every** review. The agent never edits
it.

One line per rule:

```
- [ ] id (scope) — the rule
```

| Part | What it is |
|---|---|
| `id` | Short, kebab-case, unique. The reviewer cites it verbatim, so `prefer-pathlib` beats `rule12`. |
| `scope` | `all`, or an area: `python`, `bash`, `sql`, `tests`, `frontend`. Applied only to matching files. |
| the rule | One imperative, checkable sentence. Add `(advisory)` to make it non-blocking. |

```
- [ ] tenant-scoped-queries (sql) — every query filters by tenant_id
- [ ] no-print-logging (python) — use the logging module, not print(), in library code
- [ ] pin-versions (scripts) — pin dependency versions; do not install from latest
- [ ] docstring-public-fns (python, advisory) — public functions have a short docstring
```

### What belongs here

A rule earns its place when it is **general and repeatable** — something you'd
want flagged on *any* future change.

Good sources, in order of value:

1. **A review comment you have written more than twice.** That is the definition
   of a rule.
2. **A postmortem.** Whatever caused the incident, write the rule that would have
   caught it.
3. **Tribal knowledge.** "Never call that service synchronously." "This module is
   load-bearing; changes need a test." Things a new hire learns by breaking them.
4. **A house convention that genuinely matters.** Not formatting — a formatter
   handles that, and formatting never blocks a commit here.

### What doesn't

- Anything a linter or formatter already enforces. Wasted tokens.
- Vague aspirations. "Write clean code" is unfalsifiable, so the reviewer will
  either ignore it or invent violations of it.
- Anything Semgrep catches. Phase 1 already ran.

### Severity, honestly

A violated rule is **HIGH** and blocks, unless marked `(advisory)`. Style and
convention rules cap at **MEDIUM** regardless.

Be conservative. Every rule you mark blocking is a commit someone can't make. A
gate that blocks on taste gets uninstalled, and an uninstalled gate reviews
nothing.

Start advisory. Promote a rule to blocking once you've seen it fire correctly a
few times.

## 2. Repository context — `AGENTS.md`

The reviewer reads your repository's `AGENTS.md` (or `CLAUDE.md` /
`.github/copilot-instructions.md`) for context: what this repo is, what the
domain means, which directories are generated, what "done" looks like here.

The rulebook says what must hold. `AGENTS.md` says what the code *is*. A reviewer
with both stops reporting deliberate design decisions as defects.

## 3. Semgrep packs

`static.semgrepConfigs` controls Phase 1. The defaults are security-focused.
Teams with a shared internal ruleset can point at their own packs.

Only list packs that exist in the registry — a `--config` that 404s makes Semgrep
exit non-zero and the whole scan is discarded and reported as unavailable.

## Rolling it out

1. **Ship it read-only.** `static.autofix: false`, `ai.autofixBlocking: false`.
   Let the team see findings for a week without anything changing under them.
2. **Collect the disagreements.** Every "that's wrong" is either a bad rule or a
   missing piece of context. Both are fixable, and both make the next week
   quieter.
3. **Turn on static repair.** Deterministic findings, deterministic fixes. This
   is where the time savings show up first.
4. **Turn on blocking review repair.** By now the rulebook reflects the team and
   the false-positive rate is low enough to trust.
5. **Then consider agent-stop.** Once people trust the gate at commit time, move
   it earlier — to the moment the code is generated.

Do not start at step 5. A gate that interrupts every agent turn before the team
believes in it is a gate that gets deleted.

## Sharing across repositories

Commit `.inhousecode/config.json` and `.inhousecode/developer-rulebook.md`.
They belong in version control; that is the point.

For an organization-wide baseline, keep the rulebook in one repository and either
vendor it in, or point `rulebook` at a path your build populates. Teams then
append their own rules below the shared block.

`.inhousecode/cache/` is scratch space and is git-ignored by `init`.
