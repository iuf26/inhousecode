# Finding critique (rubber duck)

An adversarial pass over the reviewer's **own** draft findings, run before
anything is emitted. The verification pass argues that the code is wrong; this
pass argues the opposite, and only findings that survive get reported.

A gate that reports plausible-sounding issues that turn out not to exist gets
ignored, then disabled. **A false positive costs more than a missed MEDIUM.**

## Rules

- Read-only. Do not edit files, do not re-run the verifications, do not go
  hunting for *new* findings — this pass only removes and downgrades.
- Critique every draft finding, including your own high-confidence ones.
- Judge the code as written in the review source, not the code you assume is
  there. Re-read the cited line and enough surrounding code to settle the
  question.
- A finding you cannot ground in a specific line of the reviewed change is a
  DROP, not a MEDIUM.

## The four questions

Ask each one of every draft finding:

1. **Is it real?** Point at the exact line and explain the concrete mechanism by
   which it misbehaves. "This looks unsafe" is not a mechanism.
2. **Is it in scope?** Does the reviewed change introduce it, or is it
   pre-existing code the change merely sits next to? Pre-existing issues the
   change does not touch are DROP.
3. **Is it already handled?** Look for the guard, validation, caller contract,
   framework behavior, type constraint, or test that makes the concern moot. If
   a caller upstream in the same change already validates the input, the finding
   is dead.
4. **Is the severity honest?** Does the claimed impact follow from the
   mechanism, or from the category name? "Auth" in the category does not make a
   finding HIGH.

## Verdicts

Assign exactly one to each draft finding:

| Verdict | Meaning |
|---|---|
| **CONFIRMED** | Mechanism named, in scope, unguarded. Keep it, with its severity. |
| **DOWNGRADE** | Real but less impactful than drafted (guarded on the common path, bounded input, non-production path). Keep at the lower severity. |
| **DROP** | Not real, out of scope, already handled, or unverifiable from the change. Remove it. |

Bias toward DROP and DOWNGRADE. Two survivors that are certainly true beat six
that are probably true.

## Blocking findings need more

Before a finding stays CRITICAL or HIGH it must have, from the reviewed change:

- the specific line where the defect originates;
- the concrete consequence at runtime (what breaks, for whom, when);
- the reason no existing guard prevents it.

Missing any of the three: DOWNGRADE to MEDIUM, or DROP if the mechanism itself
does not hold. Blocking a commit is the strongest action this gate takes; it has
to be earned.

## Duplicates and stacking

- Two findings describing one defect at different lines are one finding — keep
  the one at the origin.
- A finding restating a rulebook violation already reported under its `id` is a
  DROP.
- Anything a pattern matcher would have caught is out of scope for this review
  and a DROP; the static gate already ran.

## Output

Report only the surviving findings, at their post-critique severity. Do not
emit the critique itself, the dropped findings, or the verdict table — the
report format is fixed and nothing else may appear in it.
