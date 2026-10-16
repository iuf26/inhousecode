"""The daily harvest schedule: launchd on macOS, cron elsewhere.

The scheduler is the only part of inhousecode that touches the user's
crontab or LaunchAgents, so every write is checked for: exact content, a
marker that scopes it to one repository, idempotent re-install, and removal
that never touches anything it did not create.
"""

from __future__ import annotations

import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import load_module  # noqa: E402

schedule = load_module("harvest_schedule")

REPO = Path("/Users/dev/src/payment service")  # space on purpose
BIN = Path("/opt/inhousecode/bin/inhousecode")
ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "OPENVIKING_CLI_CONFIG_FILE": "/Users/dev/.openviking/ovcli.conf"}


class FakeRunner:
    def __init__(self, crontab=""):
        self.crontab = crontab
        self.calls = []

    def __call__(self, argv, input_text=None):
        self.calls.append((list(argv), input_text))
        if argv[:2] == ["crontab", "-l"]:
            return (0, self.crontab) if self.crontab else (1, "")
        if argv[:1] == ["crontab"] and argv[1:] == ["-"]:
            self.crontab = input_text or ""
            return (0, "")
        return (0, "")


class LabelTests(unittest.TestCase):
    def test_label_is_stable_and_repository_specific(self):
        a = schedule.job_label(REPO)
        self.assertEqual(a, schedule.job_label(REPO))
        self.assertNotEqual(a, schedule.job_label(Path("/Users/dev/src/other")))
        self.assertRegex(a, r"^ai\.inhousecode\.harvest\.[0-9a-f]{12}$")


class LaunchdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agents = Path(self.tmp.name) / "LaunchAgents"
        self.logs = Path(self.tmp.name) / "logs"
        self.runner = FakeRunner()

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, hour=3, minute=15):
        return schedule.install_launchd(
            REPO, BIN, hour=hour, minute=minute, env=ENV,
            agents_dir=self.agents, log_dir=self.logs, runner=self.runner, uid=501,
        )

    def test_plist_runs_harvest_daily_with_absolute_paths(self):
        path = self.install()
        data = plistlib.loads(path.read_bytes())
        self.assertEqual(data["Label"], schedule.job_label(REPO))
        self.assertEqual(data["ProgramArguments"], [str(BIN), "memory", "harvest"])
        self.assertEqual(data["WorkingDirectory"], str(REPO))
        self.assertEqual(data["StartCalendarInterval"], {"Hour": 3, "Minute": 15})
        self.assertEqual(data["EnvironmentVariables"]["PATH"], ENV["PATH"])
        self.assertEqual(
            data["EnvironmentVariables"]["OPENVIKING_CLI_CONFIG_FILE"], ENV["OPENVIKING_CLI_CONFIG_FILE"]
        )
        self.assertFalse(data.get("RunAtLoad", False))
        self.assertTrue(data["StandardErrorPath"].startswith(str(self.logs)))

    def test_reinstall_replaces_instead_of_duplicating(self):
        self.install(hour=3)
        self.install(hour=4)
        plists = list(self.agents.glob("*.plist"))
        self.assertEqual(len(plists), 1)
        self.assertEqual(plistlib.loads(plists[0].read_bytes())["StartCalendarInterval"]["Hour"], 4)
        # bootout before every bootstrap so launchd never keeps a stale copy
        verbs = [c[0][1] for c in self.runner.calls if c[0][0] == "launchctl"]
        self.assertEqual(verbs, ["bootout", "bootstrap", "bootout", "bootstrap"])

    def test_uninstall_removes_only_its_own_plist(self):
        self.install()
        other = self.agents / "com.someone.else.plist"
        other.write_text("keep me")
        self.assertTrue(schedule.uninstall_launchd(REPO, agents_dir=self.agents, runner=self.runner, uid=501))
        self.assertEqual([p.name for p in self.agents.iterdir()], ["com.someone.else.plist"])

    def test_bad_time_is_rejected(self):
        with self.assertRaises(ValueError):
            self.install(hour=24)
        with self.assertRaises(ValueError):
            self.install(minute=60)


class CronTests(unittest.TestCase):
    def test_install_appends_one_marked_line_and_keeps_existing_entries(self):
        runner = FakeRunner(crontab="0 1 * * * /usr/bin/backup\n")
        schedule.install_cron(REPO, BIN, hour=3, minute=15, env=ENV, log_dir=Path("/tmp/l"), runner=runner)
        lines = runner.crontab.splitlines()
        self.assertIn("0 1 * * * /usr/bin/backup", lines)
        ours = [l for l in lines if schedule.job_label(REPO) in l]
        self.assertEqual(len(ours), 1)
        self.assertTrue(ours[0].startswith("15 3 * * * "))
        # paths with spaces must be quoted for /bin/sh
        self.assertIn("'/Users/dev/src/payment service'", ours[0])
        self.assertIn("memory harvest", ours[0])

    def test_reinstall_does_not_duplicate(self):
        runner = FakeRunner()
        for hour in (3, 5):
            schedule.install_cron(REPO, BIN, hour=hour, minute=0, env=ENV, log_dir=Path("/tmp/l"), runner=runner)
        ours = [l for l in runner.crontab.splitlines() if schedule.job_label(REPO) in l]
        self.assertEqual(len(ours), 1)
        self.assertTrue(ours[0].startswith("0 5 * * * "))

    def test_uninstall_leaves_other_lines(self):
        runner = FakeRunner(crontab="0 1 * * * /usr/bin/backup\n")
        schedule.install_cron(REPO, BIN, hour=3, minute=0, env=ENV, log_dir=Path("/tmp/l"), runner=runner)
        self.assertTrue(schedule.uninstall_cron(REPO, runner=runner))
        self.assertEqual(runner.crontab, "0 1 * * * /usr/bin/backup\n")
        self.assertFalse(schedule.uninstall_cron(REPO, runner=runner))


if __name__ == "__main__":
    unittest.main()
