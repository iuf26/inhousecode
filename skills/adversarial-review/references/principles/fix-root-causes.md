# Fix root causes, not symptoms

*Skeptic lens.*

The best-suited lens for judging a proposed fix: is this patching the symptom or
the actual cause?

The checkable question: *does this address why the bad state arises, or just
hide it?*

- **A guard that silences a symptom** — a nil check hiding *why* the value is
  nil, a broad `except` swallowing an error class — is itself a finding. Ask why
  the bad state arises and say so.
- **The same bug in siblings.** If the change fixes one instance of a pattern
  and the codebase has others, the unfixed siblings are in scope — check for the
  pattern, not just the instance, and name them.
- **Own every file you touch.** A defect in the diff's blast radius is in scope
  even if the change did not introduce it; do not wave it off as "pre-existing".
