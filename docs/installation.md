# Installation

## Prerequisites

`inhousecode doctor` checks all of these for you at any time and tells you
exactly what's missing — this table is for knowing what to have ready before
you start, and why each one is there.

Every floor below is the version that introduced the specific feature
inhousecode calls, not a round number — the "why" column names it, so you can
check the claim rather than trust it.

| Tool | Minimum | Why that number | Required for | Check / install |
|---|---|---|---|---|
| **git** | **2.9** | `core.hooksPath`, which the pre-commit trigger is installed through, landed in 2.9 (June 2016). Nothing else in the codebase needs a newer git | Everything — the tool only runs inside a git repo | `git --version` |
| **Python 3** | **3.9** | PEP 585 builtin generics (`list[str]`, `dict[str, str]`) became native in 3.9. Every helper also carries `from __future__ import annotations`, so 3.7 would technically run — 3.9 is the floor that needs no such caveat. **Use 3.10+**: 3.9 reached end-of-life in October 2025, and current Semgrep requires ≥ 3.10 anyway | inhousecode's own helpers (report parsing, config validation) — unrelated to what language *your* code is in | `python3 --version` |
| **[Semgrep](https://semgrep.dev)** | **1.0.0** | First stable major (December 2022); every flag the scanner passes — `--config`, `--metrics off`, `--no-git-ignore`, `--json`, `-o` — has been stable since. The rule packs (`p/security-audit`, `p/owasp-top-ten`, `p/cwe-top-25`) are fetched from the registry at scan time, so a current release is still what you want. Note Semgrep's own wheel declares `requires_python >= 3.10` | Phase 1, the static gate | `semgrep --version`, or `install.sh --with-semgrep` / `install.ps1 -WithSemgrep` |
| **[Copilot CLI](https://github.com/github/copilot-cli)** | **1.0.72** | Two things inhousecode depends on landed together in 1.0.72: `--no-custom-instructions` became fully honored (the reviewer runs with it so reviewed code cannot rewrite the reviewer's brief — see invariant 2 in [AGENTS.md](../AGENTS.md)), and `agentStop` gained a bounded consecutive-block limit plus the `stop_hook_active` flag. Older builds accept the flags but do not honor them the same way | Phase 2 (the AI review), every automatic repair, and the `[e]` explain session | `copilot --version` |
| **GNU `timeout`** (`coreutils`) | **coreutils 7.0** | `timeout` first shipped in coreutils 7.0 (2008), together with the exit-status-124-on-timeout convention that `TIMEOUT_EXIT_STATUS` in `lib/common.sh` checks for. macOS installs it as `gtimeout` via Homebrew's `coreutils`, which inhousecode also accepts | Bounding every agent invocation so a stuck model can't hang a commit | `timeout --version` or `gtimeout --version` |
| **Git Bash** (Windows only) | **Git for Windows 2.9** | Same floor as git itself — it is the bash that ships inside it. WSL bash is *not* supported: it cannot see the Windows-side Copilot CLI or the repo paths the gates pass around | The only supported shell on Windows — `bin/inhousecode` is a Bash script | Installed automatically alongside `git` on Windows |

Optional, only needed for `review --pr`:

| Tool | Minimum | Why that number | Needed for | Check |
|---|---|---|---|---|
| **`gh`** | **2.0.0** | `lib/pr.sh` calls `gh pr view --json baseRefName,headRefName,headRefOid,title,url,body`; the `--json` selector and the `headRefOid` field are stable from 2.0 onward | Reviewing a GitHub pull request by number/URL, authenticated | `gh --version` |
| **`az`** + `azure-devops` extension | **az 2.30**, extension **0.18.0** | `lib/pr.sh` calls `az repos pr show --id <n> --output json` and reads `lastMergeSourceCommit.commitId`, which that extension version is the first to return reliably | Reviewing an Azure DevOps pull request, authenticated | `az --version` |

**Verified against**, on macOS at the time of writing: git 2.39.5, Python 3.12.13,
Copilot CLI 1.0.79, gh 2.97.0. Those are known-good, not required — the floors
in the table are what the code actually needs.

## Install

```bash
git clone https://github.com/iuf26/inhousecode.git && cd inhousecode
bash install.sh                         # interactive: asks before installing anything
bash install.sh --with-semgrep          # scripted/CI: no prompts, installs semgrep
```

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -WithSemgrep   # Windows
```

Run with no flags from a terminal and the installer walks each missing
prerequisite (semgrep, GNU `timeout`) and asks before installing or touching
your shell rc file — nothing happens without a yes. Pass `--with-semgrep`,
`--no-semgrep`, `--with-timeout`, `--no-timeout`, `-y`/`--yes` (assume yes to
everything), or `--non-interactive` (never prompt, just report what's
missing) to skip the questions for scripted or CI installs.

Then, in each repository you want reviewed:

```bash
inhousecode init            # creates .inhousecode/ (config + team rulebook)
inhousecode install-hooks   # installs your configured trigger(s)
inhousecode doctor          # verify everything resolves
```

The installer writes a launcher that points back at your checkout — `git pull`
is the entire upgrade path. See [Prerequisites](#prerequisites) above for what
each dependency is for and which versions are safe.

## Installing the pre-commit hook

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
