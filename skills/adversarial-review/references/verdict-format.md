# Verdict format

The synthesis pass merges the lenses into one verdict. It emits the normalized
`##CR-FINDING##` lines (so the gate's one table, picker, and repair loop work
unchanged) AND the human-readable verdict below.

```
## Intent
<what the change is trying to achieve, one or two sentences>

## Verdict: PASS | CONTESTED | REJECT
<one-line summary>

## Findings
<for each surviving finding, ordered by severity (CRITICAL -> HIGH -> MEDIUM -> LOW)>
- **[severity]** description with file:line references
- Lens: which lens raised it (Skeptic / Architect / Minimalist / Operator)
- Principle: which engineering principle it maps to
- Recommendation: a concrete action, not vague advice

## What went well
<1-3 things the lenses found no issue with — acknowledge good work>

## Lead judgment
<for each finding: ACCEPT or REJECT, with a one-line rationale>
```

## Verdict logic

- **PASS** — no CRITICAL or HIGH findings survive the lead judgment.
- **CONTESTED** — CRITICAL/HIGH findings exist but the lenses or the lead
  judgment disagree on whether they hold.
- **REJECT** — CRITICAL/HIGH findings with agreement that they are real.

## What the synthesis may and may not do

The synthesis + lead judgment may **drop or downgrade** a lens's finding it can
disprove — the lenses are adversarial and overreach by design. It may **not
invent** a new finding or raise a severity beyond what a lens reported: a finding
that reached no lens would reach the developer critiqued by nobody. Drop only
what you read and disproved; a finding you cannot check stays. This mirrors the
"second opinion only subtracts" rule the fast gate already follows.
