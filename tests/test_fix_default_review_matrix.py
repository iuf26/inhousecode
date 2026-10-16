"""Live CLI repair-policy matrix with deterministic scanner and fixer stubs."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "inhousecode"


class FixDefaultReviewMatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.bin = self.root / "bin"
        self.repo.mkdir()
        self.bin.mkdir()
        self._write_executable(
            "semgrep",
            """#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
out = pathlib.Path(args[args.index('-o') + 1])
target = pathlib.Path(args[-1])
source = target / 'app.py'
results = []
if source.exists() and 'BAD' in source.read_text():
    results.append({
        'check_id': 'test.bad-value',
        'path': str(source),
        'start': {'line': 1},
        'extra': {'severity': 'ERROR', 'message': 'Replace BAD.', 'fix': 'Use GOOD.'},
    })
out.write_text(json.dumps({'results': results, 'errors': []}))
""",
        )
        self._write_executable(
            "copilot",
            """#!/usr/bin/env python3
from pathlib import Path
path = Path('app.py')
path.write_text(path.read_text().replace('BAD', 'GOOD'))
""",
        )
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        (self.repo / "app.py").write_text("VALUE = 'GOOD'\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True)
        self.base = self._git("rev-parse", "HEAD")
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/project.git"],
            cwd=self.repo,
            check=True,
        )
        (self.repo / ".inhousecode").mkdir()
        self._set_fix_default(True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_executable(self, name: str, content: str) -> Path:
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)
        return path

    def _git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def _set_fix_default(self, enabled: bool):
        (self.repo / ".inhousecode" / "config.json").write_text(
            json.dumps(
                {
                    "harness": "copilot",
                    "review": {"fixByDefault": enabled},
                    "memory": {"enabled": False},
                    "ai": {"enabled": False},
                    "static": {"maxFixLoops": 2},
                }
            )
        )

    def _review(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.bin}{os.pathsep}{env['PATH']}"
        env["NO_COLOR"] = "1"
        return subprocess.run(
            [str(CLI), "review", *args, "--mode", "static", "--gate"],
            cwd=self.repo,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _make_bad_worktree(self, staged: bool = False):
        (self.repo / "app.py").write_text("VALUE = 'BAD'\n")
        if staged:
            subprocess.run(["git", "add", "app.py"], cwd=self.repo, check=True)

    def _make_bad_feature_commit(self) -> str:
        subprocess.run(["git", "switch", "-q", "-c", "feature"], cwd=self.repo, check=True)
        self._make_bad_worktree(staged=True)
        subprocess.run(["git", "commit", "-qm", "feature"], cwd=self.repo, check=True)
        return self._git("rev-parse", "HEAD")

    def _assert_repaired(self, result: subprocess.CompletedProcess[str], label: str):
        self.assertEqual(result.returncode, 0, f"{label}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 'GOOD'\n")
        self.assertIn("Static repair round 1/2", result.stdout)

    def test_fix_by_default_repairs_staged_worktree_path_diff_and_pr(self):
        cases = ("staged", "worktree", "path", "diff", "pr")
        for target in cases:
            with self.subTest(target=target):
                if target == "staged":
                    self._make_bad_worktree(staged=True)
                    result = self._review("--staged")
                    self._assert_repaired(result, target)
                    self.assertIn("GOOD", self._git("show", ":app.py"))
                elif target == "worktree":
                    self._make_bad_worktree()
                    self._assert_repaired(self._review("--worktree"), target)
                elif target == "path":
                    self._make_bad_worktree()
                    self._assert_repaired(self._review("--path", "app.py"), target)
                else:
                    head = self._make_bad_feature_commit()
                    if target == "diff":
                        result = self._review("--diff", self.base)
                    else:
                        self._install_gh(head)
                        result = self._review("--pr", "7")
                    self._assert_repaired(result, target)
                subprocess.run(["git", "reset", "--hard", "-q", self.base], cwd=self.repo, check=True)
                if self._git("branch", "--show-current") != "main":
                    subprocess.run(["git", "switch", "-q", "main"], cwd=self.repo, check=True)
                subprocess.run(["git", "branch", "-D", "feature"], cwd=self.repo, check=False, capture_output=True)

    def _install_gh(self, head: str):
        document = json.dumps(
            {
                "baseRefName": "main",
                "headRefName": "feature",
                "headRefOid": head,
                "title": "Repair matrix",
                "url": "https://github.com/example/project/pull/7",
                "body": "",
            }
        )
        self._write_executable("gh", f"#!/usr/bin/env bash\nprintf '%s\\n' {document!r}\n")

    def test_explicit_no_fix_wins_in_both_flag_orders(self):
        for flags in (("--fix", "--no-fix"), ("--no-fix", "--fix")):
            with self.subTest(flags=flags):
                self._make_bad_worktree()
                result = self._review("--worktree", *flags)
                self.assertEqual(result.returncode, 1)
                self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 'BAD'\n")
                self.assertNotIn("Static repair round", result.stdout)
                subprocess.run(["git", "reset", "--hard", "-q"], cwd=self.repo, check=True)

    def test_explicit_fix_enables_all_finding_repair_when_default_is_off(self):
        self._set_fix_default(False)
        self._make_bad_worktree()
        self._assert_repaired(self._review("--worktree", "--fix"), "explicit --fix")

    def test_pr_default_fix_is_refused_when_reviewed_head_is_not_checked_out(self):
        head = self._make_bad_feature_commit()
        subprocess.run(["git", "switch", "-q", "main"], cwd=self.repo, check=True)
        self._install_gh(head)
        result = self._review("--pr", "7")
        self.assertEqual(result.returncode, 1)
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 'GOOD'\n")
        self.assertIn("repairs are disabled", result.stderr)
        self.assertNotIn("Static repair round", result.stdout)


if __name__ == "__main__":
    unittest.main()
