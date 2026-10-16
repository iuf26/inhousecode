#!/usr/bin/env python3
"""Install or remove the daily ``inhousecode memory harvest`` schedule.

macOS uses a per-user LaunchAgent; everything else uses the user's crontab.
This is the only code in inhousecode that edits either, so it is deliberately
narrow:

- One job per repository, identified by a label derived from the repository
  path. Re-installing replaces it; it never accumulates duplicates.
- Removal touches only what carries that exact label.
- Absolute paths and an explicit PATH, because launchd and cron start jobs
  with a minimal environment that would not find ``ov``, ``python3``, or git.
- No secrets are written. Only the path of the OpenViking CLI config is
  carried over, never its contents.

Usage:
  harvest_schedule.py install   <repo-root> <inhousecode-bin> [--hour H] [--minute M] [--backend B]
  harvest_schedule.py uninstall <repo-root> [--backend B]
  harvest_schedule.py status    <repo-root> [--backend B]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable

LABEL_PREFIX = "ai.inhousecode.harvest."
DEFAULT_HOUR = 3
DEFAULT_MINUTE = 15
# Only these variables are carried into the job's environment. PATH so the job
# finds ov/python3/git; the OpenViking variables so it talks to the same
# server; the session-user override so harvest reads the right user.
PASSTHROUGH_ENV = (
    "PATH",
    "OPENVIKING_CLI_CONFIG_FILE",
    "OV_BIN",
    "INHOUSECODE_OV_SESSION_USER",
)
FALLBACK_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

Runner = Callable[..., "tuple[int, str]"]


def default_runner(argv: list[str], input_text: str | None = None) -> tuple[int, str]:
    result = subprocess.run(argv, input=input_text, text=True, capture_output=True, check=False)
    return result.returncode, result.stdout


def job_label(repo_root: Path) -> str:
    digest = hashlib.sha256(str(Path(repo_root)).encode("utf-8")).hexdigest()[:12]
    return LABEL_PREFIX + digest


def _check_time(hour: int, minute: int) -> None:
    if not 0 <= hour <= 23:
        raise ValueError("hour must be between 0 and 23")
    if not 0 <= minute <= 59:
        raise ValueError("minute must be between 0 and 59")


def job_environment(env: dict[str, str]) -> dict[str, str]:
    carried = {key: env[key] for key in PASSTHROUGH_ENV if env.get(key)}
    carried.setdefault("PATH", FALLBACK_PATH)
    return carried


# --- launchd -----------------------------------------------------------------


def _plist_path(agents_dir: Path, label: str) -> Path:
    return agents_dir / (label + ".plist")


def install_launchd(
    repo_root: Path,
    bin_path: Path,
    *,
    hour: int,
    minute: int,
    env: dict[str, str],
    agents_dir: Path,
    log_dir: Path,
    runner: Runner = default_runner,
    uid: int | None = None,
) -> Path:
    _check_time(hour, minute)
    label = job_label(repo_root)
    domain = f"gui/{os.getuid() if uid is None else uid}"
    agents_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": label,
        "ProgramArguments": [str(bin_path), "memory", "harvest"],
        "WorkingDirectory": str(repo_root),
        "EnvironmentVariables": job_environment(env),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log_dir / (label + ".log")),
        "StandardErrorPath": str(log_dir / (label + ".err.log")),
        "RunAtLoad": False,
    }
    path = _plist_path(agents_dir, label)
    # Unload first: launchd keeps the old definition until the job is booted
    # out, so writing a new plist alone would leave the previous schedule live.
    runner(["launchctl", "bootout", f"{domain}/{label}"])
    tmp = path.with_suffix(".plist.tmp")
    tmp.write_bytes(plistlib.dumps(plist))
    tmp.replace(path)
    code, _ = runner(["launchctl", "bootstrap", domain, str(path)])
    if code != 0:
        raise RuntimeError(f"launchctl bootstrap failed for {path}")
    return path


def uninstall_launchd(
    repo_root: Path, *, agents_dir: Path, runner: Runner = default_runner, uid: int | None = None
) -> bool:
    label = job_label(repo_root)
    domain = f"gui/{os.getuid() if uid is None else uid}"
    path = _plist_path(agents_dir, label)
    runner(["launchctl", "bootout", f"{domain}/{label}"])
    if path.exists():
        path.unlink()
        return True
    return False


# --- cron --------------------------------------------------------------------


def _read_crontab(runner: Runner) -> str:
    code, out = runner(["crontab", "-l"])
    # "no crontab for user" is exit 1 with nothing useful on stdout.
    return out if code == 0 else ""


def _write_crontab(runner: Runner, content: str) -> None:
    code, _ = runner(["crontab", "-"], input_text=content)
    if code != 0:
        raise RuntimeError("crontab refused the updated table")


def _without_label(content: str, label: str) -> list[str]:
    return [line for line in content.splitlines() if label not in line]


def cron_line(repo_root: Path, bin_path: Path, *, hour: int, minute: int, env: dict[str, str], log_dir: Path) -> str:
    label = job_label(repo_root)
    assignments = " ".join(f"{key}={shlex.quote(value)}" for key, value in sorted(job_environment(env).items()))
    log = shlex.quote(str(log_dir / (label + ".log")))
    command = (
        f"cd {shlex.quote(str(repo_root))} && {assignments} "
        f"{shlex.quote(str(bin_path))} memory harvest >> {log} 2>&1"
    )
    # The trailing comment is the marker uninstall looks for.
    return f"{minute} {hour} * * * {command} # {label}"


def install_cron(
    repo_root: Path,
    bin_path: Path,
    *,
    hour: int,
    minute: int,
    env: dict[str, str],
    log_dir: Path,
    runner: Runner = default_runner,
) -> str:
    _check_time(hour, minute)
    label = job_label(repo_root)
    line = cron_line(repo_root, bin_path, hour=hour, minute=minute, env=env, log_dir=log_dir)
    if "\n" in line or "%" in line:
        # cron treats % as a newline; refuse rather than install a broken job.
        raise ValueError("refusing to write a cron line containing a newline or '%'")
    lines = _without_label(_read_crontab(runner), label)
    lines.append(line)
    _write_crontab(runner, "\n".join(lines) + "\n")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return line


def uninstall_cron(repo_root: Path, *, runner: Runner = default_runner) -> bool:
    label = job_label(repo_root)
    current = _read_crontab(runner)
    kept = _without_label(current, label)
    if kept == current.splitlines():
        return False
    _write_crontab(runner, ("\n".join(kept) + "\n") if kept else "")
    return True


# --- command line ------------------------------------------------------------


def _default_backend() -> str:
    return "launchd" if sys.platform == "darwin" else "cron"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Schedule the daily memory harvest.")
    parser.add_argument("action", choices=("install", "uninstall", "status"))
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("bin_path", type=Path, nargs="?")
    parser.add_argument("--hour", type=int, default=DEFAULT_HOUR)
    parser.add_argument("--minute", type=int, default=DEFAULT_MINUTE)
    parser.add_argument("--backend", choices=("launchd", "cron"), default=_default_backend())
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    home = Path.home()
    agents_dir = home / "Library" / "LaunchAgents"
    log_dir = home / "Library" / "Logs" / "inhousecode" if args.backend == "launchd" else home / ".inhousecode-logs"
    label = job_label(repo_root)

    try:
        if args.action == "install":
            if args.bin_path is None:
                parser.error("install needs the inhousecode binary path")
            bin_path = args.bin_path.resolve()
            if args.backend == "launchd":
                path = install_launchd(
                    repo_root, bin_path, hour=args.hour, minute=args.minute,
                    env=dict(os.environ), agents_dir=agents_dir, log_dir=log_dir,
                )
                print(f"installed launchd job {label} ({path}), daily at {args.hour:02d}:{args.minute:02d}")
            else:
                install_cron(
                    repo_root, bin_path, hour=args.hour, minute=args.minute,
                    env=dict(os.environ), log_dir=log_dir,
                )
                print(f"installed cron job {label}, daily at {args.hour:02d}:{args.minute:02d}")
            print(f"logs: {log_dir}")
            return 0
        if args.action == "uninstall":
            removed = (
                uninstall_launchd(repo_root, agents_dir=agents_dir)
                if args.backend == "launchd"
                else uninstall_cron(repo_root)
            )
            print(f"removed {label}" if removed else f"no harvest job installed for {repo_root}")
            return 0
        installed = (
            _plist_path(agents_dir, label).exists()
            if args.backend == "launchd"
            else any(label in line for line in _read_crontab(default_runner).splitlines())
        )
        print(f"{args.backend} job {label}: {'installed' if installed else 'not installed'}")
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"inhousecode harvest schedule: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
