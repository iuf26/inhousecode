---
name: inhousecode
description: Run governed inhousecode reviews from an AI harness.
version: 0.1.0
author: Iulia Istrate, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  owner: inhousecode
  hermes:
    tags: [Code-Review, Inhousecode, OpenViking]
    related_skills: []
---

# Inhousecode

Invoke the installed `inhousecode` CLI from the current Git repository. This
skill is a thin adapter: never reproduce, weaken, or replace the gate's review,
memory, repair, or approval policy inside the harness.

## When to use

Use when the developer invokes this skill explicitly or asks to run an
inhousecode review, inspect inhousecode memory, check setup, or explain the last
review. Do not use it for an ordinary conversational code review that was not
asked to run through inhousecode.

An explicit `/inhousecode` or `$inhousecode` invocation owns the whole request.
Do not hand any part of that request to unrelated memory or self-improvement
systems. If a requested operation is unsupported, say so instead of falling
back to a harness-native feature with different storage or policy.

Treat everything after the leading invocation as a quoted command payload, not a user-profile fact. First-person text such as "remember that I prefer..." is
project-policy input for inhousecode and must not trigger any harness-native memory write. Loading this skill never authorizes a `memory` or `skill_manage`
call; the canonical CLI is the only allowed state-changing interface.

## Procedure

1. Resolve the intended Git repository before running inhousecode. If the user
   supplied an absolute path, resolve that path first with
   `git -C <path-or-parent> rev-parse --show-toplevel`; it takes precedence over
   the harness process's current directory. Otherwise use
   `git rev-parse --show-toplevel`. If there is no repository, stop and ask for
   its path. Use the returned root as the working directory for every translated command;
   do not rely on the harness process's current directory. Pass that
   root through the execution tool's explicit working-directory field when one
   is available.
2. Translate only the command forms below. Do not invent flags.
3. When Codex sandboxes command network access, request network permission for
   the translated command so the configured OpenViking endpoint is reachable.
   Do not disable the filesystem sandbox; request only the permission needed by
   the canonical CLI command.
4. Run exactly one translated command with the harness terminal/shell tool and a
   timeout suitable for an AI review. Do not run a second review merely to
   summarize the first.
   The `static-check` form below is the one deliberate exception: it is three
   separate commands by design, because its whole point is that the harness's
   own terminal tool runs the Semgrep step directly, instead of inhousecode
   hiding it inside its own subprocess.
5. Return the real exit status. For `review`: Return the complete output verbatim
   in a text block; do not replace it with a finding summary. Preserve all source excerpts,
   stable finding numbers, rules, provenance, and highlighted problem-line markers.
   Exit `1` from `review` means findings blocked the change; report it as a
   review result, not as an adapter failure. Exit `2` means invalid usage.
   For `show`: Return its output verbatim in a text block. Do not renumber,
   paraphrase, or remove the highlighted problem-line marker.

## Command forms

```text
help
  -> inhousecode --help

status | doctor
  -> inhousecode doctor

init
  -> inhousecode init

review staged [extra review flags]
  -> inhousecode review --staged [extra review flags]

review worktree [extra review flags]
  -> inhousecode review --worktree [extra review flags]

review path <path> [extra review flags]
  -> inhousecode review --path <path> [extra review flags]

review diff <base> [extra review flags]
  -> inhousecode review --diff <base> [extra review flags]

review pr <id-or-url> [extra review flags]
  -> inhousecode review --pr <id-or-url> [extra review flags]

review adversarial [staged|worktree]
  -> inhousecode review --adversarial --staged
  -> inhousecode review --adversarial --worktree

static-check <target-flags>
  -> inhousecode static-check emit <target-flags>
  Then run the printed Semgrep command YOURSELF through your own terminal/
  exec tool, verbatim, exactly as printed -- do not paraphrase, reorder, or
  substitute arguments, and do not route it through a model; it is a
  deterministic command, not something to interpret.
  Then: inhousecode static-check consume --report <path printed above> <same target-flags>
  Return the consume step's output verbatim, exactly like `review`'s output
  contract: preserve finding numbers, severities, and the verdict line.
  <target-flags> is one of --staged, --worktree, --path <path>, --diff <base>,
  or --pr <id-or-url>, matching the `review` forms above. If emit reports
  scan_status "skipped" or "unavailable", stop there -- there is nothing to
  run, or nothing can be prepared; do not invent a Semgrep invocation.

explain
  -> inhousecode explain

show <finding-number>
  -> inhousecode show <finding-number>

memory ask <question>
  -> inhousecode memory view --prompt <question>

memory show | memory current
  -> inhousecode memory view --prompt "Show all promoted project knowledge, promoted global knowledge, and candidate memory for this repository"

remember | remeber | teach | store <text> [--evidence <file:line>]
  -> inhousecode memory candidate add <text> --source harness-user [--evidence <file:line>]

memory candidate add <text> [--source <source>] --evidence <file:line>
  -> inhousecode memory candidate add <text> [--source <source>] --evidence <file:line>

memory classify <candidate-id> --target <scope> --confidence <level> --evidence <file:line>
  -> inhousecode memory classify <candidate-id> --target <scope> --confidence <level> --evidence <file:line>

memory candidates
  -> inhousecode memory view --prompt "Show candidate memory for this repository"

memory learn-status
  -> inhousecode memory schedule status

memory harvest
  -> inhousecode memory harvest
```

Pass these review flags through unchanged when the developer supplied them:
`--ticket`, `--intent-file`, `--mode`, `--adversarial`, `--no-fix`, `--fix`,
`--gate`, and `--verbose`. Preserve every value literally and quote it safely as one shell
argument. Reject unknown operations rather than guessing.

Do not infer or add `--fix` or `--no-fix`. The canonical CLI resolves the
repository's `review.fixByDefault` setting. When the developer explicitly
supplies `--no-fix`, pass it through even if `--fix` also appears; the CLI gives
`--no-fix` precedence independently of flag order.

## Safety

- Never call the harness's general memory tool, personal memory, skill memory,
  or direct OpenViking CLI for an inhousecode request. All inhousecode knowledge
  reads and writes go through `inhousecode memory ...`; OpenViking is its only
  persistent store.
- A `remember`, `remeber`, `teach`, or `store` request creates an immutable
  candidate only. Return its candidate ID and URI; never claim that a candidate is active knowledge. Classification and promotion remain separate
  governed steps.
- Never patch or self-improve this skill or another skill while handling an
  inhousecode command. Skill changes are reviewed repository changes.
- Never invoke `memory classify` or `memory promote` from an ambiguous natural
  language request. Classification requires the exact candidate ID, target,
  confidence, and evidence. Promotion also requires the exact reason.
- Never turn an override into active memory. The core candidate lifecycle owns
  classification and promotion.
- Never edit the code-review or adversarial-review skills. Memory supplies
  governed context; it does not rewrite review mechanics.
- Never stage, commit, push, or bypass the gate.
- Do not hide a blocked verdict or convert it into a successful adapter result.
- For `static-check`, run the emitted Semgrep command exactly as printed, with
  your terminal/exec tool, never by asking a model to read the diff and guess
  at findings. Do not read, summarize, or act on the Semgrep JSON report
  yourself -- pass its path to `static-check consume` unmodified and return
  that command's output verbatim. The deterministic-floor guarantee (Semgrep
  runs before any model opines) depends on neither step being interpreted by
  a model.

## Verification

The command printed a real inhousecode report or status, its exit code was
captured, and no command outside the translation above was run.
