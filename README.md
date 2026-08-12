# inhousecode

**A two-phase review gate for code you didn't type.**

Deterministic static analysis first, then an AI reviewer that reads your team's
own rulebook. Runs before you commit, or the moment your agent stops generating.

```
┌── Phase 1 ─────────────────┐   ┌── Phase 2 ─────────────────────┐
│  Semgrep                   │   │  AI code review                │
│  deterministic, no opinion │──▶│  understands intent            │
│  repair loop, up to 20x    │   │  then every finding, your call │
└────────────────────────────┘   └────────────────────────────────┘
```

---

## Why this exists

Most code is now written by an agent. That broke two assumptions review was
built on.

**1. Volume outran attention.** A 900-line diff that took forty seconds to
generate takes forty minutes to read. Nobody reads it. They skim it, see that it
looks like code they would have written, and approve. Review became a formality
exactly when the code needed it most.

**2. The reviewer is the same kind of thing as the author.** Teams now review AI
code with AI. That is fine — but if the only check is "ask a model if this looks
okay", you have a single point of judgment with no floor under it. A model that
hallucinated the code can hallucinate the approval.

inhousecode is built around three positions on that.

### A deterministic floor comes first

Before any model gives an opinion, Semgrep runs. It has no context window, no
temperature, and no desire to be agreeable. It finds injection, unsafe
deserialization, path traversal, weak crypto, hard-coded credentials — the class
of bug that is objectively detectable and that generated code reproduces
constantly, because it learned from code that had it.

Whatever else happens, that floor holds. The AI phase only runs on code that
already cleared it.

### Findings are useless; fixes are the product

A gate that prints twelve problems and stops has moved work, not removed it.

So Phase 1 doesn't just report — it loops. Findings go to a fixer agent with an
explicit brief to fix the *cause*, not to silence the check. Then it re-scans.
Then it does it again, up to 20 rounds, stopping early the moment a round stops
making progress. You come back to clean code and a summary, not a list.

### Severity decides who's in charge

Not every finding deserves the same authority.

| | Handled by | Why |
|---|---|---|
| **CRITICAL / HIGH** | fixed automatically, then re-reviewed | These are not opinions. A SQL injection is not a matter of taste, and asking you to approve fixing it wastes your attention. |
| **MEDIUM / LOW** | listed and numbered — **you pick** | These *are* opinions. An agent that silently restructures your code because it prefers a different shape is not reviewing, it's editing. |

That line matters more than it looks. Gates that block on opinions get disabled,
and a disabled gate reviews nothing.

### Blocking without explaining is just friction

A verdict tells you *what*. It rarely tells you *why*, and "why" is the whole
value of a review to the person who hasn't seen that mistake before.

So a blocked commit offers a third option next to override and abort:

```
  [d] show raw gate output   [e] explain these findings in Copilot
  [o] override and continue  [a] abort
```

`[e]` opens an interactive session that starts by explaining every finding — in
plain language, one sentence per field, with the team rule it violates quoted
verbatim and the offending lines shown. Then it **stops and asks you** what you
want to do. Explaining and fixing are separate acts; an agent that starts
rewriting your branch while you're still reading is not helping.

The explanation is assembled from a **briefing file built without a model** —
your findings, your rulebook, your source. If the Copilot CLI isn't installed,
you still get the briefing.

### Your team's knowledge has somewhere to live

A general reviewer doesn't know that your queries must filter by `tenant_id`, or
that this service can't take a new dependency, or that the last person who used
`except Exception` there cost you a weekend.

`.inhousecode/developer-rulebook.md` is a plain markdown file your team owns.
One line per rule. The reviewer re-reads it on every single run and cites rules
by name. It is the difference between a generic reviewer and *your* reviewer.

```markdown
- [ ] tenant-scoped-queries (sql) — every query filters by tenant_id
- [ ] no-print-logging (python) — use logging, not print(), in library code
```

---

## Two triggers — pick either, or both

### Pre-commit (default)

The classic gate. You `git commit`, the phases run against your staged changes,
and you don't commit until it's clean or you deliberately override.

### Agent-stop (post-generation)

This one is new, and it is the better fit for how people actually work.

Copilot CLI fires an `agentStop` hook when the agent finishes a turn — and that
hook can **refuse to let the turn end**. inhousecode scans what was just
written and, if there's a problem, hands the findings straight back to the *same
agent*, with its full context still loaded.

The agent fixes its own output before you ever see it. No second model is
spawned, no diff has to be re-explained, and the feedback arrives while the work
is still warm. Bounded to 20 turns per session so it can never loop forever.

> Agent-stop runs the static phase by default — it's fast, cheap, and fires many
> times per session. Enable the AI phase there too if you want it
> (`agentStop.ai: true`).

---

## Install

```bash
git clone <this-repo> inhousecode && cd inhousecode
bash install.sh --with-semgrep          # macOS / Linux / Git Bash
```

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -WithSemgrep   # Windows
```

Then, in each repository you want reviewed:

```bash
inhousecode init            # creates .inhousecode/ (config + team rulebook)
inhousecode install-hooks   # installs your configured trigger(s)
inhousecode doctor          # verify everything resolves
```

The installer writes a launcher that points back at your checkout — `git pull`
is the entire upgrade path. `install-hooks` is covered in detail
[below](#installing-the-pre-commit-hook); removal is under
[Uninstall](#uninstall).

**Requirements:** git, Python 3, [Semgrep](https://semgrep.dev),
[Copilot CLI](https://github.com/github/copilot-cli), GNU `timeout`. On Windows,
Git Bash. `inhousecode doctor` tells you what's missing.

### Installing the pre-commit hook

`install-hooks` with no arguments installs whatever `triggers` in
`.inhousecode/config.json` asks for — `preCommit: true` and
`agentStop: false` by default. Name a trigger explicitly to override that:

```bash
inhousecode install-hooks --pre-commit    # just the git hook
inhousecode install-hooks --agent-stop    # just the Copilot CLI hook
inhousecode install-hooks --pre-commit --agent-stop
```

The pre-commit install does two things:

1. writes an executable shim to **`.githooks/pre-commit`**, and
2. sets **`git config core.hooksPath .githooks`** for this clone.

The shim is three lines and holds no logic — it execs the tool:

```bash
#!/usr/bin/env bash
# Installed by inhousecode. Edit the tool, not this shim.
exec "/path/to/inhousecode/bin/inhousecode" review --staged "$@"
```

That indirection is the point: the installed checkout stays the single source of
truth, so upgrading inhousecode never means reinstalling hooks in every repo.

Verify it took:

```bash
git config core.hooksPath        # expect: .githooks
inhousecode doctor             # under "Installed triggers": pre-commit installed
```

From here, `git commit` runs both phases against your **staged** changes. To get
through once without the gate, `git commit --no-verify`.

> **Don't commit `.githooks/pre-commit`.** The shim contains an absolute path to
> *your* checkout, so it is meaningless on a teammate's machine — and the review
> will flag it as a machine-specific path, in your own diff, on every commit.
> `init` does not ignore it for you:
>
> ```bash
> echo '.githooks/' >> .gitignore
> ```
>
> Each developer runs `install-hooks` in their own clone. That is by design:
> `core.hooksPath` is local config and cannot be set for someone else anyway.

> **`core.hooksPath` replaces `.git/hooks/` entirely.** Git stops reading that
> directory once the path is redirected, so any pre-existing hooks there go
> silent. If your repo already has hooks, move them into `.githooks/` before
> installing, or call them from the shim.

---

## Uninstall

### From one repository

```bash
inhousecode uninstall-hooks
```

That removes the pre-commit shim and the agent-stop hook, and unsets
`core.hooksPath` if `.githooks/` ends up empty. It only deletes shims carrying
inhousecode's marker comment, so a hand-written `.githooks/pre-commit` is left
alone.

It deliberately leaves your **`.inhousecode/`** directory — that holds your
team's rulebook and config, which are worth more than the tool. Delete it
yourself if you really mean it:

```bash
rm -rf .inhousecode
```

`init` also appended `.inhousecode/cache/` to your `.gitignore`; remove that
line by hand if you want no trace.

### From your machine

**Do the repositories first.** The shim holds an absolute path, so deleting the
checkout while hooks are still installed leaves a hook that cannot execute — and
git treats that as a *failed* hook, not a missing one:

```
.githooks/pre-commit: line 3: .../bin/inhousecode: No such file or directory
```

The commit is rejected. Every repo you installed into stops accepting commits,
and the error names a path that no longer exists — a confusing thing to debug
months later. To list the repos still holding a shim:

```bash
find ~ -name pre-commit -path '*/.githooks/*' \
  -exec grep -l 'Installed by inhousecode' {} + 2>/dev/null
```

That matches only inhousecode's own shims, so hand-written hooks in the same
location are not reported. Run `inhousecode uninstall-hooks` in each one.

Then remove the tool. There is no `install.sh --uninstall`, because the
installer only writes a single launcher:

```bash
rm -f ~/.local/bin/inhousecode        # macOS / Linux / Git Bash
rm -rf /path/to/inhousecode           # the checkout itself
```

```powershell
Remove-Item "$env:LOCALAPPDATA\inhousecode" -Recurse -Force   # Windows launcher
Remove-Item C:\path\to\inhousecode -Recurse -Force            # the checkout
```

On Windows the installer also added its bin directory to your **user PATH**.
Deleting the folder does not remove that entry:

```powershell
$bin  = "$env:LOCALAPPDATA\inhousecode\bin"
$path = [Environment]::GetEnvironmentVariable('Path','User')
$new  = ($path -split ';' | Where-Object { $_ -and $_ -ne $bin }) -join ';'
[Environment]::SetEnvironmentVariable('Path', $new, 'User')
```

Semgrep and Copilot CLI are ordinary tools installed separately; remove them
only if nothing else uses them (`pip uninstall semgrep`).

### If you deleted the checkout first

You do not need to reinstall anything to escape. In each affected repo:

```bash
git config --unset core.hooksPath && rm -rf .githooks
```

Commits work again immediately.

---

## Use

```bash
inhousecode review                   # staged changes (what pre-commit runs)
inhousecode review --pr 1234         # review a pull request by number
inhousecode review --worktree        # everything uncommitted
inhousecode review --diff main       # commits this branch adds on top of main
inhousecode review --path src/api    # a whole folder or file
inhousecode review --mode static     # skip the AI phase
inhousecode review --no-fix          # report only, touch nothing
inhousecode review --gate            # non-interactive; exit code is the verdict
inhousecode explain                  # session over the last run's findings
```

Exit codes: `0` pass or override, `1` blocked, `2` usage error.

Bypass every hook once with `git commit --no-verify`.

### Reviewing someone else's pull request

The pull-request number is the only input:

```bash
inhousecode review --pr 1234
```

inhousecode asks the forge — GitHub via `gh`, Azure DevOps via `az` — which
branch the PR targets and which commit it proposes, fetches that commit, and
reviews it. You do **not** have to know the base branch, check the branch out,
or even be on the right branch: the reviewed files are read from the PR's own
commit, so your working tree is left completely alone.

A full PR URL works too, and so does reviewing a PR in a repository you have
only just cloned:

```bash
inhousecode review --pr https://github.com/org/repo/pull/1234
inhousecode review --pr 1234 --gate      # exit code is the verdict, for CI
```

Scoping is against the *merge base*, so commits that landed on the base branch
after the PR was opened are never blamed on its author. The branch's commit
messages are handed to the reviewer as context, so it can flag code that does
not do what its own commits claim.

If the PR's commit is already in your clone — you have the branch checked out,
or fetched it earlier — inhousecode uses that object instead of downloading it
again, so a local review is fast and works offline.

### Fixing a PR branch you have checked out

Because the branch is usually someone else's, a PR review is **report-only** by
default: both repair loops and the finding picker are off. When the branch is
yours, check it out and opt in:

```bash
git switch feature/my-branch
inhousecode review --pr 1234 --fix
```

Repairs are only ever possible when the reviewed commit is the one you have
checked out — a fixer edits the working tree, and editing it against a commit
you are not on would scatter changes over unrelated code. inhousecode checks
this and disables repairs (with a warning) rather than guessing.

With `--fix`, fixes are written to your **working tree** of the checked-out
branch. Nothing is staged, committed, or pushed — you read the diff and commit
it yourself. Each repair round re-reads the working tree, so the loop sees its
own progress and stops as soon as it stops making any, within the
`maxFixLoops` / `fixSeverity` budgets in your configuration.

If you have no forge access — or the PR has not been opened yet — name the base
branch directly instead:

```bash
inhousecode review --diff main
```

**Requires** `gh` (GitHub) or `az` with the `azure-devops` extension (Azure
DevOps), authenticated. Without one, inhousecode falls back to fetching
`refs/pull/<id>/head` and assumes the PR targets the remote's default branch —
and says so.

---

## Configure

`.inhousecode/config.json`, created by `inhousecode init`:

```json
{
  "triggers": { "preCommit": true, "agentStop": false },
  "static": {
    "enabled": true,
    "autofix": true,
    "maxFixLoops": 20,
    "fixSeverity": "all",
    "restageFixes": true,
    "semgrepConfigs": ["p/security-audit", "p/owasp-top-ten", "p/cwe-top-25"]
  },
  "ai": {
    "enabled": true,
    "model": "",
    "timeoutSec": 600,
    "autofixBlocking": true,
    "maxFixLoops": 3,
    "triageFindings": true
  },
  "agentStop": { "static": true, "ai": false, "maxTurns": 20 },
  "rulebook": ".inhousecode/developer-rulebook.md"
}
```

Unknown keys are a hard error, so a typo never silently disables a gate. Full
reference: [docs/configuration.md](docs/configuration.md).

---

## How it works

| | |
|---|---|
| [docs/architecture.md](docs/architecture.md) | The pipeline, the finding contract, the trust boundaries |
| [docs/configuration.md](docs/configuration.md) | Every option, and what it costs you |
| [docs/team-customization.md](docs/team-customization.md) | Making it *your team's* reviewer |
| [docs/testing.md](docs/testing.md) | Step-by-step manual acceptance path |

The short version: both phases emit the same tab-separated finding contract and
a single verdict line, so the orchestrator treats a scanner and a model
identically. A malformed report is an **unavailable** gate, never a pass —
neither a crashed scanner nor a confused model can wave a commit through.

The reviewer is a [Copilot skill](skills/code-review/SKILL.md) invoked read-only:
it can read your code, and it cannot write to the tree it is judging. Fixing is a
separate, write-enabled invocation that only ever receives findings a gate
already produced. Instructions found *inside* reviewed code are treated as
input, not as direction. The `[e]` explain session is a third shape again —
interactive, yours, and pre-approved only for reading.

---

## Demo

[`inhousecode-demo`](../inhousecode-demo) is a small repo seeded with the
exact defects this catches — an injection, a swallowed exception, a hard-coded
credential, an N+1 query. Clone it, install the hooks, try to commit, watch both
phases work.

---

## License

MIT. See [LICENSE](LICENSE).
