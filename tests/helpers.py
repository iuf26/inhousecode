"""Shared test scaffolding for the inhousecode Python test suite.

The scripts under ``lib/`` are standalone CLI entry points, not an installable
package, so tests load them by file path rather than via a normal import. This
also keeps a module named e.g. ``config`` from colliding with anything already
on ``sys.path``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIB_DIR = REPO_ROOT / "lib"


def load_module(name: str):
    """Load ``lib/<name>.py`` as a fresh module named ``inhousecode_<name>``."""
    module_name = f"inhousecode_{name}"
    path = LIB_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module
