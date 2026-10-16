# 5. Roll it out to the team

Everything so far was one person, one clone. This page is the order that
gets a *team* to keep the gate turned on.

The short version: **don't start by blocking commits.** A gate that
interrupts people before they trust it is a gate that gets uninstalled by
the end of the week, and an uninstalled gate reviews nothing.

## The order that works

1. **Ship it read-only first.** Keep `review.fixByDefault: false`, set
   `static.autofix: false` and `ai.autofixBlocking: false`, and use `--no-fix`
   for evaluation runs. Let the team see findings for a week without anything
   changing under them.
2. **Collect the disagreements.** Every "that's wrong" reply is either a rule
   that needs fixing or missing context the reviewer didn't have. Both are
   cheap to fix, and fixing them makes the next week quieter.
3. **Turn on static repair.** Semgrep findings are deterministic, so their
   fixes are too. This is where people first feel the tool save them time,
   not just flag them.
4. **Turn on AI repair for blocking findings.** By now governed knowledge reflects
   how the team actually works, and the false-positive rate is low enough to
   trust the automatic fix.
5. **Optionally fix every finding by default.** Set
   `review.fixByDefault: true` only after the team trusts non-blocking findings.
   Developers can still force a report-only run with `--no-fix`.
6. **Only then consider agent-stop.** Once people trust the gate at commit
   time, move the check earlier — to the moment the code is generated, not
   the moment it's committed.

Do not start at step 6. Interrupting every agent turn before anyone trusts
the gate is the fastest way to get it deleted.

## Before you flip on steps 4–6, check your AI CLI quota

Every AI-phase run — review, repair, second opinion — spends your AI CLI's
usage budget (Copilot premium requests, or Claude/Hermes API spend,
depending on which `harness` you configured), and `agentStop` fires on
**every turn**, not once per commit. Turning that on for a team multiplies
per-turn AI spend by headcount, not just by commit count. Check your team's
plan headroom before rolling either step out wide, and read the itemized
cost breakdown in
[architecture.md § What the run cost](../architecture.md#what-the-run-cost)
so you know what a run actually charges before a whole team starts running
it constantly. `agentStop.ai` defaults to `false` for this reason — the
static-only default is nearly free; the AI pass on every turn is not. Note
`agentStop` itself only exists for the `copilot` harness today — see
[docs/configuration.md](../configuration.md#harness) if your team is on a
different one.

## The final check before merge: adversarial review

The rollout above is about the *commit-time* gate — the fast, quiet pass that
runs as people work. For the review that decides whether a whole pull request
ships, there is a second, deliberate mode: **adversarial review**.

```bash
inhousecode review --pr 1234 --adversarial
```

Instead of one reviewer, it runs several critical lenses — Skeptic, Architect,
Minimalist — each attacking the change from one angle on a *different model than
your normal review*, then synthesizes one verdict. It is the thorough sign-off
you run on a whole PR before merge, **not** something to wire into the per-commit
hook (it is several model runs — see the cost note above).

Set the lens model once at install, or later via `adversarial.model` in
`.inhousecode/config.json`. The team pattern that works: the fast gate on every
commit, an adversarial review as the last gate before a PR merges. Full details
in [docs/usage.md](../usage.md#adversarial-review-of-a-whole-pr) and
[docs/configuration.md § adversarial](../configuration.md#adversarial--the-deep-multi-lens-review).

## Sharing config and knowledge

Commit only the config:

```bash
git add .inhousecode/config.json
```

Team knowledge lives in the shared OpenViking namespace
`viking://resources/inhousecode/memory-policy/`. Point every developer's `ov`
CLI at the same server. Project knowledge is scoped to this repository; global
knowledge applies across repositories and always needs human approval. See
[docs/memory-policy.md](../memory-policy.md).

## Where the rules actually come from

Not a planning meeting. The best rules come from:

1. A review comment someone has typed more than twice.
2. A postmortem — write the rule that would have caught the incident.
3. Tribal knowledge a new hire currently only learns by breaking it.

Add each as a candidate with evidence; promotion rules are in
[docs/memory-policy.md](../memory-policy.md).

## You're set up

That's the whole guided path. From here:

- [docs/configuration.md](../configuration.md) — every config option
- [docs/architecture.md](../architecture.md) — how the pipeline actually works
- [docs/memory-policy.md](../memory-policy.md) — governing team knowledge
- [../../README.md](../../README.md) — full command reference
