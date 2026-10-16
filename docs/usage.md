# Usage

```bash
inhousecode review                   # staged changes (what pre-commit runs)
inhousecode review --pr 1234         # review a pull request by number
inhousecode review --worktree        # everything uncommitted
inhousecode review --diff main       # commits this branch adds on top of main
inhousecode review --path src/api    # a whole folder or file
inhousecode review --mode static     # skip the AI phase
inhousecode review --no-fix          # report only, touch nothing
inhousecode review --fix             # repair all static and AI findings
inhousecode review --gate            # non-interactive; exit code is the verdict
inhousecode explain                  # session over the last run's findings
inhousecode discover                 # propose candidate knowledge for this repo
inhousecode memory view --prompt "…" # ask what the team knows (read-only)
```

Exit codes: `0` pass or override, `1` blocked, `2` usage error.

Bypass every hook once with `git commit --no-verify`.

## Fix every finding by default

Repairs are opt-in. To make every review repair all static and AI findings,
set this in `.inhousecode/config.json`:

```json
{
  "review": { "fixByDefault": true }
}
```

`--fix` enables the same behavior for one run. `--no-fix` always wins over the
setting and over `--fix`, regardless of flag order. Repair loops are bounded,
stop when the finding count does not improve, and re-review after every edit.
Fixers do not commit or push. Pull-request and diff repairs are still disabled
unless the reviewed commit is checked out.

## First-time setup: `inhousecode discover`

Right after `inhousecode init`, OpenViking holds no knowledge for this
repository. `inhousecode discover` closes that gap in one run: an agent reads
the manifest, the linter/CI configuration, and the existing code, then
proposes a short list of evidence-backed candidates.

```bash
inhousecode discover           # writes candidates to OpenViking
inhousecode discover --gate    # report-only; prints proposals
```

Candidates are unverified until classified and promoted. See
[memory-policy.md](memory-policy.md) for the lifecycle and commands.

## Reviewing someone else's pull request

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

## Fixing a PR branch you have checked out

Because the branch is usually someone else's, a PR review is **report-only** by
default: both repair loops and the finding picker are off. When the branch is
yours, check it out and opt in with `--fix`, or enable
`review.fixByDefault` for the repository:

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

## Checking a change against its ticket and intent

The reviewer already checks a PR against its own description. You can give it two
more sources of intent, so it verifies the diff against what the work was
*supposed* to do, not just the author's summary:

```bash
inhousecode review --pr 1234 --ticket 88                 # GitHub issue #88
inhousecode review --pr 1234 --ticket https://github.com/org/repo/issues/88
inhousecode review --diff main --intent-file SPEC.md      # any free-form spec
```

- `--ticket` fetches a GitHub issue via `gh`, or an Azure Boards work item via
  `az`. For other trackers, pass the URL — inhousecode fetches what it can and,
  if it cannot reach the tracker, says so and continues without it (a ticket is
  evidence, never a gate).
- `--intent-file` reads any file verbatim. It is the escape hatch for trackers
  behind SSO (Jira, Notion): paste the ticket text into a file and point at it.

The reviewer combines every source it was given (PR + ticket + file), extracts
the checkable claims, and reports each as MET / PARTIAL / UNMET / UNVERIFIABLE —
turning the gaps into findings.

## Adversarial review of a whole PR

**Recommended workflow: run the fast gate on every commit, and run an
adversarial review as the final check on a whole PR before it merges.** The
per-commit gate keeps day-to-day work moving; the adversarial pass is the
thorough, sign-off review you want on the change as a whole.

For that final pass on a whole pull request, add `--adversarial`:

```bash
inhousecode review --pr 1234 --adversarial
```

Instead of one reviewer, this spawns several **lenses** — Skeptic, Architect,
Minimalist — each attacking the change from one angle on a *different model than
your normal review* (the `adversarial.model` you set at install, on the same
harness). A final synthesis pass merges and deduplicates their findings, applies
a lead judgment, and produces the usual finding table and verdict.

Use it for: the final review of an entire PR, a large or risky diff, a refactor
touching many files, or anything about to merge. Don't wire it into the
per-commit hook — it is several model runs and is meant to be run deliberately,
not on every save.

The number of lenses is sized to the change (1 for a small diff, up to 3 for a
large one, capped by `adversarial.maxLenses`). Because each lens is its own model
run, this is several times the cost of a normal review — it is meant for pull
requests and large diffs, not every commit. The per-lens cost is itemized in the
run summary. See [`adversarial`](configuration.md#adversarial--the-deep-multi-lens-review)
in the configuration reference, and the
[adversarial-review skill](../skills/adversarial-review/SKILL.md).

## Recording a team preference from a review

When the gate blocks and you disagree with a finding — "we do it that way on
purpose here" — capture it so the reviewer stops flagging it. At the blocked
prompt:

```
  [d] show raw gate output   [e] explain these findings
  [w] record a team preference   [o] override and continue   [a] abort
```

Pick `[w]`. inhousecode asks what the reviewer should know, an agent drafts a
clean one-line entry from the finding and your note, and you approve, edit, or
discard it. Approving writes an OpenViking **candidate** with the finding as
evidence. Overriding with `[o]` does the same with your override reason.

A candidate does not change future reviews until it is promoted — automatically
for safe repository-local facts, by a human for anything shared or risky. See
[memory-policy.md](memory-policy.md).
