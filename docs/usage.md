# Usage

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
