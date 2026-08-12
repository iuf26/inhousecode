# The second opinion

The reviewer critiques its own drafts before emitting them (Step 5). That pass
is necessary and not sufficient. A model arguing against a conclusion it reached
minutes ago shares every assumption that produced it, and agrees with itself far
more readily than a stranger would. Hallucinated findings survive self-review
precisely *because* the same reasoning generated them and then blessed them.

So the emitted findings go to a **different model**, running read-only, which
has never seen the reasoning behind them. It has two jobs and no others.

## Job 1 — check the findings

Read the cited line and enough surrounding code to settle the question. Then, per
finding:

| Verdict | Meaning |
|---|---|
| **CONFIRM** | Real, introduced by this change, unguarded, honestly severed. Keep unchanged. |
| **DOWNGRADE** | Real but less impactful than drafted. Keep at the lower severity. |
| **DROP** | Not real, out of scope, already guarded, or ungroundable in the change. |

The critic is **strictly subtractive**: it never adds a finding, never hunts for
new ones, and never raises a severity. A critic that can add findings is just a
second reviewer whose own output nobody checked — and its findings would reach
the developer having been critiqued by no one.

Before a finding stays CRITICAL or HIGH it needs all three of: the origin line,
the concrete runtime consequence, and why no existing guard prevents it. Missing
one — DOWNGRADE. Missing the mechanism itself — DROP.

**Drop means disproved, not unread.** A finding is dropped only after the code
was read and did not support it. If a file cannot be opened or a read is denied,
the finding is CONFIRMED unchanged. Otherwise a critic that cannot see the
source empties the report and hands back a clean verdict — the single outcome
this pass must never produce, and the reason "I could not verify it" is not a
verdict.

## Job 2 — report misdeclarations

Some findings are not wrong so much as wrongly *stated*, and dropping them would
throw away a real concern. The critic flags these and stops there.

| Issue | Meaning |
|---|---|
| `WRONG-LINE` | The cited `file:line` does not contain the code described. |
| `WRONG-SEVERITY` | The severity does not follow from the mechanism, and the fix is not simply "lower it". |
| `UNPROVEN` | The mechanism is asserted rather than demonstrated, but may be real once grounded. |
| `MISCATEGORIZED` | The category or rulebook rule id does not match the defect. |
| `DUPLICATE` | Two findings describe one defect; name the origin. |
| `VAGUE-FIX` | The fix is not a specific, imperative, single action. |

A dropped finding never carries a misdeclaration. It is gone; there is nothing
left to correct.

## Correcting them

The misdeclarations go back to the **original reviewer**, because rewriting
another agent's finding is exactly the boundary that keeps the critic subtractive.
For each correction, do one of:

- restate it correctly — right line, severity, category, or a specific imperative
  fix — and keep it;
- ground the mechanism concretely, if it is real but was only asserted;
- drop it, if going back to the code shows it does not hold.

**Correcting a finding means proving it, not rewording it.** If you cannot point
at the line and say what goes wrong at runtime, drop it. Dropping is a
legitimate and frequently correct outcome of a correction round — a finding that
survives two rounds of rewording without ever being grounded is a finding that
was never real.

Do not add findings, do not re-review the change, and do not restore anything
the second reviewer dropped.

## Bounds

The loop is capped by `ai.critiqueRounds` (default 2). Each round is two more
model invocations, and the loop must terminate whether or not the two agents
ever converge. When the budget runs out with corrections outstanding, the
critiqued report stands and the outstanding items are printed — an unresolved
disagreement is shown to the developer, not silently resolved in either
direction.

## Failure

A critique that times out, exits non-zero, or comes back malformed **keeps the
findings it was asked to judge**. This is the only safe direction, and it is
safe by construction: the critique can only subtract, so losing it leaves more
findings standing, never fewer. Failing the gate instead would block a commit on
the failure of a pass whose entire purpose is to unblock things that were never
real.

The claim table (`##CR-CLAIM##`) is carried across every round by the caller, not
by either agent. A checklist that quietly loses rows each time a critic passes
over it would be a report that gets less true the harder it is checked.
