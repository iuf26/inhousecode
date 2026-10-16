"""`inhousecode static-check emit` / `inhousecode static-check consume`.

A harness (Hermes, Codex, ...) runs the printed Semgrep command through its
own command-execution tool, then hands the report back via `consume`. This
is the end-to-end CLI contract on top of lib/static_scan.sh's emit-only /
consume-mode support.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMGREP = shutil.which("semgrep")


class StaticCheckCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        (self.repo / "app.py").write_text(
            "import hashlib\n\ndef f(p):\n    return hashlib.md5(p.encode()).hexdigest()\n"
        )
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True)
        (self.repo / ".inhousecode").mkdir()
        (self.repo / ".inhousecode" / "config.json").write_text(
            json.dumps({"static": {"semgrepConfigs": ["p/python"]}})
        )
        # An uncommitted change so --worktree mode has something in scope.
        (self.repo / "app.py").write_text(
            "import hashlib\n\ndef f(p):\n    return hashlib.md5(p.encode()).hexdigest()\n\nx = 1\n"
        )

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(ROOT / "bin" / "inhousecode"), *args],
            cwd=str(self.repo),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_emit_prints_a_runnable_command_and_never_calls_semgrep(self):
        bin_dir = Path(self.tmp.name) / "stripped-bin"
        bin_dir.mkdir()
        for name in ("bash", "git", "sort", "grep", "sed", "mkdir", "rm", "cp",
                     "dirname", "tr", "python3", "env"):
            found = shutil.which(name)
            if found:
                (bin_dir / name).symlink_to(found)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:/bin:/usr/bin"
        result = subprocess.run(
            [str(ROOT / "bin" / "inhousecode"), "static-check", "emit", "--worktree"],
            cwd=str(self.repo), env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("semgrep", result.stdout)
        self.assertIn("inhousecode static-check consume --report", result.stdout)
        self.assertIn('"scan_status":"pending-external"', result.stdout)

    def test_emit_prints_consume_command_with_the_original_target_flags(self):
        # The printed consume command must include the same target flags the
        # emit was run with, or following it verbatim fails the (correct)
        # target-binding check in consume for any non-default target.
        (self.repo / "src").mkdir()
        (self.repo / "src" / "lib.py").write_text(
            "import hashlib\n\ndef f(p):\n    return hashlib.md5(p.encode()).hexdigest()\n"
        )
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add src"], cwd=self.repo, check=True)
        emit = self.run_cli("static-check", "emit", "--path", "src")
        self.assertEqual(emit.returncode, 0, emit.stderr)
        self.assertIn("static-check consume --report", emit.stdout)
        self.assertIn("--path src", emit.stdout)

    @unittest.skipUnless(SEMGREP, "semgrep not installed")
    def test_emit_then_consume_round_trip_finds_the_real_issue(self):
        emit = self.run_cli("static-check", "emit", "--worktree")
        self.assertEqual(emit.returncode, 0, emit.stderr)
        envelope = json.loads(emit.stdout.strip().splitlines()[-1])
        argv = envelope["external_argv"]
        semgrep_run = subprocess.run(argv, cwd=str(self.repo), text=True,
                                      capture_output=True, check=False)
        self.assertEqual(semgrep_run.returncode, 0, semgrep_run.stderr)

        consume = self.run_cli(
            "static-check", "consume", "--report", envelope["external_report"], "--worktree"
        )
        self.assertIn("insecure-hash-algorithm-md5", consume.stdout)
        # MEDIUM severity is non-blocking; the gate still surfaces the finding
        # and passes, as it would for the same finding from the in-process path.
        self.assertIn("STATIC-CHECK: PASS", consume.stdout)
        self.assertEqual(consume.returncode, 0)

    def test_consume_without_emit_first_is_a_usage_error(self):
        result = self.run_cli(
            "static-check", "consume", "--report", "/tmp/nonexistent-report.json", "--worktree"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("emit", result.stderr + result.stdout)

    def test_consume_missing_report_flag_is_a_usage_error(self):
        result = self.run_cli("static-check", "consume", "--worktree")
        self.assertEqual(result.returncode, 2)

    def test_consume_with_fabricated_clean_report_still_passes_through_validation(self):
        emit = self.run_cli("static-check", "emit", "--worktree")
        self.assertEqual(emit.returncode, 0, emit.stderr)
        envelope = json.loads(emit.stdout.strip().splitlines()[-1])
        Path(envelope["external_report"]).write_text(json.dumps({"results": [], "errors": []}))
        consume = self.run_cli(
            "static-check", "consume", "--report", envelope["external_report"], "--worktree"
        )
        self.assertEqual(consume.returncode, 0, consume.stderr)
        self.assertIn("STATIC-CHECK: PASS", consume.stdout)

    def test_consume_with_missing_report_blocks_rather_than_passes(self):
        emit = self.run_cli("static-check", "emit", "--worktree")
        self.assertEqual(emit.returncode, 0, emit.stderr)
        envelope = json.loads(emit.stdout.strip().splitlines()[-1])
        # Deliberately do not write the report -- simulates a harness that
        # emitted the command but never actually ran it.
        consume = self.run_cli(
            "static-check", "consume", "--report", envelope["external_report"], "--worktree"
        )
        self.assertNotEqual(consume.returncode, 0)
        self.assertIn("unavailable", consume.stdout.lower())

    def test_consume_rejects_a_target_mismatch_from_a_prior_emit(self):
        emit = self.run_cli("static-check", "emit", "--worktree")
        self.assertEqual(emit.returncode, 0, emit.stderr)
        envelope = json.loads(emit.stdout.strip().splitlines()[-1])
        Path(envelope["external_report"]).write_text(json.dumps({"results": [], "errors": []}))
        # Stage the change, then consume against --staged instead of the
        # --worktree target the emit was actually run for.
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        consume = self.run_cli(
            "static-check", "consume", "--report", envelope["external_report"], "--staged"
        )
        self.assertEqual(consume.returncode, 2)
        self.assertIn("different review", consume.stderr + consume.stdout)

    def test_consume_rejects_a_report_path_that_was_not_the_one_emit_named(self):
        emit = self.run_cli("static-check", "emit", "--worktree")
        self.assertEqual(emit.returncode, 0, emit.stderr)
        envelope = json.loads(emit.stdout.strip().splitlines()[-1])
        # A hand-written "clean" report at a different path must not be
        # accepted even though it is well-formed -- only the exact path
        # emit named for this scan is trusted.
        forged = Path(self.repo) / "forged-clean-report.json"
        forged.write_text(json.dumps({"results": [], "errors": []}))
        consume = self.run_cli("static-check", "consume", "--report", str(forged), "--worktree")
        self.assertEqual(consume.returncode, 2)
        self.assertIn("exact path printed", consume.stderr + consume.stdout)


if __name__ == "__main__":
    unittest.main()
