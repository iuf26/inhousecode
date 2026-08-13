# Documentation

Start with whichever of these matches what you're trying to do.

## Understand it

| | |
|---|---|
| [concept.md](concept.md) | The pitch, no flags: the problem, why we built it, why the name |
| [business-case.md](business-case.md) | The same argument for a PM, PO or eng manager — cost, adoption, what compounds, and the honest limitations |
| [design-principles.md](design-principles.md) | Why static-then-AI, why severity splits authority, the two triggers |
| [architecture.md](architecture.md) | The pipeline, the finding contract, the trust boundaries |
| [comparison.md](comparison.md) | Claude Code Review vs. Copilot code review vs. inhousecode, and why a third thing exists |

## Set it up

| | |
|---|---|
| [getting-started/](getting-started/) | Five short pages: install → first review → first rule → hook → team rollout |
| [installation.md](installation.md) | Full install reference: Windows, hook internals, uninstalling |
| [usage.md](usage.md) | Every `review` flag, reviewing a PR, fixing a branch that isn't yours |
| [configuration.md](configuration.md) | Every option in `.inhousecode/config.json`, and what it costs you |

## Make it yours

| | |
|---|---|
| [team-customization.md](team-customization.md) | Writing the rulebook, `AGENTS.md` context, rolling out to a team |

## Verify it

| | |
|---|---|
| [testing.md](testing.md) | Step-by-step manual acceptance path — for contributors verifying a change to inhousecode itself, not for adopting it |

## Terms used across these docs

The same two-phase pipeline gets called different things depending on which
doc you're in — this is the mapping:

| Term | Refers to |
|---|---|
| Phase 1 / static / the static gate | Semgrep, the deterministic floor |
| Phase 2 / AI / the AI review | The model reading the diff and your rulebook |
| The gate | Either phase, or the pipeline as a whole — context disambiguates |

---

Back to the [project README](../README.md).
