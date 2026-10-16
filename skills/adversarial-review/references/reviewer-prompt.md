# Reviewer prompt template

The gate builds each lens reviewer's prompt from these parts. One reviewer, one
lens, one model invocation:

1. **The stated intent** (from Step 2) — what the change is trying to achieve.
2. **The assigned lens** — the full text of that lens from
   [reviewer-lenses.md](reviewer-lenses.md).
3. **The principles relevant to that lens** — the actual file contents of the
   principle files that lens maps to (the `Maps to:` links in
   [reviewer-lenses.md](reviewer-lenses.md), each a file under
   [`principles/`](principles/)), not a summary.
4. **The frozen OpenViking review-memory snapshot**, when supplied — a lens
   finding must not contradict a documented team preference.
5. **The code or diff to review**, plus the file list.
6. **The instruction block**, verbatim:

   > You are an adversarial reviewer. Your job is to find real problems, not to
   > validate the work. Adopt your assigned lens exclusively; do not try to be
   > balanced. Be specific — cite `file:line` and a concrete failure scenario for
   > every finding. Do not invent problems to fill a quota: a lens that finds
   > nothing real says so. Rate each finding CRITICAL, HIGH, MEDIUM, or LOW.
   > Emit each finding as a `##CR-FINDING##` line (see the finding contract in
   > SKILL.md), and nothing that is not either a finding line or brief
   > supporting prose.

All lenses are spawned in parallel by the gate, each writing to its own output.
