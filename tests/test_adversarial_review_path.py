"""The public adversarial review path reaches lenses and synthesis."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "inhousecode"


class AdversarialReviewPathTests(unittest.TestCase):
    def test_path_review_runs_lens_and_synthesis_through_public_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            bindir = root / "bin"
            repo.mkdir()
            bindir.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "app.py").write_text("VALUE = 1\n")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
            (repo / "app.py").write_text("VALUE = 2\n")
            (repo / ".inhousecode").mkdir()
            (repo / ".inhousecode" / "config.json").write_text(
                json.dumps(
                    {
                        "harness": "copilot",
                        "memory": {"enabled": False},
                        "ai": {"critiqueRounds": 0},
                    }
                )
            )
            copilot = bindir / "copilot"
            copilot.write_text(
                """#!/usr/bin/env python3
import json, sys
prompt = sys.argv[sys.argv.index('-p') + 1]
if 'LEAD reviewer synthesizing' in prompt:
    answer = 'CODE-REVIEW: PASS'
else:
    answer = 'No findings from this lens.'
print(json.dumps({'type': 'assistant.message', 'data': {'phase': 'final_answer', 'content': answer}}))
"""
            )
            copilot.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
            env["NO_COLOR"] = "1"
            result = subprocess.run(
                [
                    str(CLI),
                    "review",
                    "--path",
                    "app.py",
                    "--mode",
                    "ai",
                    "--adversarial",
                    "--no-fix",
                    "--gate",
                ],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Adversarial review: 1 lens(es) [skeptic]", result.stdout)
            self.assertIn("Adversarial review: synthesizing verdict", result.stdout)
            self.assertIn("AI code review", result.stdout)
            self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
