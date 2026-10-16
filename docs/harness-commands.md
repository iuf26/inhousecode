# Harness commands

Install the inhousecode Agent Skill once, then invoke reviews without leaving
Hermes or Codex. The skill is a thin command adapter; the `inhousecode` CLI
still owns targeting, safety, memory policy, repair, and the final verdict.

## Install

From any directory:

```sh
inhousecode integrate install all
inhousecode integrate status all
```

Install one harness with `hermes` or `codex` instead of `all`. Installation is
idempotent. It refuses to replace an existing skill not managed by
inhousecode.

Locations:

| Harness | Installed skill | Invocation |
|---|---|---|
| Hermes | `$HERMES_HOME/skills/inhousecode/` (or `~/.hermes/skills/inhousecode/`) | `/inhousecode ...` |
| Codex | `~/.agents/skills/inhousecode/` | `$inhousecode ...` |

Hermes exposes installed skills as dynamic slash commands. Codex uses `$name`
for explicit Agent Skill invocation; a top-level custom slash command is not a
supported Codex extension point. Both harnesses may need a restart after first
installation. Codex normally detects later skill updates automatically.

Codex may ask for network permission when a command needs OpenViking. Approve
access to your configured OpenViking endpoint; the skill keeps the filesystem
sandbox enabled. If permission is denied, memory reports unavailable rather
than silently falling back to local storage.

## Try it

Start the harness from a Git repository and enter one of these commands:

```text
# Hermes
/inhousecode doctor
/inhousecode review worktree --no-fix
/inhousecode show 1
/inhousecode review staged --adversarial --no-fix
/inhousecode memory ask What review rules apply to this repository?

# Codex
$inhousecode doctor
$inhousecode review worktree --no-fix
$inhousecode show 1
$inhousecode review staged --adversarial --no-fix
$inhousecode memory ask What review rules apply to this repository?
```

Other supported targets are `path <path>`, `diff <base>`, and `pr <id-or-url>`.
The adapter safely translates those forms into the canonical CLI flags.

`review` may return exit code `1` when findings block the change. That is a
review result, not an adapter failure. Use `--no-fix` for a report-only first
trial.

To repair all findings once, add `--fix`. To make that the repository default,
set `review.fixByDefault: true` in `.inhousecode/config.json`. The canonical CLI
still enforces precedence: explicit `--no-fix` always disables repairs, and PR
or diff repair is refused when the reviewed commit is not checked out. Hermes
and Codex pass these flags through; they do not implement a separate policy.

The normal review result displays every finding with its saved source excerpt,
stable number, rule, and provenance. The exact problem line is colored in an
interactive terminal and marked with `🔴` in captured Hermes or Codex output.
Harness adapters return these details verbatim instead of replacing them with a
compact summary.

Afterward, `show <number>` displays only one saved finding without invoking a
model. Both displays identify whether the rule came from promoted project
knowledge, promoted global knowledge, Semgrep, or built-in review guidance.

## Select Codex as the review backend

The harness command and the review backend are independent. For example, a
review invoked from Hermes can still use Codex as its isolated reviewer.
Configure the repository with:

```json
{
  "harness": "codex"
}
```

The Codex adapter runs review and discovery agents with a read-only sandbox,
ignores user configuration and repository exec-policy rules, and uses
ephemeral sessions. Only an explicit repair path receives workspace-write
access. The same finding schema and re-review requirement apply to every
backend.

## Update or remove

Re-run installation after updating inhousecode:

```sh
inhousecode integrate install all
```

Remove only files managed by inhousecode:

```sh
inhousecode integrate uninstall all
```

If an installed managed skill was edited locally, uninstall reports a conflict
and leaves it in place. Move or remove it manually only after inspecting those
local changes.
