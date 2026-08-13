# The business case

**Who this page is for:** product managers, product owners, and engineering
managers deciding whether a team should adopt inhousecode. It assumes no
knowledge of the codebase and contains no code. If you want the technical
version, start with [concept.md](concept.md).

---

## The problem, in one paragraph

Most code is now written by AI assistants. Writing got roughly five times
faster; reviewing did not. A 900-line change an agent produced in forty seconds
still takes a person forty minutes to read properly — so in practice nobody
reads it properly. They skim, it looks plausible, they approve. The result is
that review quality is dropping at exactly the moment code volume is rising,
and the checks your team relies on are being applied least carefully to the code
that was written with the least human attention.

## Why the existing safety net doesn't close it

Most teams respond by adding an AI reviewer to pull requests. That helps, and it
has two structural gaps:

1. **It reviews too late.** The code has been written, pushed, and named in a
   pull request before anything checks it. Every problem found at that point
   costs a round trip: a comment, a context switch, a fix, a re-review.
2. **It doesn't know your team.** A hosted reviewer applies the same general
   standard to every customer. It cannot know that every database query in your
   product must filter by tenant, or that a particular pattern in your billing
   service caused an incident last year. That knowledge lives in a handful of
   senior engineers' heads, and it is applied only when one of them happens to
   read the pull request.

## What inhousecode changes

| | Before | After |
|---|---|---|
| **When code is checked** | After it's pushed, in a pull request | Before it's committed, or the moment the AI agent finishes writing |
| **What "good" means** | The vendor's general standard | Rules your team wrote down, cited by name in every finding |
| **Who applies senior judgment** | Whichever senior engineer reads the PR | Every review, automatically, whether or not they're available |
| **What happens to findings** | A list of comments for someone to action | Serious issues are fixed automatically; judgment calls are listed for a human |

The important shift is the first row. Moving the check earlier means most
problems never become pull request comments, never interrupt a second person,
and never need a review cycle to resolve.

---

## The cost picture

### What the alternatives cost

Both figures are from the vendors' own documentation (see
[comparison.md](comparison.md#sources) for the exact citations):

| Option | Cost per review | Notes |
|---|---|---|
| Claude Code Review | **$15–25** | Deepest analysis of the three; ~20 minutes per review; requires a Team/Enterprise plan |
| GitHub Copilot code review | **$0.05–$5** | Plus GitHub Actions minutes; cost rises with change size |
| inhousecode | Runs on your existing Copilot CLI seats | No new vendor, no new licence; each run reports exactly what it spent, itemised by phase |

### Why the timing matters more than the per-review price

A per-review price only tells you what one check costs. It doesn't tell you what
the *loop* costs. When a problem is found after the code is pushed, the bill
includes things that never appear on an invoice:

- the author's context switch back into work they'd finished
- a second person's time reading and re-reading the change
- the calendar delay between "PR opened" and "PR merged"

Finding the same issue before the commit removes all three. That is where the
saving is, and it is why this is worth doing even alongside a hosted reviewer
rather than instead of one.

### Estimate it with your own numbers

Rather than quote an industry statistic, use your team's real figures:

```
  A  Pull requests per week                          ____
  B  Share that come back with review comments       ____ %
  C  Average round trips per such PR                 ____
  D  Engineer-hours lost per round trip              ____   (context switch,
                                                             re-read, re-review)

  Weekly hours currently spent on review round trips
      = A × B × C × D

  Realistic target: the share of those findings that are mechanical or
  rule-based — the ones a documented rule would have caught before commit.
```

Two costs belong on the other side of the ledger, and neither is hidden:

- **Copilot CLI seats.** Phase 2 needs them. Most teams adopting this already
  have them; if yours doesn't, that's the real line item.
- **Setup and rule-writing.** Roughly a day to install and agree the first
  rules, then a few minutes whenever a team decides to write one down.

---

## The part that compounds

This is the strategic argument, and it's the one that matters most beyond the
first quarter.

Every team accumulates hard-won knowledge: the mistake that caused an outage,
the pattern that doesn't scale, the library the team stopped using and why.
Today that knowledge lives in people's memory and in review comments typed out
fresh each time someone repeats the same mistake. It leaves when they leave.

inhousecode gives it somewhere to live: a single plain-language file in your
repository, one line per rule, which the reviewer re-reads on every run.

| Timeframe | What the team has |
|---|---|
| **Day one** | An automated check catching the obvious problems, wired into the existing commit flow |
| **Month three** | The rules your team argues about most often, enforced automatically and consistently |
| **Year one** | An accumulated standard that survives people changing teams, and that onboards new joiners by enforcing the house style rather than expecting them to absorb it |

The asset is not the tool. The asset is the rulebook, and you own it — it's a
file in your repository, readable by anyone, not data held inside a vendor's
product.

---

## Adoption and risk

### What adoption actually involves

This describes the self-hosted tool. The [managed cloud
version](#self-hosted-or-managed) trades some of these for not having to operate
it yourself.

| | |
|---|---|
| **Procurement** | None. MIT-licensed, installed from a repository. No contract, no new supplier. |
| **New vendors handling your code** | None. Phase 2 uses the Copilot CLI your team already has; nothing runs on inhousecode's own servers. |
| **Setup time** | Under an hour for the tool; about a day including agreeing your first rules. |
| **Rollback** | Uninstall the hook. The rulebook is a text file; nothing is locked in. |

### Honest limitations

A business case that only lists upsides isn't one. Four things to weigh:

- **It reviews the change, not the whole codebase.** A hosted service reading
  your entire repository in parallel will find categories of problem this
  cannot. It's a gate, not a replacement for a full-codebase reviewer.
- **It depends on the Copilot CLI today.** If your organisation doesn't use
  Copilot, that's a prerequisite cost, not a detail.
- **The value tracks the rulebook.** A team that never writes rules down gets a
  competent generic reviewer and little of the compounding benefit above.
- **It is early software.** Version 0.1.0, developed in the open. Suitable for a
  team willing to give feedback; not yet a safe default for an entire
  organisation on day one.

### What to measure

Pick two or three before you start, so the decision to keep or drop it is
evidence-based:

| Metric | Why it's the right one |
|---|---|
| Review round trips per pull request | The direct target — this should fall first |
| Time from PR opened to merged | Captures the calendar cost, not just the effort cost |
| Repeat findings of the same rule | Should trend toward zero as rules get written down; if it doesn't, the rulebook isn't being used |
| Reported spend per run | Printed by the tool itself, so budget stays visible rather than inferred |

---

## Self-hosted or managed

Everything above describes the **self-hosted** tool — MIT-licensed, free, and
run entirely on your own machines and CI. There is also a **managed cloud
version**, a commercial offering for organisations that would rather not operate
it themselves.

| | **Self-hosted** (this repository) | **Managed cloud** |
|---|---|---|
| **Licence and cost** | MIT, free | Commercial; priced on team size and repository count |
| **Where it runs** | Your machines and CI runners | Hosted and operated for you |
| **Setup and upkeep** | You install it and manage Copilot CLI seats | Nothing to install; no seats to administer |
| **Rulebooks** | One file per repository, owned by that team | Maintained centrally and applied org-wide, across every repository |
| **Visibility** | Per-run output in the terminal | Team dashboard: findings over time, rule adoption, spend per team |
| **Support** | Community — GitHub issues | Commercial support with an SLA |
| **The review itself** | The complete two-phase gate | The same two-phase gate |

The last row is the important one. **The self-hosted version is not a trial or a
reduced tier** — it is the full pipeline, and it will stay that way. The managed
version sells operation, org-wide governance and support, not access to the
gate itself. Your rulebook remains a plain readable file either way, so moving
between the two is not a migration.

### Which one fits

- **Self-hosted** suits a single team, or any organisation that wants code and
  configuration to stay on infrastructure it controls, and is comfortable
  running the tool and managing Copilot CLI seats.
- **Managed** suits several teams at once — particularly where one standard
  should apply across many repositories, where someone needs a cross-team view
  of what's being found, or where nobody has capacity to operate it.

To ask about pricing, [open an issue on the
repository](https://github.com/iuf26/inhousecode/issues/new?title=Cloud%20enquiry)
with your team size and roughly how many repositories you'd want covered.

---

## Suggested rollout

| Phase | Duration | What happens | Decision point |
|---|---|---|---|
| **1. Trial** | 1–2 weeks | One team, report-only — findings are shown, nothing is blocked | Are the findings accurate and useful? |
| **2. Write the rules** | 2–4 weeks | The team adds rules for the comments they repeat most | Are repeat findings falling? |
| **3. Enforce** | Ongoing | Turn on blocking for serious findings; keep judgment calls advisory | Are round trips and cycle time down? |

Running phase 1 in report-only mode matters: it lets the team judge quality
before the tool can inconvenience anyone, which is the difference between
adoption and quiet uninstallation.

---

## The decision in one table

| Question | Answer |
|---|---|
| **What problem does it solve?** | AI writes code faster than people can review it, so review quality is falling as volume rises |
| **What's different about it?** | It checks before the commit, not after the push, against rules your team defined |
| **What does it cost?** | No licence and no new vendor; runs on existing Copilot CLI seats and reports its own spend per run |
| **What's the long-term return?** | Your team's review standards become a durable asset that outlasts individuals |
| **What's the risk?** | Early software, diff-scoped rather than whole-codebase, and dependent on the Copilot CLI |
| **How reversible is it?** | Entirely — remove one hook; the rules stay as a readable file you own |

---

Related reading: [concept.md](concept.md) for the same argument in technical
terms, [comparison.md](comparison.md) for a feature-by-feature comparison with
Claude Code Review and Copilot code review, and
[getting-started/](getting-started/) for what a team actually does on day one.
