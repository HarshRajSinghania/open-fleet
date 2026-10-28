"""Fetched branch names that hold a line break (W3-07 class, independent re-attack).

`str.splitlines()` breaks on every character in LINE_BREAKS. git accepts U+2028, U+2029 and
U+0085 in a refname (check-ref-format passes), so a worker that pushes the branch
`x<U+2028>refs/remotes/origin/main` and waits for the coordinator's plain `git fetch` gets a
`for-each-ref` listing whose second "line" reads `refs/remotes/origin/main\\0\\0<its commit>`.
git refuses the control characters in a refname; plant() writes those as a loose ref file
instead, which git then ignores — so a site must stay honest for them too, whatever git does.

Loaded by path (tests/fixtures/containment_tables.py is the precedent), never imported by name.
"""
import shutil
import subprocess
from pathlib import Path

LINE_BREAKS = (" ", " ", "\x85", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e")
# The ones git accepts in a refname: a site that parses with str.splitlines() is fooled by these.
ACCEPTED = (" ", " ", "\x85")


def plant(repo, ch, oid, honest="refs/remotes/origin/main"):
    """Point the remote-tracking ref `refs/remotes/origin/x<ch><honest>` at `oid`, as a fetch of
    the worker's branch would. Returns a callable that removes it again."""
    name = f"refs/remotes/origin/x{ch}{honest}"
    r = subprocess.run(["git", "-C", str(repo), "update-ref", name, oid], capture_output=True)
    if r.returncode == 0:
        return lambda: subprocess.run(["git", "-C", str(repo), "update-ref", "-d", name],
                                      check=True, capture_output=True)
    if ch in ACCEPTED:
        raise AssertionError(f"git refused a refname holding {ch!r}: {r.stderr!r}")
    git_dir = subprocess.run(["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
                             check=True, capture_output=True, text=True).stdout.strip()
    path = Path(git_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(oid + "\n", encoding="utf-8")
    top = Path(git_dir) / "refs" / "remotes" / "origin" / f"x{ch}refs"
    return lambda: shutil.rmtree(top)
