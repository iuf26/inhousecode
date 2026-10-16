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
| `harness` | `"copilot"` | Which AI CLI backend to use: `copilot`, `claude-code`, `codex`, or `hermes` |
| `review.fixByDefault` | `false` | Repair all static and AI findings on every review; `--no-fix` overrides it |
| `triggers.preCommit` | `true` | `install-hooks` installs the git pre-commit hook |
| `triggers.agentStop` | `false` | `install-hooks` installs the Copilot CLI `agentStop` hook |
| `static.enabled` | `true` | Run Semgrep at all |
| `static.autofix` | `false` | Hand findings to a fixer agent and re-scan |
| `static.maxFixLoops` | `20` | Repair-round budget (max 20) |
| `static.fixSeverity` | `"all"` | `all` repairs every finding; `blocking` repairs only CRITICAL/HIGH |
| `static.restageFixes` | `true` | Re-stage previously staged paths after each repair round |
| `static.semgrepConfigs` | security packs | Registry packs passed as `--config` |
| `ai.enabled` | `true` | Run the AI review |
| `ai.model` | `""` | Model id for your configured harness; empty means "whatever the CLI is set to" |
| `ai.timeoutSec` | `600` | Hard limit on a review run (fixers get double) |
| `ai.autofixBlocking` | `true` | Repair CRITICAL/HIGH automatically, then re-review |
| `ai.maxFixLoops` | `3` | Repair rounds for blocking findings, and triage rounds after your own picks |
| `ai.triageFindings` | `true` | Offer the numbered picker over every finding |
| `ai.verifyIntent` | `true` | Check the change against the PR description, claim by claim |
| `ai.impactAnalysis` | `true` | Precompute who else depends on the contracts the change touched |
| `ai.critiqueModel` | `""` | Model that gives the second opinion on the findings; empty disables the pass |
| `ai.critiqueRounds` | `2` | Critique/correction rounds; `0` disables the second opinion |
| `agentStop.static` | `true` | Run Semgrep when the agent finishes a turn |
| `agentStop.ai` | `false` | Also run the AI review on each turn |
| `agentStop.maxTurns` | `20` | Times the hook may block a single session |
| `explain.enabled` | `true` | Offer `[e]` at the blocked and triage prompts, and allow `inhousecode explain` |
| `explain.autoLaunch` | `true` | Start the harness's interactive session directly; `false` writes the briefing and prints the command |
| `explain.contextLines` | `5` | Source lines shown either side of each finding (max 25) |
| `explain.model` | `""` | Model for the explain session only; empty means "whatever the CLI is set to" |
| `memory.enabled` | `true` | Resolve governed OpenViking knowledge for AI review |
| `memory.contextMaxChars` | `4000` | Maximum characters injected from the frozen review snapshot |
| `memory.recordSessions` | `false` | Send each review's outcome to OpenViking as a session so it can learn ([details](memory-policy.md#learning-from-review-sessions)) |
| `memory.autoPromoteAfterReviews` | `3` | Automatically promote a safe project lesson after this many separate reviews; `0` disables it and `1` is invalid |
| `adversarial.enabled` | `false` | Turn on adversarial multi-lens review (also togglable per run with `--adversarial`) |
| `adversarial.model` | `""` | Model the adversarial lenses run on — a different model than the primary review, on the same harness; empty falls back to the primary review model |
| `adversarial.maxLenses` | `4` | Cap on how many lenses run (1-4); the actual number is auto-sized by diff and operational risk |

## `harness`

| Key | Default | Meaning |
|---|---|---|
| `harness` | `"copilot"` | Which AI CLI backend to use |

The harness selects which AI CLI inhousecode calls for the review, repair, and
explain agents. Four values are accepted:

| Value | CLI binary | What you need |
|---|---|---|
| `copilot` | `copilot` | A [GitHub Copilot CLI](https://github.com/github/copilot-cli) subscription |
| `claude-code` | `claude` | [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed (`npm install -g @anthropic-ai/claude-code`) and authenticated |
| `codex` | `codex` | [OpenAI Codex CLI](https://developers.openai.com/codex/cli/) installed and authenticated |
| `hermes` | `hermes` or `claude` | [Hermes](https://github.com/nousresearch/hermes) installed; falls back to `claude` if `hermes` is not on PATH |

The installer writes your choice into the shipped default config. A per-repo
`.inhousecode/config.json` can override it:

```json
{ "harness": "claude-code" }
```

Environment variables for explicit binary paths: `COPILOT_BIN`, `CLAUDE_CODE_BIN`,
`HERMES_BIN`, `CODEX_BIN`. These override PATH resolution for their respective
harness.

The selected review backend is separate from the interactive harness command.
For example, `/inhousecode review staged` can be entered in Hermes while
`harness: "codex"` runs the isolated reviewer through Codex. See
[Harness commands](harness-commands.md).

## `review` — default repair behavior

| Key | Default | Meaning |
|---|---|---|
| `fixByDefault` | `false` | Treat every review as `--fix`, repairing all static and AI findings before the final verdict |

This is deliberately off for existing users. Enable it in the repository:

```json
{
  "review": { "fixByDefault": true }
}
```

With this setting (or `--fix`), both fixers repair **every** finding —
static.fixSeverity is overridden to `all` for that run, and the AI fixer
receives blocking and non-blocking findings. Every loop remains bounded, stops
on no progress, and re-runs its gate after each edit — even when a repair
round itself fails or times out, because a fixer that touched files before
failing must never be covered by a verdict from before the edit. Fixers never
commit or push. In staged mode, only paths that were already staged may be
re-staged.

Precedence is fixed and independent of flag order:

1. `--no-fix` disables every repair and the interactive picker.
2. `--fix` enables all-finding repair for that run.
3. Otherwise, `review.fixByDefault` decides whether all-finding repair is on.
4. When all-finding repair is off, `static.autofix`, `ai.autofixBlocking`, and
   `ai.triageFindings` keep their existing behavior.

For `--diff` and `--pr`, the setting counts as the repair opt-in, but repairs
are still refused unless the reviewed commit is currently checked out.

## `triggers`

| Key | Default | Meaning |
|---|---|---|
| `preCommit` | `true` | `install-hooks` installs the git pre-commit hook |
| `agentStop` | `false` | `install-hooks` installs the Copilot CLI `agentStop` hook |

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
| `model` | `""` | Model id for your configured harness; empty means "whatever the CLI is set to" |
| `timeoutSec` | `600` | Hard limit on a review run (fixers get double) |
| `autofixBlocking` | `true` | Repair CRITICAL/HIGH automatically, then re-review |
| `maxFixLoops` | `3` | Repair rounds for blocking findings, and triage rounds after your own picks |
| `triageFindings` | `true` | Offer the numbered picker over every finding |
| `verifyIntent` | `true` | Check the change against the PR description, claim by claim |
| `impactAnalysis` | `true` | Precompute who else depends on the contracts the change touched |
| `critiqueModel` | `""` | Model that gives the second opinion on the findings; empty disables the pass |
| `critiqueRounds` | `2` | Critique/correction rounds; `0` disables the second opinion |

Notes:

- Leaving `model` empty respects each developer's own model choice in their
  configured CLI. Pin it only when a team needs identical review behavior
  across machines.
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
| `autoLaunch` | `true` | Start the harness's interactive session directly; `false` writes the briefing and prints the command |
| `contextLines` | `5` | Source lines shown either side of each finding (max 25) |
| `model` | `""` | Model for the explain session only; empty means "whatever the CLI is set to" |

A blocked commit tells a developer that something is wrong without telling them
why. `[e]` builds a **briefing** — every finding, its applicable governed rule
and provenance when available, and the reviewed source around it — and opens an
interactive session over it. The session explains first and edits nothing until
asked.

Notes:

- The briefing is built with **no model involved**, and is written to
  `.inhousecode/cache/last-briefing.md`. If the configured harness's CLI is
  missing, the path is printed and the briefing still stands on its own.
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

## `memory` — governed review knowledge

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Resolve and inject an OpenViking snapshot |
| `contextMaxChars` | `4000` | Hard prompt budget for the resolved snapshot |
| `recordSessions` | `false` | Write review outcomes as OpenViking sessions under a dedicated user; harvest them with `inhousecode memory harvest` |
| `autoPromoteAfterReviews` | `3` | Promote a recurring, low-risk project lesson after this many qualifying reviews; `0` disables automatic promotion |

OpenViking is the only persistent memory store. The resolver searches approved
project knowledge, approved global knowledge, and relevant candidates, then
filters status, scope, expiry, supersession, and quarantine before ranking.
Project knowledge precedes global knowledge; candidates are labelled unverified.
Automatic promotion never applies to security knowledge, suppression of review
findings, conflicts, overrides, or lessons without evidence in repository code.

```bash
inhousecode memory init
inhousecode memory candidate add "<fact>" --source developer-feedback
inhousecode memory classify <id> --target project --confidence high --evidence file:line
inhousecode memory promote <id> --target project --reason "approved" --evidence ADR-42
inhousecode memory view --prompt "What changed last week?"
```

### Preferences captured during a review

Memory is not only seeded up front — it learns from the reviews themselves. When
the gate blocks and a developer disagrees with a finding ("that's how we do it
here"), that preference is a candidate for memory, but **it is evaluated before
it is stored, not auto-saved**. At the blocked prompt:

- `[w] record a team preference` — the developer states the preference; an agent
  drafts a clean one-line entry from the finding plus that note; the developer
  then **approves, edits, or discards** it. Approval creates a candidate with
  provenance; it does not bypass classification or promotion.
- `[o] override and continue` — the override reason is offered as a candidate
  entry too, rather than being discarded to a log.

This is the deliberate evaluation step: a preference voiced in the moment is not
assumed to be a durable rule. The human decides whether it belongs in the repo's
candidate memory, so active policy does not fill with one-off reactions or
unreviewed machine text. See
[usage.md § Recording a team preference](usage.md#recording-a-team-preference-from-a-review).

`inhousecode discover` (see below) is the same door: the discovery agent is
handed a shell that can call `inhousecode memory candidate add`, never raw
OpenViking access. The application validates every write and verifies the exact
destination URI.

### The policy store

OpenViking stores the structured memory policy at
`viking://resources/inhousecode/memory-policy`. inhousecode does not keep a
local policy copy.

See [memory-policy.md](memory-policy.md) for the folders, lifecycle, and test
workflow. Feedback and proposals do not affect reviews until a record is
approved.

## `adversarial` — the deep multi-lens review

The fast per-commit gate runs one subtractive reviewer. Adversarial review is
the opposite posture, on demand: several critical **lenses** each review a whole
change from one angle (Skeptic, Architect, Minimalist, or Operator), then one synthesis pass
merges, deduplicates, and applies a lead judgment. **Use it as the final review
of a whole pull request before it merges — not on every commit.** The fast gate
is for day-to-day work; the adversarial pass is the thorough sign-off review.

- `adversarial.enabled` (`false`): the default state. Turn it on here to make
  every review adversarial, or leave it off and pass `--adversarial` per run.
- `adversarial.model` (`""`): the model the lenses run on. This is the key idea:
  the lenses use a **different model than your normal review, on the same
  harness** you chose at install — a genuine second opinion without a second AI
  CLI. Empty means the lenses fall back to the primary review model (the lens
  prompts still provide the adversarial pressure).
- `adversarial.maxLenses` (`4`): the ceiling. The actual count is auto-sized by
  the change: 1 lens (Skeptic) for a small diff, 2 (+Architect) for medium, and
  3 (+Minimalist) for large. If changed paths or diff semantics indicate
  operational risk, Operator is added at every size: small gets Skeptic +
  Operator, medium gets Skeptic + Architect + Operator, and large gets all four.
  When the cap is lower, Operator is retained ahead of Minimalist. Signals
  include deployments, infrastructure, migrations, queues/workers, external
  calls, retries/timeouts, resource limits, health/metrics/alerts, and production
  configuration. Lower the cap to trade depth for cost.

The Operator lens also reads the repository's relevant documentation before
judging: README files, architecture and service documentation, deployment and
configuration files, runbooks, and operational notes. It should report when a
safe rollout, rollback, limit, or alert cannot be established from the
repository rather than inventing deployment assumptions.

Each lens is one model run and the synthesis one more, so a large operationally
sensitive adversarial review costs roughly five model invocations. That is why it
is opt-in and aimed
at pull requests. The lenses are grounded in the shipped engineering principles
(`skills/code-review/references/engineering-principles.md`) and never contradict
the frozen review snapshot. The synthesis may only ever *subtract* — drop
or downgrade a lens's finding — never invent one, mirroring the fast gate's
second-opinion rule.

## Environment variables

| Variable | Effect |
|---|---|
| `COPILOT_BIN` | Explicit path to the Copilot CLI (harness `copilot`) |
| `CLAUDE_CODE_BIN` | Explicit path to the Claude Code CLI (harness `claude-code`) |
| `HERMES_BIN` | Explicit path to the Hermes CLI (harness `hermes`) |
| `INHOUSECODE_VERBOSE=1` | Stream full agent logs (same as `--verbose`) |
| `NO_COLOR` | Disable colored output |

## CLI overrides

Flags beat configuration for a single run:

```bash
inhousecode review --mode static   # ai.enabled = false
inhousecode review --mode ai       # static.enabled = false
inhousecode review --no-fix        # all autofix + triage off
inhousecode review --fix           # repair all static and AI findings this run
inhousecode review --gate          # no prompts; exit code is the verdict
inhousecode explain                # session over the last briefing
```

`--diff <base-ref>` and `--pr <id>` are report-only unless `--fix` is given or
`review.fixByDefault` is enabled. Reviewing a pull request must not rewrite an
unrelated checkout, so repairs remain disabled unless the reviewed commit is
the one checked out. Explicit `--no-fix` overrides both opt-ins.

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

**A repository that wants every finding repaired automatically:**

```json
{
  "review": { "fixByDefault": true },
  "static": { "fixSeverity": "all" },
  "ai": { "maxFixLoops": 3 }
}
```
