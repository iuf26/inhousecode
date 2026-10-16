"""End-to-end target resolution using a deterministic clean Semgrep stub."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "inhousecode"


class ReviewTargetMatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.bin = self.root / "bin"
        self.repo.mkdir()
        self.bin.mkdir()
        self._write_executable(
            "semgrep",
            """#!/usr/bin/env bash
set -eu
output=''
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then shift; output="$1"; fi
  shift
done
printf '%s\n' '{"results":[],"errors":[],"paths":{"scanned":[]}}' > "$output"
""",
        )
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        (self.repo / "app.py").write_text("VALUE = 1\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True)
        self.base = self._git("rev-parse", "HEAD")
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/project.git"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(["git", "switch", "-q", "-c", "feature"], cwd=self.repo, check=True)
        (self.repo / ".inhousecode").mkdir()
        (self.repo / ".inhousecode" / "config.json").write_text(
            json.dumps({"memory": {"enabled": False}})
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def _write_executable(self, name: str, content: str) -> Path:
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)
        return path

    def _review(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.bin}{os.pathsep}{env['PATH']}"
        env["NO_COLOR"] = "1"
        return subprocess.run(
            [str(CLI), "review", *args, "--mode", "static", "--no-fix", "--gate"],
            cwd=self.repo,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _assert_clean_review(self, result: subprocess.CompletedProcess[str], label: str):
        self.assertEqual(result.returncode, 0, f"{label}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertIn("Static analysis", result.stdout)
        self.assertIn("PASS", result.stdout)

    def test_staged_worktree_path_diff_and_pr_targets(self):
        (self.repo / "app.py").write_text("VALUE = 2\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.repo, check=True)
        self._assert_clean_review(self._review("--staged"), "staged")

        (self.repo / "app.py").write_text("VALUE = 3\n")
        self._assert_clean_review(self._review("--worktree"), "worktree")
        self._assert_clean_review(self._review("--path", "app.py"), "path")

        subprocess.run(["git", "add", "app.py"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "feature"], cwd=self.repo, check=True)
        head = self._git("rev-parse", "HEAD")
        self._assert_clean_review(self._review("--diff", self.base), "diff")

        self._write_executable(
            "gh",
            "#!/usr/bin/env bash\n"
            + "printf '%s\\n' "
            + repr(
                json.dumps(
                    {
                        "baseRefName": "main",
                        "headRefName": "feature",
                        "headRefOid": head,
                        "title": "Target matrix",
                        "url": "https://github.com/example/project/pull/7",
                        "body": "",
                    }
                )
            )
            + "\n",
        )
        self._assert_clean_review(self._review("--pr", "7"), "pr")


if __name__ == "__main__":
    unittest.main()
