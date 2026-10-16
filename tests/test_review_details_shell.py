"""Shell integration for rich finding details in normal review output."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIEFING = """# inhousecode findings

---

## [1] MEDIUM - src/app.py:2 - project-rule

- Found by: AI review (phase 2) (advisory)
- Gate's one-line fix: Use the approved API.
- Rule source: promoted project knowledge
- Rule: Use the approved API.

Source, `src/app.py` (`>` marks line 2):

```text
  1 | before()
> 2 | old_api()
  3 | after()
```
"""


class ReviewDetailsShellTests(unittest.TestCase):
    def test_review_details_print_the_saved_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            briefing = repo / ".inhousecode" / "cache" / "last-briefing.md"
            briefing.parent.mkdir(parents=True)
            briefing.write_text(BRIEFING, encoding="utf-8")
            script = f"""
set -e
REPO_ROOT={str(repo)!r}
INHOUSECODE_HOME={str(ROOT)!r}
PYTHON_CMD=(python3)
source "$INHOUSECODE_HOME/lib/explain.sh"
explain_print_finding_details never
"""
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[1] MEDIUM — src/app.py:2", result.stdout)
        self.assertIn("🔴 > 2 | old_api()", result.stdout)


if __name__ == "__main__":
    unittest.main()