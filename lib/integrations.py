#!/usr/bin/env python3
"""Install the inhousecode Agent Skill into supported harness homes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

SUPPORTED = ("hermes", "codex")
MARKER = "integration.json"
MANAGED_BY = "inhousecode"


class IntegrationError(RuntimeError):
    pass


def _target(harness: str, *, home: Path, hermes_home: Path) -> Path:
    if harness == "hermes":
        return hermes_home / "skills" / "inhousecode"
    if harness == "codex":
        return home / ".agents" / "skills" / "inhousecode"
    raise IntegrationError(f"unsupported harness: {harness}")


def _managed(path: Path) -> bool:
    marker = path / MARKER
    if not marker.is_file():
        return False
    try:
        return json.loads(marker.read_text(encoding="utf-8")).get("managed_by") == MANAGED_BY
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.is_dir():
        return ""
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def apply(
    action: str,
    harness: str,
    *,
    source: Path,
    home: Path,
    hermes_home: Path,
) -> dict:
    if action not in ("install", "status", "uninstall"):
        raise IntegrationError(f"unsupported integration action: {action}")
    if harness not in SUPPORTED:
        raise IntegrationError(f"unsupported integration harness: {harness}")
    target = _target(harness, home=home, hermes_home=hermes_home)

    if action == "status":
        if not target.exists():
            status = "not-installed"
        elif not _managed(target):
            status = "unmanaged"
        else:
            status = "current" if _digest(target) == _digest(source) else "outdated"
        return {"harness": harness, "status": status, "path": str(target)}

    if action == "uninstall":
        if not target.exists():
            return {"harness": harness, "status": "not-installed", "path": str(target)}
        if not _managed(target):
            raise IntegrationError(f"refusing to remove {target}: it is not managed by inhousecode")
        if _digest(target) != _digest(source):
            raise IntegrationError(
                f"refusing to remove {target}: the managed skill is locally edited or outdated"
            )
        shutil.rmtree(target)
        return {"harness": harness, "status": "removed", "path": str(target)}

    if not (source / "SKILL.md").is_file() or not _managed(source):
        raise IntegrationError(f"invalid inhousecode integration source: {source}")
    previous = "installed"
    if target.exists():
        if not _managed(target):
            raise IntegrationError(f"refusing to overwrite {target}: it is not managed by inhousecode")
        if _digest(target) == _digest(source):
            return {"harness": harness, "status": "current", "path": str(target)}
        shutil.rmtree(target)
        previous = "updated"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return {"harness": harness, "status": previous, "path": str(target)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "uninstall"))
    parser.add_argument("harness", choices=SUPPORTED)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args(argv)
    home = Path.home()
    hermes_home = Path(os.environ.get("HERMES_HOME", home / ".hermes"))
    try:
        result = apply(
            args.action,
            args.harness,
            source=args.source.resolve(),
            home=home,
            hermes_home=hermes_home,
        )
    except (IntegrationError, OSError) as error:
        print(f"inhousecode integration: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
