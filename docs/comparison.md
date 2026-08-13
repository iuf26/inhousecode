# How inhousecode compares

Claude Code Review and GitHub Copilot code review both exist, both work, and
both are built by companies with more engineers than this project has files.
So the fair question to open with is not "which is best" — it's **why build a
third thing at all?**

## Why this comparison exists

This is not a survey of the market, and inhousecode is not a library that
exists because writing one looked fun. It exists because of a specific gap the
two managed products share by design, and this page is the honest accounting of
where that gap is real and where it isn't.

The two incumbents are both **hosted review services attached to a pull
request**. That shape decides almost everything else about them:

- The review happens *after* the code is pushed, on someone else's
  infrastructure, in a place where the feedback loop is a PR comment thread.
- Everything the reviewer knows comes from one model reading a diff. There is
  no deterministic layer underneath it — if the model misses the SQL injection,
  nothing else was looking.
- Findings are advisory. Neither product blocks a merge on its own, on purpose,
  so existing workflows stay intact.
- The review method is closed. You supply instructions; the pipeline that
  interprets them is the vendor's, and you cannot open it, change it, or add a
  step to it.

That's a good product shape for "add a second opinion to our PRs." It is not
the shape of "nothing reaches the branch until it clears a bar our team
defined." inhousecode is the second thing: a **local gate**, run at commit time
or the instant an agent finishes a turn, with a deterministic floor underneath
the model and rules the team wrote down.

The honest version of the pitch: if PR-time advisory comments are what you
want, the incumbents do that better than this project will. Read on if you want
the gate.

## What Claude Code Review offers

Anthropic's managed service ([docs](https://code.claude.com/docs/en/code-review)),
currently in research preview for Team and Enterprise plans.

- **Where it runs**: Anthropic infrastructure, via a GitHub App. Not available
  to orgs with Zero Data Retention enabled.
- **How it reviews**: a fleet of specialized agents analyze the diff *and the
  surrounding codebase* in parallel, each hunting a different class of issue,
  followed by a verification step that checks candidates against real code
  behavior to strip false positives. This is genuinely strong — full-codebase
  context is the thing local tooling struggles hardest to match.
- **Triggers**: once per PR, on every push, or manual via `@claude review` /
  `@claude review always`.
- **Customization**: `CLAUDE.md` (project context; violations surface as nits)
  and `REVIEW.md` (review-only instructions injected into every agent as
  highest priority — severity recalibration, nit caps, skip rules,
  repo-specific checks, verification bars).
- **Severity**: 🔴 Important / 🟡 Nit / 🟣 Pre-existing. The check run always
  completes **neutral**, so it never blocks a merge; you gate it yourself by
  parsing the check-run output in your own CI.
- **Cost**: **$15–25 per review** on average, scaling with PR size and
  complexity, billed as usage credits separate from your plan. Reviews take
  ~20 minutes. "After every push" multiplies that by the number of pushes.

There is also `/code-review` in the Claude Code CLI — free of the GitHub App,
runs locally as a background subagent, supports `--fix` and `--comment`. That's
a different and much cheaper thing than the managed service, and it's the
closest existing analogue to what inhousecode does locally. It does **not** read
`REVIEW.md`.

## What GitHub Copilot code review offers

GitHub's reviewer ([docs](https://docs.github.com/en/copilot/concepts/agents/code-review)),
included in all paid Copilot plans.

- **Where it runs**: GitHub.com, GitHub CLI, GitHub Mobile, VS Code, Visual
  Studio, JetBrains, Xcode, and Azure DevOps (preview). The broadest surface
  area of the three by a distance.
- **Triggers**: manual on demand, or automatic at user / repo / org level,
  including on draft PRs and on every push.
- **Customization**: `.github/copilot-instructions.md` (repo-wide),
  `.github/instructions/**/*.instructions.md` (path-scoped), `AGENTS.md`,
  `.github/skills/`, plus MCP servers. It now also reads `REVIEW.md`,
  `CLAUDE.md`, and `GEMINI.md`, so customization written for other tools is
  picked up automatically.
- **Effort levels**: Lite (default, fast) and Balanced (higher-reasoning model
  for complex logic and security-sensitive code).
- **Merge blocking**: not on its own. GitHub Code Quality rulesets can gate
  merges alongside it.
- **Cost**: roughly **$0.05–$1 per review** on Lite, **$0.25–$5** on Balanced,
  drawn from AI credits — with GitHub Actions minutes billed separately on top,
  and consumption rising with PR size *and* with the size of your custom
  instructions. Still an order of magnitude cheaper than the Claude service.
- **Stated limitation**, verbatim from the docs: "Copilot is not guaranteed to
  spot all problems or issues in a pull request. Sometimes it will make
  mistakes."

## The comparison with inhousecode

The inhousecode column below is the **self-hosted** tool in this repository —
the thing you can read, fork and run for free, and the fair subject for a
comparison against two hosted products. A [managed cloud
version](business-case.md#self-hosted-or-managed) exists separately for teams
that want the same pipeline operated for them; it does not change any row here
except where you run it.

| | **Claude Code Review** | **Copilot code review** | **inhousecode** |
|---|---|---|---|
| **Shape** | Hosted service on a PR | Hosted service on a PR (+ IDEs) | Local gate on your machine / CI |
| **When it runs** | PR open / push / `@claude review` | PR open / push / on demand | `git commit`, agent-stop hook, or `review --pr` |
| **Deterministic layer** | None — model only | None — model only | **Semgrep runs first**, before any model opines |
| **Can it block?** | No, neutral check by design | No, needs Code Quality rulesets | **Yes** — that's the point; non-zero exit stops the commit |
| **Does it fix?** | No, posts comments | Suggestions you apply | **Yes** — static repair loop (≤20 rounds), auto-fix for CRITICAL/HIGH |
| **Who decides on a finding** | You, per comment | You, per suggestion | **Severity decides**: CRITICAL/HIGH auto-fixed, MEDIUM/LOW numbered and left to you |
| **False-positive control** | Verification agent | None documented | Rubber-duck critique + **second opinion from a different model**, strictly subtractive |
| **Team rules** | `CLAUDE.md`, `REVIEW.md` | `copilot-instructions.md`, `AGENTS.md`, `REVIEW.md`, `CLAUDE.md` | `.inhousecode/developer-rulebook.md`, **cited by name in every finding** |
| **Can you change the reviewer itself?** | No — instructions only, the pipeline is Anthropic's | No — instructions only, the pipeline is GitHub's | **Yes** — the reviewer *is* a skill in your repo; edit its method, fork it, reuse it |
| **Can you add your own checks?** | No | No | **Yes** — any tool that emits the finding contract is a gate |
| **Codebase context** | **Full repo, multi-agent** — strongest here | Diff + instruction files | Diff + blast-radius map + commit log + PR description |
| **Explains a finding** | Collapsible reasoning in the comment | Comment text | `[e]` → briefing quoting the rule **verbatim**, then an interactive session |
| **Fails safe?** | Best-effort; failed run posts nothing | Best-effort | **Malformed or missing output = `unavailable` = blocks.** Never a silent pass |
| **Cost per review** | **$15–25** | **$0.05–$5** (+ Actions minutes) | Your CLI's own credits, itemized per phase in the run summary |
| **Availability** | Team/Enterprise, no ZDR orgs | All paid Copilot plans | MIT license, self-hosted, any repo — requires Copilot CLI today; a managed cloud version is available commercially |

### Sources

Vendor claims above are taken from the vendors' own documentation, checked
**13 August 2026**. Both products move quickly — re-verify the cost rows before
quoting them anywhere that matters.

**Claude Code Review** — all rows from
[code.claude.com/docs/en/code-review](https://code.claude.com/docs/en/code-review):

- *Shape, availability, codebase context* — "How reviews work" and the research-preview note (Team/Enterprise, excluded for Zero Data Retention orgs)
- *When it runs* — "Set up Code Review" (review behavior dropdown) and "Manually trigger reviews"
- *Can it block?* — "Check run output": the check run "always completes with a neutral conclusion so it never blocks merging"
- *False-positive control* — "How reviews work": a verification step "checks candidates against actual code behavior to filter out false positives"
- *Team rules, can you change the reviewer* — "Customize reviews" (`CLAUDE.md` and `REVIEW.md` are the only two inputs; the pipeline itself is not configurable)
- *Explains a finding* — "Severity levels": findings carry a collapsible extended reasoning section
- *Fails safe?* — "Troubleshooting": "Review runs are best-effort. A failed run never blocks your PR, but it also doesn't retry on its own"
- *Cost* — "Pricing": "Each review averages $15-25 in cost", billed via usage credits, ~20 minutes average

**Copilot code review** — from GitHub's docs:

- *Shape, when it runs, team rules, merge blocking, limitations* — [About GitHub Copilot code review](https://docs.github.com/en/copilot/concepts/agents/code-review)
- *Automatic triggers at user/repo/org level* — [Configuring automatic code review](https://docs.github.com/en/copilot/how-tos/copilot-on-github/set-up-copilot/configure-automatic-review)
- *Cost and effort levels* — [Models and pricing for GitHub Copilot](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing): "$0.05 USD to $1 USD worth of AI credits with Lite effort, and $0.25 USD to $5 USD with Balanced effort", noting consumption rises with PR size and custom instructions, and that **GitHub Actions minutes are billed separately on top**
- *Effort levels GA* — [Copilot code review effort levels are generally available](https://github.blog/changelog/2026-08-07-copilot-code-review-effort-levels-are-generally-available/)
- *Reads `REVIEW.md` / `CLAUDE.md` / `GEMINI.md`, instructions read from the head branch* — [Copilot code review: Customization and configurability improvements](https://github.blog/changelog/2026-07-17-copilot-code-review-customization-and-configurability-improvements/)
- *Instruction file patterns* — [Using custom instructions to unlock the power of Copilot code review](https://docs.github.com/en/copilot/tutorials/customize-code-review)

**inhousecode** — all rows are this repository, so they're verifiable by
reading it rather than by trusting the table:

- *Deterministic layer, repair loops, fails safe, finding contract* — [architecture.md](architecture.md)
- *Can it block? / who decides on a finding* — [design-principles.md](design-principles.md#five-positions)
- *False-positive control* — [the critique pass](architecture.md#the-critique-pass) and [second-opinion.md](../skills/code-review/references/second-opinion.md)
- *Team rules* — [team-customization.md](team-customization.md)
- *Change the reviewer / add your own checks* — [skills/code-review/SKILL.md](../skills/code-review/SKILL.md) and [the finding contract](architecture.md#the-finding-contract)
- *Explains a finding* — [the explain handoff](architecture.md#the-explain-handoff)
- *Codebase context* — [judging a change against what it promised](architecture.md#judging-a-change-against-what-it-promised)
- *Cost reporting* — [what the run cost](architecture.md#what-the-run-cost)
- *Availability* — [installation.md](installation.md)

## Where each one genuinely wins

**Claude Code Review** wins on depth. Parallel specialized agents reading your
whole codebase will find classes of bug that a diff-scoped local review cannot
see, and the verification pass is a real answer to false positives. If your
constraint is "catch the subtle regression in a 2,000-file service" and the
budget is there, it's the strongest reviewer of the three. The trade is $15–25
a pop, ~20 minutes, your code on someone else's infrastructure, and a review
that can only ever advise.

**Copilot code review** wins on reach and price. It's everywhere your team
already is, costs cents, and reads every instruction file format anyone has
invented. If you want a light second pair of eyes on every PR with essentially
no cost or setup decision to make, this is the pragmatic default.

**inhousecode** wins on **control**, and that word is doing specific work:

1. **Control over what "bad" means.** The rulebook is one line per rule, in
   your repo, re-read every run, and every finding cites the rule by name. Not
   a vendor's calibration of "Important" that you nudge with prose — your rule,
   quoted back at you.
2. **Control over when it happens.** Before the commit, or the moment your
   agent stops generating — with the agent's context still loaded, so a fix
   costs nothing to re-explain. Not after the code is already pushed and named
   in a PR.
3. **Control over what gets through.** A malformed report blocks. A crashed
   scanner blocks. A confused model blocks. Neither hosted service will ever
   stop a merge on its own, because stopping merges is not a safe default for a
   multi-tenant product — but it may be exactly the default *you* want.
4. **Control over the floor.** Semgrep catches injection, hard-coded secrets,
   and unsafe deserialization deterministically, before a model has an opinion.
   If your only reviewer is a model, your entire safety net is one more thing
   that can hallucinate.
5. **Control over the bill.** Every phase — second opinion, repair rounds,
   re-review — is a config key you can switch off, and the run summary itemizes
   what each one cost using the CLI's own reported figures, never an estimate.
6. **Control over the reviewer itself.** This is the one the other two
   structurally cannot offer. With both hosted services you write *instructions*
   and a fixed pipeline interprets them; the review method is the vendor's and
   you tune it from the outside. Here the reviewer is
   [a skill in your repo](../skills/code-review/SKILL.md) — its checklist, its
   critique pass, its severity rubric, its output shape are all markdown files
   your team can edit, fork per-repo, or lift wholesale into another project.
   And because both phases speak one five-field
   [finding contract](architecture.md#the-finding-contract), Semgrep is just
   *an* implementation of a gate, not *the* static check: swap it, or bolt on
   your own linter, license scanner, or house script, and the orchestrator
   treats it identically — same severity handling, same repair loop, same
   verdict.

And the honest limits: inhousecode has no full-codebase multi-agent sweep, no
hosted infrastructure, no dashboard, and it depends on the Copilot CLI, Semgrep,
and Python being installed. It is a gate, not a reviewer-of-record.

## These are not mutually exclusive

The most defensible setup is probably both. inhousecode as the local gate that
enforces your team's rules and the deterministic floor before code ever leaves
the machine; a hosted reviewer on the PR for the whole-codebase depth a local
diff-scoped tool can't reach. They fail in different directions, which is the
only reason running two of anything is ever worth it.

---

See also: [concept.md](concept.md) for why the rulebook is the whole idea,
[design-principles.md](design-principles.md) for why static comes before AI,
and [architecture.md](architecture.md) for the pipeline and trust boundaries.
