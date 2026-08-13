# Configuration

*Defaults and budgets below verified against `config/review.config.default.json`
as of 13 August 2026 — if a value here disagrees with that file, the file
wins.*

Configuration resolves in two layers, lowest precedence first:

1. `config/review.config.default.json` in the inhousecode checkout
2. `.inhousecode/config.json` in the repository being reviewed

Only keys that exist in the default document are accepted. **An unknown key is a
hard error**, not a warning — a typo must never silently disable a gate.

Create the repository layer with `inhousecode init`, then delete everything you
don't want to override.

## All parameters at a glance

Every key in `config/review.config.default.json`, in file order. See the
section below each group for the full explanation and notes — this table is
for finding the key you want fast.

| Key | Default | Meaning |
|---|---|---|
| `triggers.preCommit` | `true` | `install-hooks` installs the git pre-commit hook |
| `triggers.agentStop` | `false` | `install-hooks` installs the Copilot `agentStop` hook |
| `static.enabled` | `true` | Run Semgrep at all |
| `static.autofix` | `false` | Hand findings to a fixer agent and re-scan |
| `static.maxFixLoops` | `20` | Repair-round budget (max 20) |
| `static.fixSeverity` | `"all"` | `all` repairs every finding; `blocking` repairs only CRITICAL/HIGH |
| `static.restageFixes` | `true` | Re-stage previously staged paths after each repair round |
| `static.semgrepConfigs` | security packs | Registry packs passed as `--config` |
| `ai.enabled` | `true` | Run the AI review |
| `ai.model` | `""` | Copilot model id; empty means "whatever the CLI is set to" |
| `ai.timeoutSec` | `600` | Hard limit on a review run (fixers get double) |
| `ai.autofixBlocking` | `true` | Repair CRITICAL/HIGH automatically, then re-review |
| `ai.maxFixLoops` | `3` | Repair rounds for blocking findings, and triage rounds after your own picks |
| `ai.triageFindings` | `true` | Offer the numbered picker over every finding |
| `ai.verifyIntent` | `true` | Check the change against the PR description, claim by claim |
| `ai.impactAnalysis` | `true` | Precompute who else depends on the contracts the change touched |
| `ai.critiqueModel` | `gpt-5.6-sol` | Model that gives the second opinion on the findings |
| `ai.critiqueRounds` | `2` | Critique/correction rounds; `0` disables the second opinion |
| `agentStop.static` | `true` | Run Semgrep when the agent finishes a turn |
| `agentStop.ai` | `false` | Also run the AI review on each turn |
| `agentStop.maxTurns` | `20` | Times the hook may block a single session |
| `explain.enabled` | `true` | Offer `[e]` at the blocked and triage prompts, and allow `inhousecode explain` |
| `explain.autoLaunch` | `true` | Start the Copilot session directly; `false` writes the briefing and prints the command |
| `explain.contextLines` | `5` | Source lines shown either side of each finding (max 25) |
| `explain.model` | `""` | Model for the explain session only; empty means "whatever the CLI is set to" |
| `rulebook` | `.inhousecode/developer-rulebook.md` | Path to the team rulebook, relative to the repo root |

## `triggers`

| Key | Default | Meaning |
|---|---|---|
| `preCommit` | `true` | `install-hooks` installs the git pre-commit hook |
| `agentStop` | `false` | `install-hooks` installs the Copilot `agentStop` hook |

These control what `inhousecode install-hooks` installs when called without
flags. Explicit flags (`--pre-commit`, `--agent-stop`) always win.

## `static` — Phase 1

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Run Semgrep at all |
| `autofix` | `false` | Hand findings to a fixer agent and re-scan |
| `maxFixLoops` | `20` | Repair-round budget (max 20) |
| `fixSeverity` | `"all"` | `all` repairs every finding; `blocking` repairs only CRITICAL/HIGH |
| `restageFixes` | `true` | Re-stage previously staged paths after each repair round |
| `semgrepConfigs` | security packs | Registry packs passed as `--config` |

Notes:

- The loop stops early when a round doesn't reduce the finding count. Each round
  is a model invocation, so a stalled loop is stopped rather than run to budget.
- `fixSeverity: "all"` is the default because static findings are objective. If
  Semgrep flagged it, someone will have to deal with it eventually.
- `restageFixes: false` means repairs land in the working tree but not the index,
  so the next scan sees the old blobs and the loop cannot converge. Only turn it
  off if you want to inspect every change before it is staged.
- Only packs verified to exist in the Semgrep registry should be listed — a
  `--config` that 404s makes Semgrep exit non-zero and discards the whole scan.
  `p/code-quality`, `p/performance`, `p/correctness`, and `p/bash` do **not**
  exist.

## `ai` — Phase 2

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Run the AI review |
| `model` | `""` | Copilot model id; empty means "whatever the CLI is set to" |
| `timeoutSec` | `600` | Hard limit on a review run (fixers get double) |
| `autofixBlocking` | `true` | Repair CRITICAL/HIGH automatically, then re-review |
| `maxFixLoops` | `3` | Repair rounds for blocking findings, and triage rounds after your own picks |
| `triageFindings` | `true` | Offer the numbered picker over every finding |
| `verifyIntent` | `true` | Check the change against the PR description, claim by claim |
| `impactAnalysis` | `true` | Precompute who else depends on the contracts the change touched |
| `critiqueModel` | `gpt-5.6-sol` | Model that gives the second opinion on the findings |
| `critiqueRounds` | `2` | Critique/correction rounds; `0` disables the second opinion |

Notes:

- Leaving `model` empty respects each developer's own `/model` choice. Pin it
  only when a team needs identical review behavior across machines.
- `triageFindings` is skipped automatically without a terminal (CI, `--gate`),
  since there is nobody to ask.
- The picker covers **every** finding, blocking or not, and applies only what
  you type. Your picks are re-reviewed and the remaining list offered again, so
  you can work a change to clean in one sitting; `maxFixLoops` bounds that, and
  when it runs out you are told to re-run rather than held in the loop.
- Renamed from `triageNits`. Configs carrying the old key still load; carrying
  both is an error.
- `verifyIntent` needs a description to check against, so it only does anything
  in `--pr` mode, and only when `gh` or `az` could fetch one. The reviewer
  extracts the checkable claims, reports each as MET / PARTIAL / UNMET /
  UNVERIFIABLE, and raises a finding for the gaps. Claims the description
  assigns to another PR in a stack are deliberately ignored.
- `impactAnalysis` runs in every mode except `--path`. It maps each definition
  the change adds, modifies, or removes to the places outside the change that
  still reference it, so the reviewer can judge breakage against evidence rather
  than guess. The map is syntactic: it will not see dynamic dispatch,
  reflection, or consumers outside this repository.
- `critiqueModel` should be a *different* model from `model`. A model checking
  its own findings shares the reasoning that produced them and agrees with
  itself too easily; the point of the pass is a reader who never believed the
  conclusion. Set it empty to rely on the reviewer's in-session critique alone.
- Each critique round costs up to two model runs — one to critique, one to
  correct — on top of the review. `critiqueRounds: 1` critiques without ever
  correcting; `0` turns the pass off. The pass is skipped automatically when the
  review found nothing, so a clean change never pays for it.

## `agentStop` — the post-generation trigger

| Key | Default | Meaning |
|---|---|---|
| `static` | `true` | Run Semgrep when the agent finishes a turn |
| `ai` | `false` | Also run the AI review on each turn |
| `maxTurns` | `20` | Times the hook may block a single session |

The hook fires on **every** turn, so the default is static-only: fast, cheap, and
deterministic. Turning `ai` on gives deeper feedback at real cost in latency and
tokens on each turn. When `ai` is on, only **blocking** (CRITICAL/HIGH) findings
are handed back — a stop hook that argued about naming after every turn would be
unusable, and the rest is the developer's call anyway.

The hook fails open. Any internal error exits 0 and the turn ends normally — a
broken hook must never trap you inside a session.

## `explain` — the teaching handoff

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Offer `[e]` at the blocked and triage prompts, and allow `inhousecode explain` |
| `autoLaunch` | `true` | Start the Copilot session directly; `false` writes the briefing and prints the command |
| `contextLines` | `5` | Source lines shown either side of each finding (max 25) |
| `model` | `""` | Model for the explain session only; empty means "whatever the CLI is set to" |

A blocked commit tells a developer that something is wrong without telling them
why. `[e]` builds a **briefing** — every finding, the team rule it violates
quoted verbatim from the rulebook, and the reviewed source around it — and opens
an interactive session over it. The session explains first and edits nothing
until asked.

Notes:

- The briefing is built with **no model involved**, and is written to
  `.inhousecode/cache/last-briefing.md`. If the Copilot CLI is missing, the
  path is printed and the briefing still stands on its own.
- It is written on **every** run that finds something, including `--gate` runs
  that never show a prompt — the non-interactive failure is exactly the one you
  most want to ask about afterwards. A clean run deletes it, so `explain` never
  replays findings you already fixed.
- Without a terminal (CI, `--gate`, the `agentStop` hook) nothing is ever
  launched. The `agentStop` hook never offers this at all — it fails open, and a
  hook that dropped you into a session would trap you inside your own turn.
- The session inherits **read** permission only. Anything that can change the
  tree prompts, because the session belongs to the developer, not to the gate.
- Unlike the gates, the explain session keeps your repository's custom
  instructions. It renders no verdict, so the reviewer's isolation rationale
  does not apply and repository context makes its explanations better.
- A commit never survives a session. If the tree changed, the run exits blocked
  and you re-run — nothing has re-reviewed the edits the session made.
- `inhousecode explain` replays the last briefing without re-running the
  gates, for the developer who aborted and thought better of it.

## `rulebook`

Path, relative to the repository root, of the team rulebook.
Default `.inhousecode/developer-rulebook.md`. When the file is absent the
reviewer falls back to the rulebook shipped with inhousecode.

See [team-customization.md](team-customization.md).

## Environment variables

| Variable | Effect |
|---|---|
| `COPILOT_BIN` | Explicit path to the Copilot CLI |
| `INHOUSECODE_VERBOSE=1` | Stream full agent logs (same as `--verbose`) |
| `NO_COLOR` | Disable colored output |

## CLI overrides

Flags beat configuration for a single run:

```bash
inhousecode review --mode static   # ai.enabled = false
inhousecode review --mode ai       # static.enabled = false
inhousecode review --no-fix        # all autofix + triage off
inhousecode review --fix           # allow repairs in --diff mode
inhousecode review --gate          # no prompts; exit code is the verdict
inhousecode explain                # session over the last briefing
```

`--diff <base-ref>` and `--pr <id>` imply `--no-fix` unless `--fix` is given:
reviewing a pull request must not rewrite the author's branch. With `--pr`,
repairs remain disabled even with `--fix` unless the reviewed commit is the one
checked out.

## Worked examples

**A team that wants a hard security floor and nothing else automated:**

```json
{
  "static": { "fixSeverity": "blocking", "maxFixLoops": 5 },
  "ai": { "autofixBlocking": false, "triageFindings": true }
}
```

**A team going all-in on the agent-stop loop:**

```json
{
  "triggers": { "preCommit": true, "agentStop": true },
  "agentStop": { "static": true, "ai": true, "maxTurns": 10 }
}
```

**A CI-style repository with no interactivity:** run
`inhousecode review --worktree --gate --no-fix` and read the exit code.
