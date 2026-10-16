# The idea, in plain terms

This page skips the flags and the config schema. It's for the five minutes
before that, when the question is just: *what is this, and why would my team
want it?*

## The problem

AI writes most of the code now. Reviewing it did not get five times easier
just because writing it got five times faster.

A 900-line diff that took an agent forty seconds to generate still takes a
human forty minutes to actually read. Nobody spends those forty minutes.
People skim, see something that looks plausible, and approve — which means
review is now happening at exactly the moment it matters least, on exactly
the code that needs it most.

The obvious fix — "review the AI's code with another AI" — has its own hole
in it. If the only check is a model reading a diff and giving an opinion,
your entire safety net is one more thing that can hallucinate. A model that
would have missed the bug can just as easily miss it a second time, wearing
a reviewer's hat instead of an author's.

## Why the tools on the market didn't fit

We looked at existing AI code review products before building this. They
work, in the sense that they produce comments. What they don't do is know
anything about *your* team.

They flag generic smells at a generic bar, the same bar for every customer,
because that's the only bar a multi-tenant product can maintain. They don't
know that every query in your codebase has to filter by `tenant_id`. They
don't know that `except Exception` in your billing service cost someone a
weekend last spring. They don't know your team stopped allowing a dependency
six months ago for a reason that never made it into a linter rule.

That knowledge exists. It lives in senior engineers' heads, in Slack threads,
in review comments that get typed out fresh every single time someone
repeats the same mistake. A general reviewer can't use it, because nobody
wrote it down anywhere a reviewer could read it.

Named names and a side-by-side table — Claude Code Review, Copilot code review,
and this — are in [comparison.md](comparison.md), including where each of the
other two genuinely wins.

## Why "inhousecode"

The name is the whole pitch, compressed.

**In-house** because the knowledge the reviewer enforces is *yours* — recorded
by your team, scoped to a project or shared globally, and promoted only under
your policy. Not a vendor's opinion of good code. Yours.

OpenViking is the persistent store. A comment starts as candidate memory with
provenance and evidence. inhousecode validates its scope, risk, lifecycle, and
approval before it can become active project or global knowledge. Each review
gets one frozen snapshot with record URIs and a hash, so the reviewer can cite
what informed it without silently changing policy mid-run.

## How it actually works, briefly

Two phases, in order, and they are not interchangeable:

1. **A deterministic floor first.** Semgrep runs before any model sees the
   diff. No opinions, no context window, no charm — just pattern matching for
   the objectively bad stuff (injection, hard-coded secrets, unsafe
   deserialization). This is the check a hallucinating reviewer can't talk
   its way around, because it isn't a reviewer at all.
2. **An AI review that knows your team.** Once the floor holds, an AI
   reviewer reads the PR description, the diff, and a frozen snapshot of your
   governed knowledge, then reports the exact line, rule provenance, and fix.

Findings split by how much judgment they require. Critical and high-severity
issues get fixed automatically and re-checked — they're not opinions, so
your attention shouldn't be spent approving them. Medium and low findings get
listed, numbered, and left to you — those *are* opinions, and a tool that
silently rewrites your code because it prefers a different shape isn't
reviewing, it's editing.

It can run at commit time, or the moment your coding agent finishes
generating — whichever point you'd rather catch things.

## What this deliberately isn't

- **Not a full-codebase, multi-agent sweep.** It reviews the diff in front of
  it, not your whole repository — a hosted service reading full-repo context
  in parallel will catch classes of bug this can't see.
- **Not hosted infrastructure — in this, the self-hosted version.** No
  dashboard, nothing runs on *inhousecode's* servers; the tool is a checkout on
  your machine (or CI runner), not a service you send code to. That's a
  narrower claim than "your code never leaves the machine": Phase 2 still calls
  out to your configured AI CLI's models — Copilot, Claude Code, Codex, or Hermes —
  and the second opinion calls a different model again, the same way any AI
  reviewer would. What inhousecode adds is a
  deterministic floor that runs before any of that, and a pipeline you can
  read, fork, or swap pieces out of — not an on-machine guarantee for the AI
  phase. (A [managed cloud version](business-case.md#self-hosted-or-managed)
  does exist as a separate commercial offering, for teams that would rather not
  run it themselves. Everything in this repository is the self-hosted tool.)
- **Not a reviewer-of-record.** It's a gate, meant to run alongside a
  full-codebase reviewer, not replace one. See
  [comparison.md](comparison.md#where-each-one-genuinely-wins) for where the
  hosted alternatives genuinely win.

## What you get on day one vs. six months in

Day one: a static and AI check that catches the obvious stuff, wired into
your commit flow with essentially no setup.

Six months in, if governed knowledge gets used: a reviewer that applies the
approved lessons your team has preserved, keeps project and global scope
separate, and can trace each applied rule to its source and evidence.

---

Ready for the mechanics? Follow [docs/getting-started/](getting-started/)
page by page — install, first review, first rule, the hook, then rolling it
out to the rest of the team.
