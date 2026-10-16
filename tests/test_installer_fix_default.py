"""Installer contracts for the opt-in default repair policy."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ShellInstallerFixDefaultTests(unittest.TestCase):
    def test_shell_installer_can_enable_fix_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "checkout"
            (checkout / "config").mkdir(parents=True)
            shutil.copy2(ROOT / "install.sh", checkout / "install.sh")
            config_path = checkout / "config" / "review.config.default.json"
            config_path.write_text(
                json.dumps(
                    {
                        "harness": "copilot",
                        "review": {"fixByDefault": False},
                        "adversarial": {
                            "enabled": False,
                            "model": "",
                            "maxLenses": 4,
                        },
                    }
                )
            )
            result = subprocess.run(
                [
                    "bash",
                    str(checkout / "install.sh"),
                    "--bin-dir",
                    str(Path(tmp) / "bin"),
                    "--harness",
                    "codex",
                    "--fix-by-default",
                    "--no-semgrep",
                    "--no-timeout",
                    "--no-adversarial",
                    "--non-interactive",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads(config_path.read_text())
            self.assertTrue(config["review"]["fixByDefault"])
            self.assertIn("Fix findings by default: enabled", result.stdout)
            self.assertNotIn("rulebook", result.stdout.lower())
            self.assertIn("creates .inhousecode/ configuration", result.stdout)


class PowerShellInstallerFixDefaultContractTests(unittest.TestCase):
    def test_powershell_installer_exposes_and_writes_fix_by_default(self):
        script = (ROOT / "install.ps1").read_text()
        self.assertIn("[switch]$FixByDefault", script)
        self.assertIn("[switch]$NoFixByDefault", script)
        self.assertIn("$cfg.review.fixByDefault", script)
        self.assertIn("Fix findings by default", script)
        self.assertNotIn("rulebook", script.lower())


if __name__ == "__main__":
    unittest.main()
