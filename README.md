<h1 align="center">
<img src="docs/assets/image.png" alt="inhousecode — a review gate for AI-generated code, backed by rules your team wrote down" width="100%">
</h1>

<p align="center">
<a href="docs/getting-started/"><strong>Getting Started</strong></a> •
<a href="docs/concept.md"><strong>Why inhousecode</strong></a> •
<a href="docs/business-case.md"><strong>Business Case</strong></a> •
<a href="docs/"><strong>Docs</strong></a> •
<a href="#-how-to-contribute"><strong>Contribute</strong></a> •
<a href="LICENSE"><strong>License</strong></a>
</p>

<p align="center">
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
</p>

## ℹ️ About

> Reviewing code an AI wrote, with a tool that knows nothing about your team?
> **inhousecode is here to help.**

**inhousecode** is a two-phase code review gate built for teams shipping
AI-generated code: deterministic Semgrep first, then an AI reviewer that
enforces rules **your team writes down** — not a vendor's idea of clean code.
That's the whole idea behind the name: rules declared **in-house**.

- 🛡️ A deterministic Semgrep floor runs before any model opines, with a
  bounded auto-repair loop (up to 20 rounds)
- 📓 The AI review reads `.inhousecode/developer-rulebook.md` — a plain file
  your team owns — and cites the exact rule it's enforcing on every finding
- 🚦 Blocking findings (CRITICAL/HIGH) get fixed and re-reviewed
  automatically; opinions (MEDIUM/LOW) get numbered and left to **you**
- ⏱️ Runs at `git commit`, or the moment your coding agent finishes a turn —
  before you ever see the diff
- 🔓 No vendor lock-in: your rules live in a markdown file, checked into your
  own repo

Curious why the tools already on the market didn't fit? Read the
five-minute pitch in [docs/concept.md](docs/concept.md).

## 🚀 Example

Review what's staged, right before you commit:

```bash
inhousecode review
```

Review a teammate's pull request — no need to check it out:

```bash
inhousecode review --pr 1234
```

Either way you get one verdict, after both phases have run in order and
fixes have already been applied wherever they weren't a judgment call.

Full command reference: [docs/usage.md](docs/usage.md).

## 📊 For engineering leads — why adopt this

Evaluating this for a team rather than using it day to day? The case is written
out in full, in non-technical terms, in
**[docs/business-case.md](docs/business-case.md)** — share that page with a PM,
PO or budget holder. It answers:

| The question | Where it's answered |
|---|---|
| What problem does this solve, in business terms? | [The problem](docs/business-case.md#the-problem-in-one-paragraph) |
| What does it cost, and where's the saving? | [The cost picture](docs/business-case.md#the-cost-picture) — with a model you fill in using your own PR numbers |
| What's the return beyond the first quarter? | [The part that compounds](docs/business-case.md#the-part-that-compounds) |
| What does adopting it actually involve? | [Adoption and risk](docs/business-case.md#adoption-and-risk) — procurement, setup effort, rollback |
| How would we know it's working? | [What to measure](docs/business-case.md#what-to-measure) |
| How do we trial it safely? | [Suggested rollout](docs/business-case.md#suggested-rollout) — report-only first |
| Where does it fall short? | [Honest limitations](docs/business-case.md#honest-limitations) |

The short version: review moves *before* the commit instead of after the push,
the standard it enforces is one your team wrote down, there's no procurement and
no new vendor, and it's reversible by removing a single hook.

## ☁️ Managed cloud version

Everything else on this page describes the **self-hosted** tool: MIT-licensed,
free, and yours to run. For teams that would rather not run it themselves,
there is also a **managed cloud version of inhousecode** — a commercial
offering that adds:

- **Managed hosting** of the same two-phase pipeline — no local install, no
  Copilot CLI seats to administer
- **Org-wide shared rulebooks** — rules maintained centrally and applied across
  every repository, instead of one file per repo
- **A team dashboard** — findings over time, rule adoption, and spend per team
- **Commercial support, with an SLA**

Pricing depends on team size and repository count. To ask,
**[open an issue](https://github.com/iuf26/inhousecode/issues/new?title=Cloud%20enquiry)**
with a rough idea of your team size and how many repositories you'd want
covered, and we'll come back to you.

> The self-hosted version is not a trial or a limited tier. It is the complete
> gate, it stays that way, and the rulebook it enforces is always a plain file
> you own. See [self-hosted or managed](docs/business-case.md#self-hosted-or-managed)
> for a side-by-side.

## ⬇️ Installation

```bash
git clone https://github.com/iuf26/inhousecode.git && cd inhousecode
bash install.sh       # macOS / Linux / Git Bash
inhousecode doctor                      # confirms every dependency resolves
```

Then, in each repository you want reviewed:

```bash
inhousecode init && inhousecode install-hooks
```

**Requires:** git, Python 3, [Semgrep](https://semgrep.dev),
[Copilot CLI](https://github.com/github/copilot-cli), GNU `timeout`
(Windows: Git Bash).

Minimum versions, Windows steps, hook internals, and uninstalling:
[docs/installation.md](docs/installation.md). Config reference:
[docs/configuration.md](docs/configuration.md). First time setting this up?
Follow [docs/getting-started/](docs/getting-started/) page by page.

## 💭 How to contribute

Found a bug, have an idea, or disagree with a design choice? Open an issue —
this is early, and feedback shapes it more than anything else right now.

Before sending a pull request:

- Skim [AGENTS.md](AGENTS.md) for the project's invariants — several
  behaviors (like the review agent never getting write access) are
  load-bearing, not stylistic.
- Adding a config key touches the schema, the default, and
  [docs/configuration.md](docs/configuration.md) together — keep them in
  sync.
- Walk through [docs/testing.md](docs/testing.md) before opening the PR.

## 📖 Further reading

| | |
|---|---|
| [docs/](docs/) | Full documentation index |
| [docs/concept.md](docs/concept.md) | The problem, why we built this, why the name |
| [docs/business-case.md](docs/business-case.md) | For PMs, POs and eng managers: cost, adoption effort, long-term return, risks |
| [docs/design-principles.md](docs/design-principles.md) | Why static-then-AI, why severity splits authority, the two triggers |
| [docs/architecture.md](docs/architecture.md) | The pipeline, the finding contract, trust boundaries |
| [docs/comparison.md](docs/comparison.md) | vs. Claude Code Review and Copilot code review — cost, control, and what each wins on |
| [docs/team-customization.md](docs/team-customization.md) | Writing the rulebook, rolling it out to a team |

## License

MIT — see [LICENSE](LICENSE).
