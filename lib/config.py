#!/usr/bin/env python3
"""Resolve inhousecode configuration and emit it as shell assignments.

Layering, lowest precedence first:

1. ``config/review.config.default.json`` shipped with the installation.
2. ``.inhousecode/config.json`` inside the reviewed repository (team-owned).

Only keys declared in the default document are honored; unknown keys are a hard
error so a typo never silently disables a gate. Values are type-checked and
range-checked against the same shape as the default document.

Usage:  config.py <install-root> <repo-root>
Output: ``KEY='value'`` lines suitable for ``eval`` in bash.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

REPO_CONFIG_RELPATH = Path(".inhousecode") / "config.json"
DEFAULT_CONFIG_RELPATH = Path("config") / "review.config.default.json"

# Bounds mirror config/review.config.schema.json. Keep the two in sync.
INTEGER_BOUNDS = {
    ("static", "maxFixLoops"): (0, 20),
    ("ai", "timeoutSec"): (30, 3600),
    ("ai", "maxFixLoops"): (0, 10),
    ("ai", "critiqueRounds"): (0, 5),
    ("agentStop", "maxTurns"): (1, 20),
    ("explain", "contextLines"): (0, 25),
}
# Keys that were renamed. Unknown keys are a hard error, so a rename would break
# every config in the wild; these are accepted silently and folded into the new
# name. Old name and new name in the same document is an error, not a merge --
# there is no sane precedence to pick.
RENAMED_KEYS = {
    ("ai", "triageNits"): "triageFindings",
}
# Semgrep config tokens are passed to a subprocess, so restrict them to a safe
# alphabet rather than trusting repository-supplied strings.
SEMGREP_CONFIG_ALPHABET = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
)
# Shell variables are named INHOUSECODE_<SECTION>_<KEY> in upper snake case.
SHELL_PREFIX = "INHOUSECODE"


class ConfigError(ValueError):
    """Raised when a configuration document violates the expected contract."""


def load_json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"could not read {label} ({path}): {error}") from error
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a JSON object")
    return value


def merge(defaults: dict, overrides: dict, trail: tuple[str, ...] = ()) -> dict:
    """Recursively overlay ``overrides`` on ``defaults``, validating as we go."""
    merged = dict(defaults)
    for key, override_value in overrides.items():
        if key == "$schema":
            continue
        path = trail + (key,)
        dotted = ".".join(path)
        renamed = RENAMED_KEYS.get(path)
        if renamed is not None:
            if renamed in overrides:
                raise ConfigError(
                    f"{dotted} was renamed to "
                    f"{'.'.join(trail + (renamed,))}; remove the old key"
                )
            key = renamed
            path = trail + (key,)
        if key not in defaults:
            raise ConfigError(f"unknown configuration key: {dotted}")
        default_value = defaults[key]
        if isinstance(default_value, dict):
            if not isinstance(override_value, dict):
                raise ConfigError(f"{dotted} must be an object")
            merged[key] = merge(default_value, override_value, path)
            continue
        merged[key] = validate_scalar(path, default_value, override_value)
    return merged


def validate_scalar(path: tuple[str, ...], default_value, value):
    dotted = ".".join(path)
    if isinstance(default_value, bool):
        if not isinstance(value, bool):
            raise ConfigError(f"{dotted} must be true or false")
        return value
    if isinstance(default_value, int):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{dotted} must be an integer")
        low, high = INTEGER_BOUNDS.get(path, (0, 10_000))
        if not low <= value <= high:
            raise ConfigError(f"{dotted} must be between {low} and {high}")
        return value
    if isinstance(default_value, list):
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ConfigError(f"{dotted} must be an array of strings")
        for item in value:
            if not item or set(item) - SEMGREP_CONFIG_ALPHABET:
                raise ConfigError(f"{dotted} contains an unsafe entry: {item!r}")
        return value
    if isinstance(default_value, str):
        if not isinstance(value, str):
            raise ConfigError(f"{dotted} must be a string")
        if any(ord(character) < 32 for character in value):
            raise ConfigError(f"{dotted} contains control characters")
        return value
    raise ConfigError(f"{dotted} has an unsupported default type")


def shell_name(path: tuple[str, ...]) -> str:
    parts = [SHELL_PREFIX]
    for segment in path:
        # camelCase -> UPPER_SNAKE so `static.maxFixLoops` reads as
        # INHOUSECODE_STATIC_MAX_FIX_LOOPS in the shell.
        snake = "".join(
            f"_{character}" if character.isupper() else character
            for character in segment
        )
        parts.append(snake.upper())
    return "_".join(parts)


def emit(config: dict, trail: tuple[str, ...] = ()) -> list[str]:
    lines: list[str] = []
    for key, value in config.items():
        if key == "$schema":
            continue
        path = trail + (key,)
        if isinstance(value, dict):
            lines.extend(emit(value, path))
            continue
        if isinstance(value, bool):
            rendered = "1" if value else "0"
        elif isinstance(value, list):
            rendered = " ".join(value)
        else:
            rendered = str(value)
        lines.append(f"{shell_name(path)}={shlex.quote(rendered)}")
    return lines


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: config.py <install-root> <repo-root>", file=sys.stderr)
        return 2
    install_root = Path(sys.argv[1])
    repo_root = Path(sys.argv[2])
    try:
        defaults = load_json_object(
            install_root / DEFAULT_CONFIG_RELPATH, "default configuration"
        )
        repo_config_path = repo_root / REPO_CONFIG_RELPATH
        overrides = (
            load_json_object(repo_config_path, "repository configuration")
            if repo_config_path.is_file()
            else {}
        )
        merged = merge(defaults, overrides)
    except ConfigError as error:
        print(f"inhousecode config: {error}", file=sys.stderr)
        return 1
    print("\n".join(emit(merged)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
