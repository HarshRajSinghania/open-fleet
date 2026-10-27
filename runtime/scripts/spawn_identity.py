#!/usr/bin/env python3
"""Who is spawning: an identity that survives a scrubbed environment (W4-04, Codex round 3).

spawn_worker.sh capped a worker by what its environment said (a profile variable, or the pane
handle `ORCA_TERMINAL_HANDLE` keyed into the spawn registry). A harness that drops `ORCA_*` (Codex's
`shell_environment_policy` does, as ordinary behaviour) left a `ro` worker with nothing to say,
and a missing pane handle read as "coordinator": uncapped. Identity here comes from the process
tree instead, which a worker cannot rewrite short of daemonizing out of it:

- a ROOT is a worker's pane process, recorded at registration as `<pid>.<start>` (the start
  time defeats pid reuse) with the worker's profile. It is found by the pane handle in its
  INITIAL environment (`/proc/<pid>/environ`, else `ps -E`), which the pane process keeps
  whatever its children later drop. Every process the worker runs descends from it;
- a HOST is a root's parent (the pty host, the tmux pane's shell): a caller under one is inside
  a provider's process tree;
- an ANCHOR is a process of the coordinator that launched a worker while uncapped: its own
  ancestors below the nearest one it shares with the worker. A worker can never descend from
  one. An anchor stops counting the moment a live root or a host turns out to descend from it.

record-root exits 3 when the scan worked and no process carries the handle (the worker is not a
local process: it exited, runs remotely or in another uid's container, or the backend is a dry
run) and 1 when it could not scan at all.

Registry (under spawn_worker.sh's `~/.open-fleet/spawn-profiles/`): `.roots/<key>` holds
`<profile> <handle>`, `.hosts/<key>` and `.anchors/<key>` are markers, and `.pending/r.*` are
spawn_worker.sh's launch reservations (`<profile> <launcher handle> <launcher pid> <launcher
start>`). Standard library only.

  whoami --registry DIR --pid PID          what identifies PID (lines, see `whoami`)
  record-root --registry DIR --handle H --profile P [--launcher PID] [--wait SECS]
      find H's pane root, record it and its host, and (with --launcher) the launcher's anchors
"""
import sys

# W3-01: `python3 <dir>/<script>.py` puts <dir> at sys.path[0], AHEAD of the stdlib, so a committed
# sibling named like a stdlib module would BE that module here. Drop that entry before any other
# import (no `from __future__` in this file for that reason); `os` is read from sys.modules,
# loaded at start-up. spawn_worker.sh also runs this with `python3 -I`.
if (__name__ == "__main__" and not getattr(sys.flags, "safe_path", False) and sys.path
        and ("os" not in sys.modules or sys.modules["os"].path.realpath(sys.path[0])
             == sys.modules["os"].path.dirname(sys.modules["os"].path.realpath(__file__)))):
    del sys.path[0]

import argparse
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

PROC = Path("/proc")
HANDLE_VARS = ("ORCA_TERMINAL_HANDLE", "OPEN_FLEET_TERMINAL_HANDLE")
PROFILES = ("ro", "rw", "danger")
_KEY = re.compile(r"[1-9][0-9]*\.[0-9]+\Z")
_HANDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
MAX_DEPTH = 256


def _ps(pid: int, field: str) -> str | None:
    try:
        out = subprocess.run(["ps", "-o", f"{field}=", "-p", str(pid)], capture_output=True, text=True,
                             timeout=10, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    text = " ".join(out.stdout.split())
    return text if out.returncode == 0 and text else None


def stat(pid: int) -> tuple[int, str] | None:
    """(ppid, start token) of a live pid, or None."""
    try:
        raw = (PROC / str(pid) / "stat").read_text()
    except OSError:
        raw = None
    if raw is not None:
        fields = raw[raw.rfind(")") + 2:].split()
        try:
            return int(fields[1]), fields[19]
        except (IndexError, ValueError):
            return None
    if PROC.is_dir():
        return None  # a /proc host where the pid is gone
    ppid, lstart = _ps(pid, "ppid"), _ps(pid, "lstart")
    if ppid is None or lstart is None or not ppid.isdigit():
        return None
    try:
        start = str(int(time.mktime(time.strptime(lstart, "%a %b %d %H:%M:%S %Y"))))
    except ValueError:
        return None
    return int(ppid), start


def key(pid: int) -> str | None:
    st = stat(pid)
    return f"{pid}.{st[1]}" if st else None


def alive(k: str) -> bool:
    pid = int(k.split(".", 1)[0])
    return key(pid) == k


def chain(pid: int) -> list[str]:
    """The keys of pid and every ancestor, nearest first (pid 1 and the kernel excluded)."""
    out: list[str] = []
    while pid > 1 and len(out) < MAX_DEPTH:
        st = stat(pid)
        if st is None:
            break
        out.append(f"{pid}.{st[1]}")
        pid = st[0]
    return out


def _environ_handles(pid: int) -> set[str]:
    try:
        raw = (PROC / str(pid) / "environ").read_bytes()
    except OSError:
        return set()
    found = set()
    for item in raw.split(b"\0"):
        name, _, value = item.partition(b"=")
        if name.decode("latin-1") in HANDLE_VARS:
            found.add(value.decode("utf-8", "replace"))
    return found


class ScanUnavailable(RuntimeError):
    """No way to read other processes' environments on this host: nothing found proves nothing."""


class NoProcess(RuntimeError):
    """The scan worked and no running process carries the handle: no local worker to record."""


def processes_with_handle(handle: str) -> list[int]:
    """Every pid whose INITIAL environment names `handle` as its pane."""
    if PROC.is_dir():
        pids = [int(p.name) for p in PROC.iterdir() if p.name.isdigit()]
        return sorted(p for p in pids if handle in _environ_handles(p))
    try:  # BSD/macOS ps: -E appends the environment to the command (unwitnessed; best effort)
        out = subprocess.run(["ps", "-A", "-ww", "-E", "-o", "pid=,command="], capture_output=True,
                             text=True, timeout=20, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScanUnavailable(f"cannot list process environments: {exc}") from None
    if out.returncode != 0:
        raise ScanUnavailable("cannot list process environments (ps -E failed)")
    want = re.compile(r"(?:^| )(?:%s)=%s(?: |$)" % ("|".join(HANDLE_VARS), re.escape(handle)))
    pids = []
    for line in out.stdout.splitlines():
        head, _, rest = line.strip().partition(" ")
        if head.isdigit() and want.search(rest):
            pids.append(int(head))
    return sorted(pids)


class Registry:
    def __init__(self, path: str):
        self.root = Path(path)

    def _dir(self, name: str) -> Path:
        return self.root / name

    def keys(self, name: str) -> list[str]:
        d = self._dir(name)
        try:
            return sorted(p.name for p in d.iterdir() if _KEY.match(p.name))
        except OSError:
            return []

    def read(self, name: str, k: str) -> str:
        try:
            return (self._dir(name) / k).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def write(self, name: str, k: str, text: str) -> None:
        d = self._dir(name)
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".w.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, d / k)

    def drop(self, name: str, k: str) -> None:
        try:
            (self._dir(name) / k).unlink()
        except OSError:
            pass

    def live_roots(self) -> dict[str, str]:
        """key -> profile of every recorded root still running (dead ones are pruned)."""
        out = {}
        for k in self.keys(".roots"):
            if alive(k):
                out[k] = _profile(self.read(".roots", k))
            else:
                self.drop(".roots", k)
        return out


def _profile(text: str) -> str:
    word = (text.split() or ["ro"])[0]
    return word if word in PROFILES else "invalid"


def whoami(reg: Registry, pid: int) -> list[str]:
    """Lines: ROOT <profile> <key> per recorded root among pid's ancestors; INTREE yes|no;
    ANCHORED yes|no; LIVE <profile> per live root anywhere; RESERVATION <profile> <inflight> <path>
    per open launch reservation this caller is not exempt from; SELF <key>."""
    mine = chain(pid)
    if not mine:
        raise RuntimeError("cannot read this process's ancestry")
    ancestors = set(mine)
    # Reservations FIRST: a launch records its root before it drops its reservation, so one gone
    # from this snapshot means its root (if this process has one) is readable below.
    snapshot = []
    try:
        entries = sorted(p for p in reg._dir(".pending").iterdir() if p.name.startswith("r."))
    except OSError:
        entries = []
    for path in entries:
        try:
            snapshot.append((path, path.read_text(encoding="utf-8", errors="replace").split()))
        except OSError:
            continue  # gone: resolved between the listing and the read
    live = reg.live_roots()
    lines = [f"ROOT {prof} {k}" for k, prof in live.items() if k in ancestors]
    hosts = [k for k in reg.keys(".hosts") if alive(k) or reg.drop(".hosts", k)]
    lines.append("INTREE " + ("yes" if ancestors & set(hosts) else "no"))
    # An anchor counts only while no live root and no host descends from it.
    shadowed = set()
    for k in list(live) + hosts:
        shadowed.update(chain(int(k.split(".", 1)[0])))
    anchors = [k for k in reg.keys(".anchors") if alive(k) or reg.drop(".anchors", k)]
    anchored = any(k in ancestors and k not in shadowed for k in anchors)
    lines.append("ANCHORED " + ("yes" if anchored else "no"))
    lines += [f"LIVE {prof}" for prof in live.values()]
    for path, fields in snapshot:
        prof = fields[0] if fields and fields[0] in PROFILES else ("ro" if not fields else "invalid")
        launcher = f"{fields[2]}.{fields[3]}" if len(fields) >= 4 and _KEY.match(f"{fields[2]}.{fields[3]}") else None
        inflight = launcher is not None and alive(launcher)
        # The coordinator's own launches do not cap it: exempt only when it is anchored AND does
        # not descend from the launch in question (a worker that launch started might, while
        # the launch is still running).
        if anchored and launcher is not None and launcher not in ancestors:
            continue
        lines.append(f"RESERVATION {prof} {1 if inflight else 0} {path}")
    lines.append(f"SELF {mine[0]}")
    return lines


def record_root(reg: Registry, handle: str, profile: str, launcher: int | None, wait: float) -> list[str]:
    if not _HANDLE.match(handle) or profile not in PROFILES:
        raise RuntimeError("not a pane handle or profile")
    deadline = time.monotonic() + wait
    while True:
        found = processes_with_handle(handle)
        if found or time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    roots = []
    found_set = set(found)
    for pid in found:
        st = stat(pid)
        if st is None or st[0] in found_set:
            continue  # gone, or not the topmost process of the pane
        roots.append((pid, st))
    if not roots:
        raise NoProcess(f"no running process carries pane handle {handle}")
    lines = []
    for pid, (ppid, start) in roots:
        k = f"{pid}.{start}"
        reg.write(".roots", k, f"{profile} {handle}\n")
        lines.append(f"ROOT {k}")
        hk = key(ppid) if ppid > 1 else None
        if hk:
            reg.write(".hosts", hk, "")
            lines.append(f"HOST {hk}")
    if launcher is not None:
        coordinator = chain(launcher)
        shared = set()
        for pid, _st in roots:
            shared.update(chain(pid))
        for k in coordinator:
            if k in shared:
                break  # the nearest common ancestor and everything above it are not the coordinator's
            reg.write(".anchors", k, "")
            lines.append(f"ANCHOR {k}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="spawn_identity.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("whoami")
    w.add_argument("--registry", required=True)
    w.add_argument("--pid", type=int, required=True)
    r = sub.add_parser("record-root")
    r.add_argument("--registry", required=True)
    r.add_argument("--handle", required=True)
    r.add_argument("--profile", required=True)
    r.add_argument("--launcher", type=int)
    r.add_argument("--wait", type=float, default=1.0)
    ns = ap.parse_args(argv)
    reg = Registry(ns.registry)
    try:
        if ns.cmd == "whoami":
            lines = whoami(reg, ns.pid)
        else:
            lines = record_root(reg, ns.handle, ns.profile, ns.launcher, max(0.0, ns.wait))
    except (OSError, RuntimeError) as exc:
        text = "".join(c if c.isprintable() else f"\\u{ord(c):04x}" for c in str(exc))
        print(f"spawn_identity: {text}", file=sys.stderr)
        return 3 if isinstance(exc, NoProcess) else 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
