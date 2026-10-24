"""Process containment for paid calls: find every process of a call, wherever it went.

Every process of a call carries `OF_CALL_ID=<its tag>` in its environment. A descendant that calls
setsid() leaves its call's process group and, once its parent exits, its process tree too, but it
keeps the marker, so a sweep finds it by the marker. `sweep` SIGKILLs everything carrying a tag,
every member of the given groups and every descendant of any of them, until a fresh scan finds
none; it fails closed when one survives or when the process table cannot be read.
`containment_problem` is the host check a paid live run makes before it reserves anything: probes
in sessions of their own, carrying a marker, must show up in the process table by that marker.

One helper, shared: scripts/_ablation_run.py (#606/#657, its watchdog and contained_run),
first_run.py and the WIP-curve runner use this module. It ships in the runtime bundle, which
first_run.py is part of (PR #668 review: the sweep moved here from _ablation_run.py, unchanged
but for the injectable process-table reader `table`).

Discovery is only as good as the table: Linux reads /proc/<pid>/environ, which shows every process
this user owns; elsewhere `ps -E`, which on macOS cannot read an Apple system binary's environment
(/bin/sh, /bin/sleep), so a detached shell is invisible there. The probe can test for exactly that.
"""
from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# Every process of a call carries `OF_CALL_ID=<its tag>` in its environment, wherever it goes: a
# descendant that calls setsid() leaves the call's process group but keeps the marker (K4).
CALL_MARKER = "OF_CALL_ID"


def environ_of(pid):
    """A Linux process's environment as it was started (empty when it is not ours to read)."""
    try:
        raw = Path("/proc", str(pid), "environ").read_bytes()
    except OSError:
        return ()
    return tuple(raw.decode("utf-8", errors="replace").split("\0"))


def process_table():
    """{pid: (ppid, pgid, environment entries)} for every live process this user can see; a zombie
    runs nothing and is left out. Linux reads /proc; elsewhere `ps -E` lists each of this user's
    own processes with the environment it started with (others' read as empty). OSError when the
    table cannot be read: a sweep that cannot see cannot vouch for anything."""
    table = {}
    if os.path.isdir("/proc/self"):
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                stat = Path("/proc", entry, "stat").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue  # gone since the listing
            fields = stat.rsplit(")", 1)[-1].split()  # after `pid (comm)`: comm may hold spaces
            if len(fields) > 2 and fields[0] not in ("Z", "X") and fields[1].isdigit() and fields[2].isdigit():
                table[int(entry)] = (int(fields[1]), int(fields[2]), environ_of(entry))
        return table
    scan = subprocess.Popen(["ps", "-A", "-E", "-ww", "-o", "pid=,ppid=,pgid=,stat=,command="],
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="replace",
                            start_new_session=True)
    try:
        out, _err = scan.communicate(timeout=30)
    except subprocess.TimeoutExpired as err:
        scan.kill()
        scan.wait()
        raise OSError("ps did not answer within 30 s") from err
    if scan.returncode != 0:
        raise OSError(f"ps exited with status {scan.returncode}")
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit() \
                and not parts[3].startswith("Z"):
            # `command` is the argv then (-E) the environment, space-separated: a marker is a token.
            env = tuple(parts[4].split()) if len(parts) > 4 else ()
            table[int(parts[0])] = (int(parts[1]), int(parts[2]), env)
    table.pop(scan.pid, None)  # the scan itself is nobody's call
    return table


def call_processes(table, roots=(), groups=(), exclude=(), tag=None):
    """A call's live pids in `table`: every process carrying its `tag`, every member of `groups`,
    every one of `roots`, and every descendant of any of them -- minus `exclude` and this process,
    which never sweeps itself."""
    marker = f"{CALL_MARKER}={tag}" if tag else None
    children = {}
    for pid, (ppid, _pgid, _env) in table.items():
        children.setdefault(ppid, []).append(pid)
    stack = [pid for pid, (_ppid, pgid, env) in table.items() if pgid in groups or (marker and marker in env)]
    stack += [pid for pid in roots if pid in table]
    found = set()
    while stack:
        pid = stack.pop()
        if pid not in found:
            found.add(pid)
            stack.extend(children.get(pid, ()))
    return found - set(exclude) - {os.getpid()}


def sweep(roots=(), groups=(), exclude=(), wait_s=10.0, tag=None, table=None):
    """SIGKILL a call's processes (call_processes) until a fresh scan finds none: True. False when
    one survives `wait_s`, or when the process table cannot be read (fail closed). `table` is the
    process-table reader (process_table when None), injected by a caller or a test."""
    read = table or process_table
    deadline = time.monotonic() + wait_s
    while True:
        try:
            left = call_processes(read(), roots, groups, exclude, tag)
        except OSError:
            return False
        if not left:
            return True
        for pid in left:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)


def containment_problem(system_binary=False, table=None):
    """Why process discovery cannot contain a call on this host, or None (#657 review W1). A probe
    in a session of its own, carrying a call marker, must show up in the process table by that
    marker. Checked before a paid run reserves anything: where a sandbox denies `ps`, or the table
    hides environments, a call's escaped processes could never be found."""
    # With `system_binary`, a second probe: a system binary such as a worker's shell starts. macOS's
    # `ps -E` cannot read an Apple system binary's environment (/bin/sh, /bin/sleep) while it reads
    # a Python's, so the Python probe alone vouches for a table blind to a detached shell (PR #668
    # review). The WIP-curve runner asks for it; this runner's own default is unchanged.
    tag = secrets.token_hex(16)
    sleep = shutil.which("sleep", path="/bin:/usr/bin") if system_binary else None
    argvs = [[sys.executable, "-c", "import time; time.sleep(60)"]] + ([[sleep, "60"]] if sleep else [])
    probes = []
    try:
        for argv in argvs:
            probes.append(subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, env=dict(os.environ, **{CALL_MARKER: tag}),
                                           start_new_session=True))
    except OSError as err:
        for probe in probes:
            probe.kill()
            probe.wait()
        return f"a probe could not start: {err}"
    try:
        deadline = time.monotonic() + 3
        while True:
            try:
                found = call_processes((table or process_table)(), tag=tag)
            except OSError as err:
                return f"the process table cannot be read: {err}"
            if found == {probe.pid for probe in probes}:
                return None
            if time.monotonic() > deadline:
                hidden = [Path(probe.args[0]).name for probe in probes if probe.pid not in found]
                return f"the process table does not show a call's {CALL_MARKER} marker (on {', '.join(hidden)})"
            time.sleep(0.05)
    finally:
        for probe in probes:
            probe.kill()
            probe.wait()
