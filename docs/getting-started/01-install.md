# 1. Install it

## What you need first

- **git** ≥ **2.9** — that's when `core.hooksPath` landed, which is all the hook needs (verified on 2.39.5)
- **Python** ≥ **3.9**, and 3.10+ in practice — 3.9 is end-of-life and current Semgrep needs 3.10 anyway (verified on 3.12.13)
- **[Semgrep](https://semgrep.dev)** ≥ **1.0.0** — every flag the scanner passes has been stable since that release; rule packs are still fetched live, so prefer a current version
- **[Copilot CLI](https://github.com/github/copilot-cli)** ≥ **1.0.72** — the release that made `--no-custom-instructions` fully honored and bounded `agentStop` blocking (verified on 1.0.79)
- **GNU `timeout`** (coreutils) ≥ **7.0** — when `timeout` and its exit-status-124 convention first shipped; on macOS `brew install coreutils` exposes it as `gtimeout` (verified on 9.10)
- **Git Bash** (Windows only) — ships with [Git for Windows](https://git-scm.com/download/win) ≥ 2.9; bundles `timeout`

You don't strictly need Semgrep or Copilot CLI installed *before* this step —
the installer can pull Semgrep in for you, and `inhousecode doctor` (last
step below) will tell you exactly what's still missing. Full table with why
each one is needed: [docs/installation.md#prerequisites](../installation.md#prerequisites).

## Install the tool

Clone it once, anywhere on your machine — this checkout is what every repo's
hook will point back to, so pick a location you won't casually delete later.

```bash
git clone https://github.com/iuf26/inhousecode.git && cd inhousecode
bash install.sh --with-semgrep          # macOS / Linux / Git Bash
```

The installer will ask you to pick an AI CLI backend:

```
  Which AI CLI do you want inhousecode to use as its backend?

    [1] copilot      — GitHub Copilot CLI  (copilot)
    [2] claude-code  — Anthropic Claude Code CLI  (claude)
    [3] hermes       — Hermes / Claude Code  (hermes or claude)

  Pick a number [1]:
```

Or pass it directly: `bash install.sh --harness claude-code --with-semgrep`.
Add `--fix-by-default` only if you want every review to repair all findings;
the installer otherwise leaves this safe opt-in disabled.

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -WithSemgrep   # Windows
# Add -FixByDefault to opt into all-finding repair.
```

This writes a small launcher onto your `PATH` (`inhousecode`) that execs
straight back into this checkout. That indirection is deliberate: upgrading
later is `git pull` in this folder — nothing to reinstall, nothing to
republish.

## Confirm it worked

```bash
inhousecode doctor
```

This checks every dependency and tells you plainly what's missing and how to
fix it. Don't move on to the next page until it's clean — everything after
this assumes `inhousecode` resolves and its dependencies are in place.

## Nothing is installed into any repository yet

This step only put the `inhousecode` command on your machine. It hasn't
touched a git repo, hasn't installed a hook, hasn't created a config file
anywhere. That's the next page: [Run your first review](02-first-review.md).
