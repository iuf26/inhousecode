"""Tests for lib/usage.py — parses the Copilot CLI JSONL log.

Two things a customer relies on here: the gate's own control flow parses
``extract_text`` output as if it were text-mode CLI output (so it must be
byte-exact to what text mode would have printed), and the cost figure in
``extract_usage`` is a spend report a developer or their manager may act on
directly, so it must never double-count.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import load_module  # noqa: E402

usage = load_module("usage")


def jsonl(*objects) -> str:
    import json

    return "\n".join(json.dumps(obj) for obj in objects) + "\n"


class ReadEventsTests(unittest.TestCase):
    def test_skips_non_json_lines(self):
        path = self._write("warning: something\n" + jsonl({"type": "x"}))
        events = usage.read_events(path)
        self.assertEqual(events, [{"type": "x"}])

    def test_skips_malformed_json(self):
        path = self._write('{"type": "x"\n' + jsonl({"type": "y"}))
        events = usage.read_events(path)
        self.assertEqual(events, [{"type": "y"}])

    def test_skips_json_that_is_not_an_object(self):
        path = self._write('[1, 2, 3]\n' + jsonl({"type": "y"}))
        events = usage.read_events(path)
        self.assertEqual(events, [{"type": "y"}])

    def _write(self, content: str) -> str:
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        handle.write(content)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name


class ExtractTextTests(unittest.TestCase):
    def test_prefers_final_answer_phase(self):
        events = [
            {"type": "assistant.message", "data": {"content": "thinking...", "phase": "draft"}},
            {"type": "assistant.message", "data": {"content": "the answer", "phase": "final_answer"}},
        ]
        self.assertEqual(usage.extract_text(events), "the answer")

    def test_falls_back_to_every_message_when_no_final_answer_flagged(self):
        events = [
            {"type": "assistant.message", "data": {"content": "part one"}},
            {"type": "assistant.message", "data": {"content": "part two"}},
        ]
        self.assertEqual(usage.extract_text(events), "part one\npart two")

    def test_ignores_non_assistant_events(self):
        events = [
            {"type": "session.usage_checkpoint", "data": {}},
            {"type": "assistant.message", "data": {"content": "hi", "phase": "final_answer"}},
        ]
        self.assertEqual(usage.extract_text(events), "hi")

    def test_ignores_events_with_empty_or_missing_content(self):
        events = [
            {"type": "assistant.message", "data": {"content": ""}},
            {"type": "assistant.message", "data": {}},
        ]
        self.assertEqual(usage.extract_text(events), "")

    def test_multiple_final_answer_events_are_joined(self):
        events = [
            {"type": "assistant.message", "data": {"content": "line1", "phase": "final_answer"}},
            {"type": "assistant.message", "data": {"content": "line2", "phase": "final_answer"}},
        ]
        self.assertEqual(usage.extract_text(events), "line1\nline2")


class ExtractUsageTests(unittest.TestCase):
    def test_usage_checkpoints_are_cumulative_so_only_the_max_counts(self):
        # Checkpoints report a running total for the session; summing them
        # would double-count everything before the last checkpoint.
        events = [
            {"type": "session.usage_checkpoint", "data": {"totalNanoAiu": 1000, "totalPremiumRequests": 1}},
            {"type": "session.usage_checkpoint", "data": {"totalNanoAiu": 2500, "totalPremiumRequests": 3}},
        ]
        nano, premium = usage.extract_usage(events)
        self.assertEqual(nano, 2500)
        self.assertEqual(premium, 3)

    def test_result_event_premium_requests_contributes(self):
        events = [
            {"type": "session.usage_checkpoint", "data": {"totalPremiumRequests": 1}},
            {"type": "result", "usage": {"premiumRequests": 4}},
        ]
        _, premium = usage.extract_usage(events)
        self.assertEqual(premium, 4)

    def test_missing_fields_default_to_zero(self):
        events = [{"type": "session.usage_checkpoint", "data": {}}]
        nano, premium = usage.extract_usage(events)
        self.assertEqual((nano, premium), (0, 0))

    def test_no_usage_events_returns_zero(self):
        events = [{"type": "assistant.message", "data": {"content": "hi"}}]
        self.assertEqual(usage.extract_usage(events), (0, 0))


class MainIntegrationTests(unittest.TestCase):
    def _write_log(self, *objects) -> str:
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        handle.write(jsonl(*objects))
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def _run(self, args):
        import contextlib
        import io

        old_argv = sys.argv
        sys.argv = ["usage.py", *args]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                exit_code = usage.main()
        finally:
            sys.argv = old_argv
        return exit_code, out.getvalue()

    def test_text_mode_prints_the_final_answer(self):
        path = self._write_log(
            {"type": "assistant.message", "data": {"content": "verdict: pass", "phase": "final_answer"}}
        )
        exit_code, out = self._run(["--log", path, "--mode", "text"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(out, "verdict: pass")

    def test_usage_mode_prints_tab_separated_nano_and_premium(self):
        path = self._write_log(
            {"type": "session.usage_checkpoint", "data": {"totalNanoAiu": 42, "totalPremiumRequests": 2}}
        )
        exit_code, out = self._run(["--log", path, "--mode", "usage"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(out.strip(), "42\t2")

    def test_missing_log_file_returns_error_exit_code(self):
        exit_code, _ = self._run(["--log", "/nonexistent/path.jsonl", "--mode", "text"])
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
