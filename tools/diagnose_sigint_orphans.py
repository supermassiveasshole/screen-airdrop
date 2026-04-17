#!/usr/bin/env python3
"""Diagnose orphaned subprocesses after SIGINT.

This tool launches a command, waits for child processes to appear, sends SIGINT
to the command's process group (matching terminal Ctrl+C behavior), and reports
any descendants that remain alive afterward. It is intended for debugging the
layered receiver runtime on macOS.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from typing import List, Sequence

DEFAULT_COMMAND = [
    "uv",
    "run",
    "screen-airdrop-receiver",
    "--source",
    "screen",
    "--window-title",
    "screen-airdrop",
    "--protocol",
    "layered",
    "--module-grid",
    "240x144",
    "--roi",
    "0,0,128,128",
    "--capture-fps",
    "55",
    "--decode-workers",
    "6",
    "--capture-dump-dir",
    "/tmp/layered-live-runtime-captured",
    "--capture-dump-max-frames",
    "2500",
    "--max-idle-seconds",
    "30",
    "--report-json",
    "/tmp/layered-live-runtime-report.json",
    "--prep-process",
    "1",
]


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _run_capture(cmd: Sequence[str]) -> str:
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return result.stdout


def _collect_descendants(root_pid: int) -> List[int]:
    descendants: set[int] = set()
    frontier = [root_pid]
    while frontier:
        current = frontier.pop()
        result = subprocess.run(
            ["pgrep", "-P", str(current)],
            check=False,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.isdigit():
                continue
            child = int(line)
            if child in descendants:
                continue
            descendants.add(child)
            frontier.append(child)
    return sorted(descendants)


def _format_ps(pids: Sequence[int]) -> str:
    if not pids:
        return "(none)"
    pid_csv = ",".join(str(pid) for pid in pids)
    output = _run_capture(
        ["ps", "-o", "pid,ppid,pgid,stat,etime,command", "-p", pid_csv]
    ).strip()
    return output or "(none)"


def _print_section(title: str, body: str) -> None:
    print(f"\n=== {title} ===")
    print(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose orphaned receiver subprocesses")
    parser.add_argument(
        "--sigint-after",
        type=float,
        default=5.0,
        help="seconds to wait before sending SIGINT after children appear",
    )
    parser.add_argument(
        "--spawn-timeout",
        type=float,
        default=10.0,
        help="seconds to wait for the command to spawn child processes",
    )
    parser.add_argument(
        "--exit-timeout",
        type=float,
        default=10.0,
        help="seconds to wait for the root process to exit after SIGINT",
    )
    parser.add_argument(
        "--post-timeout",
        type=float,
        default=5.0,
        help="seconds to wait for descendant processes to disappear after the root exits",
    )
    parser.add_argument(
        "--kill-leaks",
        action="store_true",
        help="send SIGKILL to any descendants that still exist at the end",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="command to run; defaults to the layered receiver diagnostic command",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = list(args.command) if args.command else list(DEFAULT_COMMAND)
    if command and command[0] == "--":
        command = command[1:]

    print("Launching command:")
    print(" ".join(command))
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    stdout = ""
    stderr = ""
    descendants: List[int] = []
    try:
        deadline = time.time() + max(0.1, args.spawn_timeout)
        while time.time() < deadline:
            descendants = _collect_descendants(proc.pid)
            if descendants:
                break
            if proc.poll() is not None:
                break
            time.sleep(0.05)

        root_and_children = [proc.pid] + descendants
        _print_section("Process Tree Before SIGINT", _format_ps(root_and_children))

        if proc.poll() is None:
            time.sleep(max(0.0, args.sigint_after))
            os.killpg(proc.pid, signal.SIGINT)

        try:
            stdout, stderr = proc.communicate(timeout=max(0.1, args.exit_timeout))
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            _print_section("Root Exit", "root process did not exit after SIGINT; killed with SIGKILL")
        else:
            _print_section("Root Exit", f"returncode={proc.returncode}")

        deadline = time.time() + max(0.1, args.post_timeout)
        while time.time() < deadline and any(_pid_exists(pid) for pid in descendants):
            time.sleep(0.05)

        leaked = [pid for pid in descendants if _pid_exists(pid)]
        _print_section("Process Tree After SIGINT", _format_ps(leaked))
        _print_section("Stdout", stdout.strip() or "(empty)")
        _print_section("Stderr", stderr.strip() or "(empty)")

        if leaked:
            print(f"\nLeaked descendant PIDs: {', '.join(str(pid) for pid in leaked)}")
            if args.kill_leaks:
                for pid in leaked:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
                print("Sent SIGKILL to leaked descendants.")
            return 1

        print("\nNo leaked descendants detected.")
        return 0
    finally:
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
