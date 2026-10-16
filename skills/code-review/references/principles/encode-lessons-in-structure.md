# Encode repeated lessons in structure

*Meta — after the review, not a per-finding check. Reframed from
encode-lessons-in-structure for a reviewer.*

This is what to do when the *same* finding keeps recurring.

The checkable question: *am I writing this comment for the second time?*

- **A recurring finding is a missing rule.** If the same issue would be flagged
  across multiple PRs, it should become a durable rule, not prose repeated every
  review — a Semgrep pattern in the static config or a governed OpenViking
  candidate record (see the `[w]` capture flow at the blocked
  prompt).
- **Prefer the most mechanical home that fits:** a deterministic Semgrep rule
  over an approved project record over unverified candidate evidence. The point is that the lesson is
  checked automatically next time instead of relying on a reviewer to remember
  it.
