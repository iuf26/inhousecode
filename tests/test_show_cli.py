"""CLI coverage for focused finding display."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "inhousecode"
BRIEFING = """# inhousecode findings

---

## [1] MEDIUM - src/app.py:2 - project-rule

- Found by: AI review (phase 2) (advisory)
- Gate's one-line fix: Use the approved API.
- Rule source: promoted project knowledge
- Rule: Use the approved API.
- Memory record: `project-rule`

Source, `src/app.py` (`>` marks line 2):

```text
  1 | before()
> 2 | old_api()
  3 | after()
```
"""


class ShowCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        cache = self.repo / ".inhousecode" / "cache"
        cache.mkdir(parents=True)
        (cache / "last-briefing.md").write_text(BRIEFING, encoding="utf-8")

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(CLI), *args], cwd=self.repo, text=True,
            capture_output=True, check=False,
        )

    def test_show_prints_focused_excerpt_without_model(self):
        result = self.run_cli("show", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[1] MEDIUM — src/app.py:2", result.stdout)
        self.assertIn("Rule source: promoted project knowledge", result.stdout)
        self.assertIn("🔴 > 2 | old_api()", result.stdout)

    def test_show_rejects_unknown_number(self):
        result = self.run_cli("show", "9")
        self.assertEqual(result.returncode, 2)
        self.assertIn("finding 9 is not available", result.stderr)


if __name__ == "__main__":
    unittest.main()
