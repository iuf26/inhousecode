"""Focused finding display for terminal and harness integrations."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import load_module  # noqa: E402

finding_view = load_module("finding_view")


BRIEFING = """# inhousecode findings

---

## [1] MEDIUM - src/user_service.py:36 - project-select-columns

- Found by: AI review (phase 2) (advisory)
- Gate's one-line fix: Select only needed columns.
- Rule source: promoted project knowledge
- Rule: Queries must name their columns; SELECT * is not allowed.
- Memory record: `project-select-columns`

Source, `src/user_service.py` (`>` marks line 36):

```text
  34 | cursor = conn.cursor()
> 36 | cursor.execute("SELECT * FROM users")
  37 | return cursor.fetchone()
```

---

## [2] HIGH - src/user_service.py:68 - Password Storage

- Rule source: built-in AI review guidance
"""


class FindingViewTests(unittest.TestCase):
    def test_selects_one_numbered_finding(self):
        section = finding_view.select_finding(BRIEFING, 1)
        self.assertIn("src/user_service.py:36", section)
        self.assertNotIn("src/user_service.py:68", section)

    def test_plain_display_marks_problem_line_and_keeps_rule_provenance(self):
        output = finding_view.render_finding(BRIEFING, 1, color=False)
        self.assertIn("[1] MEDIUM — src/user_service.py:36", output)
        self.assertIn("Rule source: promoted project knowledge", output)
        self.assertIn("Rule: Queries must name their columns", output)
        self.assertIn("🔴 > 36 |", output)

    def test_colored_display_uses_ansi_red_on_problem_line(self):
        output = finding_view.render_finding(BRIEFING, 1, color=True)
        self.assertIn("\x1b[1;97;41m", output)
        self.assertIn('> 36 | cursor.execute("SELECT * FROM users")', output)
        self.assertIn("\x1b[0m", output)

    def test_full_review_display_renders_every_finding_with_stable_numbers(self):
        output = finding_view.render_findings(BRIEFING, color=False)

        self.assertIn("[1] MEDIUM — src/user_service.py:36", output)
        self.assertIn("🔴 > 36 |", output)
        self.assertIn("[2] HIGH — src/user_service.py:68", output)
        self.assertEqual(output.count("[1] MEDIUM"), 1)
        self.assertEqual(output.count("[2] HIGH"), 1)

    def test_unknown_finding_number_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "finding 9 is not available"):
            finding_view.render_finding(BRIEFING, 9, color=False)


if __name__ == "__main__":
    unittest.main()
