#!/usr/bin/env python3
"""One git resolution rule and one hardened git environment for the read-side tools.

inventory.py, evidence-run.py, floor_guard.py and preflight.py read repositories they
do not own — a worker's worktree, a target project, a run's
directory — and each used to spawn a bare ``git``: re-resolved against PATH on every
call (a later PATH entry, or a worker-planted ``./bin/git`` on it, answers instead),
under the caller's whole git environment and the graded repo's own config. A
repo-local ``core.fsmonitor`` is a command git runs on ``status``/``diff``; a
``refs/replace/`` ref silently swaps the object a blob hash is taken from.

``GIT`` is resolved ONCE, at import, to an absolute path (the run_report.py /
verify.py rule, h409 R2). ``argv(*args)`` is the argv head every call uses; with no
git on PATH it raises ``GitAbsent`` — a FileNotFoundError, so the callers' existing
``except OSError`` handlers keep their could-not-run exits, now with a message that
names the cause.

``env()`` is the caller's environment plus the floor verify.py's git_env applies
(h409 B4/B5) and replacement objects off:

- ``GIT_NO_REPLACE_OBJECTS=1`` + ``GIT_GRAFT_FILE=/dev/null`` — hash and diff the objects
  the commit names; a planted ``refs/replace/*`` or ``.git/info/grafts`` cannot rewrite the
  tree, parents or content a read resolves (the verify.py object-rewrite belt);
- ``GIT_CONFIG_GLOBAL=/dev/null`` + ``GIT_CONFIG_NOSYSTEM=1`` — no ~/.gitconfig or
  system file steering a read;
- ``GIT_CONFIG_COUNT`` pairs (command-line precedence, above repo-local config), each
  closing a REPOSITORY-config command channel the worker could plant in its own
  ``.git/config`` (#629): ``core.fsmonitor=false`` (a program git runs on status/diff),
  ``core.hooksPath=/dev/null`` (every hook — ``post-checkout`` on a ``worktree add`` /
  ``checkout <paths>`` among them — looked up in a dir with none), ``diff.external=``
  (the global external-diff program; the per-driver ``diff.<n>.command`` is closed by
  ``--no-ext-diff`` and ``driver_blanks``), ``protocol.ext.allow=never`` (the ``ext::``
  transport), and ``safe.directory=*`` in place of the one legitimate use of the dropped
  global file (CI ownership belts);
- ``GIT_TERMINAL_PROMPT=0``; ``GIT_EXTERNAL_DIFF`` and any inherited
  ``GIT_CONFIG_KEY_n``/``VALUE_n`` pairs are dropped so they cannot shadow these.

The attribute-selected channels — ``filter.<driver>.clean/smudge/process`` and
``diff.<driver>.textconv``/``command`` — cannot be closed by a fixed ``-c`` key (``-c``
cannot enumerate an unknown ``<driver>`` name, and ``$GIT_DIR/info/attributes`` outranks
any ``--attr-source`` the belt could set). ``driver_blanks(repo)`` closes them by reading
the driver names the repo's OWN config declares and blanking each — the only place such a
command can come from. A worktree-materialising read (floor_guard's and diff_scope's
``diff`` of the working tree, verify.py's negative-control ``checkout``) passes its pairs;
a read of committed objects alone (inventory, decisions ``--pin-ref``) never selects a
filter and does not need them.

Unlike verify.py the rest of the environment passes: these tools are not a verifier
stating facts against a worker, and a coordinator's locale, HOME and PATH stay theirs.
diff_scope.py inlines the same floor rather than importing this module: verify.py loads
diff_scope by path, so a sibling it imported would join the signed verifier toolchain
(verify._Transcript.TOOLCHAIN and run_report.TOOLCHAIN_FILES). This module is in that
toolchain since #608 all the same: verify.py loads inventory.py to check a retention
receipt, and inventory.py loads this module at import. verify.py's _Authority keeps its
own git_env() and a mirror of driver_blanks() rather than calling this module, but no
longer to stay out of the toolchain: every verifier git leg runs the custody-classed git
_Authority pinned at startup under its scrubbed nc_env floor, where this module runs its
own GIT under the caller's whole environment. tests/test_gitexec_config_commands.py holds
both driver_blanks copies (diff_scope's and verify's) to this one.

Library only: no CLI, no exit codes.
"""
import os
import re
import shutil
import subprocess


class GitAbsent(FileNotFoundError):
    """No git on PATH when this module was imported."""


_found = shutil.which("git")
GIT = os.path.abspath(_found) if _found else None

HARDENED = {
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_GRAFT_FILE": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_COUNT": "5",
    "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "protocol.ext.allow", "GIT_CONFIG_VALUE_1": "never",
    "GIT_CONFIG_KEY_2": "safe.directory", "GIT_CONFIG_VALUE_2": "*",
    "GIT_CONFIG_KEY_3": "core.hooksPath", "GIT_CONFIG_VALUE_3": os.devnull,
    "GIT_CONFIG_KEY_4": "diff.external", "GIT_CONFIG_VALUE_4": "",
}

# A config key whose VALUE is a command git runs when a .gitattributes line selects its
# <driver>: a clean/smudge/process filter, or a textconv/command diff driver. The command
# can come from NOWHERE else, so blanking every such key the repo DECLARES closes the
# channel for driver names no fixed -c could have named (#629). Matched as BYTES: a driver
# name is whatever bytes git accepts (0xff, an invalid UTF-8 sequence, a `.`, an `=`), and
# a .gitattributes line selects that exact name (PR #649 review).
_DRIVER_KEY_RE = re.compile(
    rb"\A(?:filter\.(?:.+)\.(?:clean|smudge|process)|diff\.(?:.+)\.(?:textconv|command))\Z",
    re.S)


def argv(*args):
    """[absolute git, *args]; raises GitAbsent when git was not on PATH at import."""
    if GIT is None:
        raise GitAbsent("git is not on PATH (resolved once, at startup)")
    return [GIT, *args]


def env(base=None, blanks=()):
    """The hardened environment for one git child (see module docstring), plus ``blanks`` —
    ``driver_blanks``'s ``(key, value)`` pairs — appended as further GIT_CONFIG_KEY_n/VALUE_n
    pairs. An env pair carries a key and a value separately, so a key holding ``=`` (which a
    ``-c <key>=<value>`` splits at its FIRST ``=``) or any non-UTF-8 byte reaches git intact."""
    out = {k: v for k, v in (os.environ if base is None else base).items()
           if k != "GIT_EXTERNAL_DIFF"
           and not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    out.update(HARDENED)
    first = int(HARDENED["GIT_CONFIG_COUNT"])
    for i, (key, value) in enumerate(blanks, start=first):
        out[f"GIT_CONFIG_KEY_{i}"], out[f"GIT_CONFIG_VALUE_{i}"] = key, value
    out["GIT_CONFIG_COUNT"] = str(first + len(blanks))
    return out


def driver_blanks(repo):
    """``(key, value)`` config pairs that blank the command of every filter/diff driver DECLARED
    in ``repo``'s config — the attribute-selected exec channel a fixed ``-c`` cannot name (#629).
    Pass them as ``env(blanks=...)``; never as ``-c`` argv, which splits a key at its first ``=``.

    A clean/smudge/process filter or a textconv/command diff driver runs only when a
    ``.gitattributes`` (or ``$GIT_DIR/info/attributes``) line selects a ``<driver>`` AND a
    ``filter.<driver>.*`` / ``diff.<driver>.*`` config key supplies the command. ``-c`` cannot
    wildcard the ``<driver>`` name, and ``info/attributes`` outranks any ``--attr-source`` the
    belt could set, so neither the attribute side nor a fixed key closes it. The command side,
    though, is enumerable: the names come from the repo's OWN config (listed under the hardened
    env, so only repo-local keys appear), and an empty value makes git run no command and pass
    content through — the raw bytes a scanner wants. A read that never materialises worktree
    content selects no filter and may skip this.

    Fail-closed to the EMPTY list only on a git error (never a reason to trust a planted
    driver): callers add these pairs on top of ``--no-ext-diff``/``--no-textconv`` and the
    static belt, so an empty list leaves those in force. The config is read as BYTES and each
    key is handed back through ``os.fsdecode``, which ``subprocess`` reverses with
    ``os.fsencode`` — so git receives exactly the bytes it declared, never a decoded stand-in
    that names a different driver (PR #649 review)."""
    try:
        out = subprocess.run(argv("-C", str(repo), "config", "--list", "-z", "--name-only"),
                             capture_output=True, timeout=30, env=env(),
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [(os.fsdecode(key), "") for key in out.stdout.split(b"\0")
            if _DRIVER_KEY_RE.match(key)]
