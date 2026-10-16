"""Harness-native inhousecode skill installation is safe and reversible."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import load_module  # noqa: E402

integrations = load_module("integrations")
ROOT = Path(__file__).resolve().parents[1]
SHIPPED_SKILL = ROOT / "skills" / "inhousecode" / "SKILL.md"


SKILL = """---
name: inhousecode
description: Run governed inhousecode reviews from an AI harness.
---
# inhousecode
"""


class IntegrationTests(unittest.TestCase):
    def test_shipped_skill_preserves_sandbox_but_requests_openviking_network(self):
        content = SHIPPED_SKILL.read_text(encoding="utf-8")
        self.assertIn("request network permission", content)
        self.assertIn("Do not disable the filesystem sandbox", content)

    def test_shipped_skill_supports_the_demo_learning_flow(self):
        content = SHIPPED_SKILL.read_text(encoding="utf-8")
        self.assertIn("init\n  -> inhousecode init", content)
        self.assertIn("memory candidate add <text>", content)
        self.assertIn("memory classify <candidate-id>", content)

    def test_shipped_skill_supports_focused_finding_display(self):
        content = SHIPPED_SKILL.read_text(encoding="utf-8")
        self.assertIn("show <finding-number>", content)
        self.assertIn("inhousecode show <finding-number>", content)
        self.assertIn("Return its output verbatim", content)

    def test_shipped_skill_preserves_rich_review_output(self):
        content = SHIPPED_SKILL.read_text(encoding="utf-8")
        self.assertIn("For `review`: Return the complete output verbatim", content)
        self.assertIn("source excerpts", content)
        self.assertIn("highlighted problem-line markers", content)

    def test_shipped_skill_routes_memory_only_through_openviking_policy(self):
        content = SHIPPED_SKILL.read_text(encoding="utf-8")
        self.assertIn("remember | remeber | teach | store <text>", content)
        self.assertIn("inhousecode memory candidate add <text>", content)
        self.assertIn("Never call the harness's general memory tool", content)
        self.assertIn("quoted command payload, not a user-profile fact", content)
        self.assertIn("must not trigger any harness-native memory write", content)
        self.assertIn("never claim that a candidate is active knowledge", content)

    def test_shipped_skill_binds_commands_to_detected_repository_root(self):
        content = SHIPPED_SKILL.read_text(encoding="utf-8")
        self.assertIn("absolute path", content)
        self.assertIn("git -C", content)
        self.assertIn("working directory for every translated command", content)
        self.assertIn("do not rely on the harness process's current directory", content)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "SKILL.md").write_text(SKILL)
        (self.source / "integration.json").write_text(json.dumps({"managed_by": "inhousecode"}))
        self.hermes_home = self.root / "hermes"
        self.home = self.root / "home"

    def target(self, harness):
        if harness == "hermes":
            return self.hermes_home / "skills" / "inhousecode"
        return self.home / ".agents" / "skills" / "inhousecode"

    def call(self, action, harness):
        return integrations.apply(
            action,
            harness,
            source=self.source,
            home=self.home,
            hermes_home=self.hermes_home,
        )

    def test_installs_to_each_native_user_skill_directory(self):
        for harness in ("hermes", "codex"):
            with self.subTest(harness=harness):
                result = self.call("install", harness)
                self.assertEqual(result["status"], "installed")
                self.assertEqual((self.target(harness) / "SKILL.md").read_text(), SKILL)
                self.call("uninstall", harness)

    def test_status_distinguishes_missing_current_and_outdated(self):
        self.assertEqual(self.call("status", "hermes")["status"], "not-installed")
        self.call("install", "hermes")
        self.assertEqual(self.call("status", "hermes")["status"], "current")
        (self.target("hermes") / "SKILL.md").write_text(SKILL + "changed\n")
        self.assertEqual(self.call("status", "hermes")["status"], "outdated")

    def test_reinstall_updates_a_managed_copy(self):
        self.call("install", "codex")
        (self.target("codex") / "SKILL.md").write_text(SKILL + "old\n")
        result = self.call("install", "codex")
        self.assertEqual(result["status"], "updated")
        self.assertEqual((self.target("codex") / "SKILL.md").read_text(), SKILL)

    def test_refuses_to_overwrite_or_remove_an_unmanaged_skill(self):
        target = self.target("hermes")
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("personal")
        with self.assertRaisesRegex(integrations.IntegrationError, "not managed"):
            self.call("install", "hermes")
        with self.assertRaisesRegex(integrations.IntegrationError, "not managed"):
            self.call("uninstall", "hermes")
        self.assertEqual((target / "SKILL.md").read_text(), "personal")

    def test_uninstall_removes_only_the_managed_skill(self):
        self.call("install", "hermes")
        other = self.hermes_home / "skills" / "other" / "SKILL.md"
        other.parent.mkdir(parents=True)
        other.write_text("other")
        result = self.call("uninstall", "hermes")
        self.assertEqual(result["status"], "removed")
        self.assertFalse(self.target("hermes").exists())
        self.assertEqual(other.read_text(), "other")

    def test_uninstall_refuses_a_locally_edited_managed_skill(self):
        self.call("install", "hermes")
        target = self.target("hermes")
        (target / "SKILL.md").write_text(SKILL + "local edit\n")
        with self.assertRaisesRegex(integrations.IntegrationError, "locally edited"):
            self.call("uninstall", "hermes")
        self.assertTrue(target.exists())

    def test_shipped_skill_passes_adversarial_flag_through(self):
        content = SHIPPED_SKILL.read_text(encoding="utf-8")
        allowlist = content.split("Pass these review flags through unchanged", 1)[1]
        self.assertIn("`--adversarial`", allowlist)

    def test_rejects_unknown_harness_and_action(self):
        with self.assertRaisesRegex(integrations.IntegrationError, "harness"):
            self.call("install", "claude")
        with self.assertRaisesRegex(integrations.IntegrationError, "action"):
            self.call("explode", "hermes")


class IntegrationCliTests(unittest.TestCase):
    def test_install_status_and_uninstall_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["HOME"] = str(Path(tmp) / "home")
            env["HERMES_HOME"] = str(Path(tmp) / "hermes")
            command = [str(ROOT / "bin" / "inhousecode"), "integrate"]
            for action in ("install", "status", "uninstall"):
                result = subprocess.run(
                    [*command, action, "all"], env=env, text=True,
                    capture_output=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
                self.assertEqual({line["harness"] for line in lines}, {"hermes", "codex"})


if __name__ == "__main__":
    unittest.main()
