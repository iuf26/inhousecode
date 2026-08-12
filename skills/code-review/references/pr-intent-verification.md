# Verifying a change against its own description

The pull-request description is not commentary. It is the specification the
author asked to be judged against, and the thing every human reviewer silently
uses as the baseline: *"they said it does X — does it do X?"*

Nobody checks it rigorously. The description is read once at the top, the diff
is read next, and by the time the reviewer reaches the end they are judging the
code against their memory of the description rather than the description itself.
This is where the most expensive review misses come from: not bad code, but code
that was approved for doing something it does not actually do.

This file is the procedure for doing it properly.

## Contents

- [Extract the claims](#extract-the-claims)
- [What is not a claim](#what-is-not-a-claim)
- [Judge each claim](#judge-each-claim)
- [Look the other way](#look-the-other-way)
- [Severity](#severity)
- [Stacked pull requests](#stacked-pull-requests)

## Extract the claims

Read the description and pull out every statement that is **checkable against
this diff** — one you could settle by pointing at code and saying "there it is",
or "it is not there".

Checkable claims usually look like:

- a behavior: *"retries now back off exponentially"*
- a fix: *"fixes the crash when the manifest list is empty"*
- a removal: *"drops the legacy `--sync` flag"*
- a new surface: *"adds `batch_validate()` to the coverage gate"*
- a guarantee: *"no longer writes to the database on a dry run"*
- a migration or config change: *"adds `ai.impactAnalysis`, defaulting to true"*
- a scope boundary: *"only affects the Python generator, not the TypeScript one"*

Write each one as a single short line, in your own words. Two claims in one
sentence are two claims.

## What is not a claim

Extracting too much is the failure mode that makes this check useless — a
checklist of fourteen items, ten of which were never promises, trains the reader
to skip the whole section.

Do not extract:

- **background and motivation** — why the work was needed
- **rollout and ops notes** — how it will be deployed, monitored, or flagged
- **review instructions** — "start with `lib/gate_ai.sh`"
- **screenshots, links, and issue references**
- **explicitly deferred work** — "part 2 will handle the cache", "follow-up",
  "tracked in #451", "out of scope for this PR"
- **template boilerplate** the author never filled in
- **anything unfalsifiable** — "improves performance" with no stated measure is
  not checkable; "cuts the manifest pass from two scans to one" is

## Judge each claim

For each surviving claim, go and find the code. Assign exactly one status:

| Status | Means | Requires |
|---|---|---|
| `MET` | the code plainly does it | the `file:line` that proves it |
| `PARTIAL` | done for some cases, or partly done | precisely what is missing |
| `UNMET` | no code in this change does it | what you searched for |
| `UNVERIFIABLE` | not judgeable from this diff | why, in a few words |

Rules that keep this honest:

1. **Cite, do not assert.** `MET` without a `file:line` is a guess. If you
   cannot cite it, it is not `MET`.
2. **A test is not the implementation.** A test asserting the new behavior is
   good evidence the behavior exists; it is not evidence on its own if the
   production path never reaches it.
3. **A rename is not a feature.** Code that mentions the claim's vocabulary is
   not code that delivers it.
4. **`UNVERIFIABLE` is a real answer, not an escape.** Infrastructure changes,
   dashboards, and manual steps genuinely cannot be judged from a diff. Use it
   for those, and not for claims you simply did not look hard enough for.

## Look the other way

The description bounds the change in both directions. Having checked that
everything promised is present, check whether anything present was never
promised.

Behavior this change introduces that the description does not mention is how a
reviewer approves something they did not know they were approving. Flag it as
`undocumented-change`. The bar is *behavior*: a refactor, a rename, or a
comment that the description skipped is not worth a line.

If the undocumented change is also incompatible with existing callers, it stops
being a documentation problem — see
[breaking-change-analysis.md](breaking-change-analysis.md).

## Severity

The checklist itself carries no severity. What it produces does:

| Situation | Severity | Category |
|---|---|---|
| `UNMET`, and the description states it as delivered here | HIGH | `pr-claim-unmet` |
| `UNMET`, but the wording reads as intent rather than a promise | MEDIUM | `pr-claim-unmet` |
| `PARTIAL` | MEDIUM | `pr-claim-partial` |
| Undocumented behavior change | MEDIUM | `undocumented-change` |
| `UNVERIFIABLE` | no finding | — |

The wording distinction matters. *"Adds retry backoff"* is a promise; *"the goal
here is to make retries less aggressive"* is intent. Blocking a PR over the
second is the kind of false positive that gets this gate turned off.

## Stacked pull requests

A PR that is one of a series (`[3/5]`, "stacked on #99", "depends on #100") is
the case most likely to produce false failures, because its description often
describes the *series* rather than the commit.

Judge it against its own scope only:

- claims the description assigns to a sibling PR are out of scope entirely —
  do not list them, not even as `UNVERIFIABLE`
- code that is present because an earlier PR in the stack added it is not part
  of this change; the diff is the boundary
- a claim you cannot place in either this PR or a named sibling is in scope, and
  gets judged normally
