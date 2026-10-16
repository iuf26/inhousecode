"""lib/static_scan.sh emit-only / consume-mode contract.

A harness (Hermes, Codex, ...) should be able to run the deterministic
Semgrep command itself, through its own command-execution tool, instead of
inhousecode invoking it as a hidden subprocess. These modes let an external
caller take over exactly the semgrep invocation while inhousecode still owns
file materialization and report validation -- the "malformed report is never
a pass" invariant must hold identically either way.
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


def run_scan(env_overrides: dict[str, str], cwd: Path) -> dict:
    env = os.environ.copy()
    env.update(env_overrides)
    env["INHOUSECODE_HOME"] = str(ROOT)
    result = subprocess.run(
        ["bash", str(ROOT / "lib" / "static_scan.sh")],
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class EmitOnlyModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        (self.repo / "app.py").write_text("import hashlib\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True)
        # An uncommitted change so worktree mode has something in scope.
        (self.repo / "app.py").write_text("import hashlib\nx = 1\n")
        self.cache = Path(self.tmp.name) / "cache"
        self.cache.mkdir()

    def test_emit_only_never_invokes_semgrep_itself(self):
        # Strip semgrep from PATH entirely. If emit-only mode tried to run it,
        # this would fail with "semgrep not found"; it must not even try.
        bin_dir = Path(self.tmp.name) / "stripped-bin"
        bin_dir.mkdir()
        for name in ("bash", "git", "sort", "grep", "sed", "mkdir", "rm", "cp", "dirname", "tr"):
            found = shutil.which(name)
            if found:
                (bin_dir / name).symlink_to(found)
        envelope = run_scan(
            {
                "INHOUSECODE_STATIC_EMIT_ONLY": "1",
                "INHOUSECODE_TARGET_MODE": "worktree",
                "INHOUSECODE_CACHE_ROOT": str(self.cache),
                "PATH": f"{bin_dir}:/bin:/usr/bin",
            },
            cwd=self.repo,
        )
        self.assertEqual(envelope["scan_status"], "pending-external")
        self.assertIsInstance(envelope["external_argv"], list)
        self.assertIn("semgrep", envelope["external_argv"])
        self.assertNotEqual(envelope["external_report"], "none")
        self.assertTrue(Path(envelope["scan_target"]).is_dir())
        self.assertTrue((Path(envelope["scan_target"]) / "app.py").is_file())

    def test_emitted_command_is_the_real_scan_command(self):
        envelope = run_scan(
            {
                "INHOUSECODE_STATIC_EMIT_ONLY": "1",
                "INHOUSECODE_TARGET_MODE": "worktree",
                "INHOUSECODE_SEMGREP_CONFIGS": "p/python",
                "INHOUSECODE_CACHE_ROOT": str(self.cache),
            },
            cwd=self.repo,
        )
        argv = envelope["external_argv"]
        self.assertIn("--config", argv)
        self.assertIn("p/python", argv)
        self.assertIn("--json", argv)
        self.assertIn("-o", argv)
        self.assertEqual(argv[-1], envelope["scan_target"])

    def test_skipped_when_nothing_to_scan(self):
        # Reset the worktree-dirtying mutation from setUp, then stage only a
        # prose file -- nothing eligible for Semgrep.
        subprocess.run(["git", "checkout", "--", "app.py"], cwd=self.repo, check=True)
        (self.repo / "README.md").write_text("docs\n")
        subprocess.run(["git", "add", "README.md"], cwd=self.repo, check=True)
        envelope = run_scan(
            {
                "INHOUSECODE_STATIC_EMIT_ONLY": "1",
                "INHOUSECODE_TARGET_MODE": "staged",
                "INHOUSECODE_CACHE_ROOT": str(self.cache),
            },
            cwd=self.repo,
        )
        self.assertEqual(envelope["scan_status"], "skipped")
        self.assertIsNone(envelope["external_argv"])


class ConsumeModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        (self.repo / "app.py").write_text("import hashlib\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True)
        # An uncommitted change so worktree mode has something in scope.
        (self.repo / "app.py").write_text("import hashlib\nx = 1\n")
        self.cache = Path(self.tmp.name) / "cache"
        self.cache.mkdir()
        self.envelope = run_scan(
            {
                "INHOUSECODE_STATIC_EMIT_ONLY": "1",
                "INHOUSECODE_TARGET_MODE": "worktree",
                "INHOUSECODE_CACHE_ROOT": str(self.cache),
            },
            cwd=self.repo,
        )

    def consume(self, report_path: str) -> dict:
        return run_scan(
            {
                "INHOUSECODE_STATIC_CONSUME_MODE": "1",
                "INHOUSECODE_STATIC_CONSUME_REPORT": report_path,
                "INHOUSECODE_TARGET_MODE": "worktree",
                "INHOUSECODE_CACHE_ROOT": str(self.cache),
            },
            cwd=self.repo,
        )

    def test_clean_externally_produced_report_is_completed(self):
        report = Path(self.envelope["external_report"])
        report.write_text(json.dumps({"results": [], "errors": []}))
        envelope = self.consume(str(report))
        self.assertEqual(envelope["scan_status"], "completed")
        self.assertEqual(envelope["semgrep_json"], str(report))

    def test_missing_report_is_unavailable_not_a_pass(self):
        envelope = self.consume(str(Path(self.envelope["external_report"]).with_suffix(".absent")))
        self.assertEqual(envelope["scan_status"], "unavailable")
        self.assertIn("was not run", envelope["scan_reason"])

    def test_report_with_scan_errors_is_unavailable(self):
        report = Path(self.envelope["external_report"])
        report.write_text(json.dumps({"results": [], "errors": [{"message": "boom"}]}))
        envelope = self.consume(str(report))
        self.assertEqual(envelope["scan_status"], "unavailable")

    def test_empty_report_file_is_unavailable(self):
        report = Path(self.envelope["external_report"])
        report.write_text("")
        envelope = self.consume(str(report))
        self.assertEqual(envelope["scan_status"], "unavailable")

    def test_scan_tree_changing_after_emit_is_detected_as_stale(self):
        report = Path(self.envelope["external_report"])
        report.write_text(json.dumps({"results": [], "errors": []}))
        # Mutate a file inside the already-materialized scan tree, simulating
        # the tree changing out from under a stale cache directory.
        scan_tree = Path(self.envelope["scan_target"])
        target_file = next(scan_tree.rglob("*.py"))
        target_file.write_text(target_file.read_text() + "\nx = 2\n")
        envelope = self.consume(str(report))
        self.assertEqual(envelope["scan_status"], "unavailable")
        self.assertIn("changed since", envelope["scan_reason"])

    def test_missing_scan_tree_hash_fails_closed_not_open(self):
        report = Path(self.envelope["external_report"])
        report.write_text(json.dumps({"results": [], "errors": []}))
        # Delete the recorded hash -- a corrupted or hand-assembled cache
        # directory must never be treated as an automatic match.
        hash_file = Path(self.envelope["cache_root"]) / "static-external" / "scan-tree.sha256"
        hash_file.unlink()
        envelope = self.consume(str(report))
        self.assertEqual(envelope["scan_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
