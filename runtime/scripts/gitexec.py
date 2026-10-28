#!/usr/bin/env python3
"""One git resolution rule and one hardened git environment for the read-side tools.

inventory.py, evidence-run.py, floor_guard.py and preflight.py read repositories they
do not own — a worker's worktree, a target project, a run's
directory — and each used to spawn a bare ``git``: re-resolved against PATH on every
call (a later PATH entry, or a worker-planted ``./bin/git`` on it, answers instead),
under the caller's whole git environment and the graded repo's own config. A
repo-local ``core.fsmonitor`` is a command git runs on ``status``/``diff``; a
``refs/replace/`` ref silently swaps the object a blob hash is taken from. decisions.py
(``--pin-ref``), hint_provenance.py and the paid runners in scripts/ (ablation.py,
_trajectories.py, wip_curve.py, live_container.py) have since joined those four, and so have the
posix provider (runtime/providers/posix.py) and the external adapters' shared CLI runners
(runtime/providers/_external.py), whose git runs coordinator-side over the shared ``.git`` a
worker writes (W4-01). Their git custody lives here too, shared with the read-side tools.

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
  ``GIT_CONFIG_KEY_n``/``VALUE_n`` pairs are dropped so they cannot shadow these, and so are
  ``GIT_CONFIG_PARAMETERS`` (inherited ``-c`` pairs, read AFTER the count pairs, so they would
  outrank them) and ``GIT_CONFIG`` (the one file ``git config --list`` reads, which hid every
  declared driver from ``driver_blanks`` while the content-reading call still loaded the repo's
  config; W4-07 sweep).

The attribute-selected channels — ``filter.<driver>.clean/smudge/process`` and
``diff.<driver>.textconv``/``command`` — cannot be closed by a fixed ``-c`` key (``-c``
cannot enumerate an unknown ``<driver>`` name, and ``$GIT_DIR/info/attributes`` outranks
any ``--attr-source`` the belt could set). ``driver_blanks(repo)`` reads the driver names the
repo's OWN config declares and blanks each — the only place such a command can come from. But
the listing and the call are two steps: a driver a concurrent writer of that config adds between
them runs unblanked, so the pairs close the channel only for a config nobody writes while the call
runs. A git that could apply such a driver therefore runs in GIT CUSTODY instead
(``custody()``/``custody_git_dir()``, below): against a git dir the coordinator builds over the
repository's objects (and, for a work-tree read, its index), whose config declares no driver at
all, so a driver added at any moment is undefined there. The providers' ``run_git``
(runtime/providers/posix.py, PR #720 Codex round 3) and, since the W4 custody sweep, floor_guard's
and hint_provenance's working-tree ``diff`` (and hint_provenance's ``log``), diff_scope's
working-tree ``diff`` and ``merge-tree``, and verify.py's negative-control checkout, revert, apply
and seal all run there. Those callers keep listing the drivers as a belt (an unreadable config is
still a refusal); _trajectories.py's replay still relies on the listing alone. A read of committed
objects alone (inventory, decisions ``--pin-ref``) never selects a driver and needs neither.

``custody_env()`` is ``env()`` for a git that must run nothing the repository names: it drops every
repository-selecting variable (``SELECTOR_ENV``: ``GIT_DIR``, ``GIT_INDEX_FILE``,
``GIT_OBJECT_DIRECTORY``, ``GIT_EXEC_PATH``, ...), adds ``CUSTODY_FLOOR`` (fixed keys that name a
program: ``core.alternateRefsCommand``, submodule recursion, ``log.showSignature`` and every
``gpg.*.program``, auto-maintenance) and sets ``CUSTODY_ENV`` (``GIT_ALLOW_PROTOCOL=file``,
``GIT_NO_LAZY_FETCH=1``: no lazy fetch from a planted promisor remote, so no ``uploadpack``,
credential helper or ssh command). floor_guard, diff_scope and hint_provenance run every git under
it, in custody or not. Neither the custody nor this env reaches into a checked-out SUBMODULE: a
git that compares the work tree probes a submodule's dirtiness with a child git that runs under
the submodule's own config, so every such custody call also carries ``NO_SUBMODULE_CHILD``
(``--ignore-submodules=dirty``), and a caller that stages keeps its gitlinks out of ``git add``.

Unlike verify.py the rest of the environment passes: these tools are not a verifier
stating facts against a worker, and a coordinator's locale, HOME and PATH stay theirs.
diff_scope.py inlines the same floor (its own GIT, ``_git_env``, ``_driver_blanks``) and loads
this module by path only for the custody (``custody`` with its own runner, ``SELECTOR_ENV``,
``CUSTODY_FLOOR``, ``CUSTODY_ENV``). This module is in the signed verifier toolchain
(verify._Transcript.TOOLCHAIN and run_report.TOOLCHAIN_FILES) since #608: verify.py loads
inventory.py to check a retention receipt, and inventory.py loads this module at import.
verify.py's _Authority keeps its own git_env() and a mirror of driver_blanks(), and takes only
``custody_git_dir`` from here (it runs no git): every verifier git leg runs the custody-classed
git _Authority pinned at startup under its scrubbed nc_env floor, where this module runs its own
GIT under the caller's whole environment. tests/test_gitexec_config_commands.py holds both
driver_blanks copies (diff_scope's and verify's) to this one.

``remote_tracking_commit(git, name)`` is the one rule a TRUST ANCHOR named by its caller answers
to (W3-07): a commit id, read as an object id only, or a full ``refs/remotes/…`` ref that exists
under exactly that name, every symbolic hop remote-tracking too. It holds the rule, not a git:
each caller passes its own executor (verify.py its custody-classed one), so decisions.py
``--pin-ref``, gate-batch.py ``--pin-ref``, run_report.py's trusted base, verify.py's trust keys
and release_check.py's gate-1 anchor resolve a name the same way. verify-gate.sh mirrors it in sh.

Library only: no CLI, no exit codes.
"""
import contextlib
import os
import re
import shutil
import stat
import subprocess
import tempfile


class GitAbsent(FileNotFoundError):
    """No git on PATH when this module was imported."""


class DriverQueryFailed(OSError):
    """driver_blanks could not read the repository's config: the query errored, timed out, or
    printed output it cannot parse. An OSError, so a caller's could-not-run handler applies; it is
    NEVER read as "no drivers declared" — that would run the content-reading git command with
    every planted driver live (PR #649 review, PRRT_kwDOTWxN9c6vzAIE)."""


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
# Inherited variables env() never passes on (see the module docstring): each would shadow or
# blind the floor above.
_INHERITED_DROPPED = frozenset({"GIT_EXTERNAL_DIFF", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG"})

# A config key whose VALUE is a command git runs when a .gitattributes line selects its
# <driver>: a clean/smudge/process filter, or a textconv/command diff driver. The command
# can come from NOWHERE else, so blanking every such key the repo DECLARES closes the
# channel for driver names no fixed -c could have named (#629). Matched as BYTES: a driver
# name is whatever bytes git accepts (0xff, an invalid UTF-8 sequence, a `.`, an `=`), and
# a .gitattributes line selects that exact name (PR #649 review).
# A filter is neutralised WHOLE, once per declared name: commands blanked AND `required=false`,
# because a required filter that runs nothing makes git die (`clean filter '<driver>' failed`) —
# with its command blanked, or with none declared at all — and a worker could stop every gate
# that reads a matching file (PR #649 review). A diff driver carries no `required`.
_FILTER_KEY_RE = re.compile(rb"\Afilter\.(.+)\.[^.]+\Z", re.S)
_DIFF_COMMAND_KEY_RE = re.compile(rb"\Adiff\.(?:.+)\.(?:textconv|command)\Z", re.S)
_FILTER_BLANKS = ((b"clean", ""), (b"smudge", ""), (b"process", ""), (b"required", "false"))
# A `merge.<driver>.*` key marks a custom merge driver a `merge=<driver>` attribute selects when
# git 3-way-merges a path — reachable on the read side through `git merge-tree` (diff_scope's
# predict_merge) and the control's `revert`/`apply`/`checkout` (PR #649 review). Its command
# can come only from `merge.<driver>.driver`, so for every declared driver NAME we override that
# to `exit 1`: git runs a merge driver as `sh -c "<command>"`, and `exit 1` is a POSIX shell
# special builtin that terminates with status 1 before any word runs a program — no
# repository-supplied command, no PATH or cwd lookup, nothing a worktree file could shadow — and
# git reads the non-zero status as an unresolved (conflicting) merge, i.e. fails closed. This
# also covers `merge.<driver>.recursive` (its named inner driver is itself declared, so its
# `.driver` is overridden too) and a driver declared without a command (git would otherwise fatal
# "lacks command line"). Only repo-declared drivers appear, since the scrubbed env drops global.
_MERGE_KEY_RE = re.compile(rb"\Amerge\.(.+)\.[^.]+\Z", re.S)
_MERGE_DRIVER = "exit 1"


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
           if k not in _INHERITED_DROPPED
           and not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    out.update(HARDENED)
    first = int(HARDENED["GIT_CONFIG_COUNT"])
    for i, (key, value) in enumerate(blanks, start=first):
        out[f"GIT_CONFIG_KEY_{i}"], out[f"GIT_CONFIG_VALUE_{i}"] = key, value
    out["GIT_CONFIG_COUNT"] = str(first + len(blanks))
    return out


def driver_blanks(repo, *, git_dir=None, base=None):
    """``(key, value)`` config pairs that neutralise the command of every filter/diff/merge driver
    DECLARED in ``repo``'s config — the attribute-selected exec channel a fixed ``-c`` cannot name
    (#629). Pass them as ``env(blanks=...)``; never as ``-c`` argv, which splits a key at its
    first ``=``. ``git_dir`` reads the config the git directory it names resolves (``--git-dir``)
    instead of discovering one from ``repo``: for a caller that names its repository that way and
    never trusts a worktree's own ``.git`` pointer (posix.py's sandbox sync, W4-01), so the
    drivers are read where its call runs. ``base`` is the environment the listing runs under (as
    ``env(base)``); a caller whose git call runs under a base of its own passes the same one, so
    the listing and the call resolve the same repository (PR #720 Codex round 2). Filter and diff commands are blanked to empty; a merge driver is overridden to
    ``exit 1`` (see ``_MERGE_KEY_RE``), so a git ``merge-tree``/``revert``/``apply``/``checkout``
    that would run it reads a conflict instead and runs nothing.

    A clean/smudge/process filter or a textconv/command diff driver runs only when a
    ``.gitattributes`` (or ``$GIT_DIR/info/attributes``) line selects a ``<driver>`` AND a
    ``filter.<driver>.*`` / ``diff.<driver>.*`` config key supplies the command; a custom merge
    driver likewise needs a ``merge=<driver>`` attribute and a ``merge.<driver>.driver``. ``-c``
    cannot
    wildcard the ``<driver>`` name, and ``info/attributes`` outranks any ``--attr-source`` the
    belt could set, so neither the attribute side nor a fixed key closes it. The command side,
    though, is enumerable: the names come from the repo's OWN config (listed under the hardened
    env, so only repo-local keys appear), and an empty value makes git run no command and pass
    content through — the raw bytes a scanner wants. A read that never materialises worktree
    content selects no filter and may skip this.

    Every declared filter gets all four of clean/smudge/process blank and ``required=false``:
    git dies on a required filter that runs nothing, so blanking the commands alone turned a
    planted ``required=true`` into a gate that cannot run (PR #649 review). Git then passes the
    working-tree bytes through untouched. A diff driver's non-command keys are left alone.

    An empty list means exactly "no driver declared": git answers an empty but valid config with
    exit 0 and no output. Any other outcome — a git error, a timeout, a non-zero exit (git uses
    128 for an unreadable or malformed config), or output that is not NUL-terminated keys —
    raises DriverQueryFailed, so the caller stops instead of running with nothing blanked
    (PR #649 review). The config is read as BYTES and each
    key is handed back through ``os.fsdecode``, which ``subprocess`` reverses with
    ``os.fsencode`` — so git receives exactly the bytes it declared, never a decoded stand-in
    that names a different driver (PR #649 review)."""
    where = ("--git-dir", str(git_dir)) if git_dir is not None else ("-C", str(repo))
    try:
        out = subprocess.run(argv(*where, "config", "--list", "-z", "--name-only"),
                             capture_output=True, timeout=30, env=env(base),
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as err:
        raise DriverQueryFailed(f"git config --list could not run in {where[1]}: {err}") from err
    if out.returncode != 0:
        why = out.stderr.decode("utf-8", "replace").strip()[:200]
        raise DriverQueryFailed(f"git config --list exited {out.returncode} in {where[1]}: {why}")
    return _blank_pairs(out.stdout)


def _blank_pairs(listing):
    """``git config --list -z --name-only`` bytes -> driver_blanks pairs (see its docstring).
    The listing must be empty or a run of non-empty, NUL-terminated keys; anything else is a
    query this cannot trust, so DriverQueryFailed rather than a guess."""
    if listing and not listing.endswith(b"\0"):
        raise DriverQueryFailed("git config --list printed output that is not NUL-terminated keys")
    keys = listing.split(b"\0")[:-1] if listing else []
    if any(not key for key in keys):
        raise DriverQueryFailed("git config --list printed an empty key")
    pairs, filt_seen, merge_seen = [], set(), set()
    for key in keys:
        filt = _FILTER_KEY_RE.match(key)
        merge = _MERGE_KEY_RE.match(key)
        if filt:
            if filt.group(1) not in filt_seen:
                filt_seen.add(filt.group(1))
                pairs += [(os.fsdecode(b"filter." + filt.group(1) + b"." + var), value)
                          for var, value in _FILTER_BLANKS]
        elif merge:
            if merge.group(1) not in merge_seen:
                merge_seen.add(merge.group(1))
                pairs.append((os.fsdecode(b"merge." + merge.group(1) + b".driver"), _MERGE_DRIVER))
        elif _DIFF_COMMAND_KEY_RE.match(key):
            pairs.append((os.fsdecode(key), ""))
    return pairs


# --- A trust anchor by its exact name (W3-07) ------------------------------------------------
# `rev-parse <name>` expands a ref name (gitrevisions: <name>, refs/<name>, refs/tags/<name>,
# refs/heads/<name>, …), so `refs/remotes/worker/key` with that ref ABSENT resolves to the local
# branch `refs/heads/refs/remotes/worker/key` — a spelling check on the name passed it, and so
# did any revision suffix (`refs/remotes/origin/main~1`, `^`, `@{1}`). A 64-hex name in a SHA-1
# repository (or a 40-hex one in a SHA-256 repository) is not an object id there and expands as
# a ref name too. The rule below never hands git a name to expand: refs are looked up by their
# exact name in one listing, and a commit id must resolve to itself.
COMMIT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
REMOTE_TRACKING = "refs/remotes/"
LOCAL_BRANCH = "refs/heads/"
_SYMREF_HOPS = 5  # git's own limit on a symbolic-ref chain


def remote_tracking_commit(git, name):
    """``(commit, target, None)`` when ``name`` anchors trust, else ``(None, target, why)``.

    ``git(*args)`` runs one git command in the repository and returns ``(returncode, stdout
    text)``. ``target`` is the final ref ``name`` reaches (the commit id itself for an id), for
    the caller's message; ``why`` completes a sentence that begins with ``name``.

    - A commit id (40 or 64 hex digits, any case) anchors when ``rev-parse <id>^{commit}``
      prints that same id: it names a commit OBJECT, never a ref spelled in hex.
    - Anything else must be a full ``refs/remotes/…`` name ``git check-ref-format`` accepts —
      no revision syntax — that EXISTS under exactly that name in the repository's
      ``refs/remotes/`` listing. A symbolic ref is walked one hop at a time (``symbolic-ref
      --no-recurse``, never the listing's recursive ``%(symref)``), so every hop and the final
      target are remote-tracking and exist; the target's object id is then peeled to a commit.
      Resolved once: the caller reads at ``commit``, never at ``name``.

    Remote-tracking means what this clone's fetch wrote: an anchor in the coordinator's clone or
    a CI checkout, advisory in a worker's own, where every ref is the worker's to write."""
    if not name or name.startswith("-"):
        return None, name, "is empty or option-shaped, not a commit id or a ref"
    if COMMIT_ID.fullmatch(name.lower()):
        oid = name.lower()
        code, out = git("rev-parse", "--verify", "-q", f"{oid}^{{commit}}")
        if code != 0 or out.strip() != oid:
            return None, name, ("is spelled as a commit id but names no commit object here (an id "
                                "is read as an object id only, never as a ref of that spelling)")
        return oid, oid, None
    if not name.startswith(REMOTE_TRACKING):
        return None, name, ("is neither a commit id nor a full remote-tracking ref name "
                            "(refs/remotes/…): a local branch, tag, HEAD or short name is one the "
                            "checked change can move")
    return _exact_ref_commit(git, name, REMOTE_TRACKING, "remote-tracking ref",
                             "is not remote-tracking (a local branch the checked change can move)")


def local_branch_commit(git, name):
    """``(commit, target, None)`` for a full ``refs/heads/…`` branch that exists under exactly that
    name (every symbolic hop a local branch too), else ``(None, target, why)``. The same exact-name
    lookup as remote_tracking_commit, in the local namespace: never a tag, never a revision
    suffix, never what git's ref-name expansion would substitute. A local branch is NOT a trust
    anchor — the checked change can move it — so a caller that accepts one says so."""
    if not name or not name.startswith(LOCAL_BRANCH):
        return None, name, "is not a full local branch name (refs/heads/…)"
    return _exact_ref_commit(git, name, LOCAL_BRANCH, "local branch", "is not a local branch")


def _exact_ref_commit(git, name, namespace, kind, outside):
    """The exact-name lookup both rules share. ``name`` (already under ``namespace``) must pass
    check-ref-format and exist under exactly that name in one ``for-each-ref <namespace>``
    listing. A symbolic ref is walked ONE HOP AT A TIME with ``git symbolic-ref --no-recurse``:
    the listing's ``%(symref)`` is the RECURSIVELY resolved target, so it showed
    refs/remotes/worker/key -> refs/heads/bridge -> refs/remotes/origin/retired-key as pointing
    straight at the remote ref and hid the local bridge — which the checked change can re-point
    at any other remote-tracking ref (Codex review). Every hop must be a ``namespace`` ref listed
    under exactly its name, the chain is bounded, and where one hop cannot be read on its own (git
    older than 2.39 has no ``--no-recurse``) a symbolic name is refused, never trusted on its
    recursive target. A plain, non-symbolic ref needs no hop reading and works on any git."""
    code, _ = git("check-ref-format", name)
    if code != 0:
        return None, name, ("is not a valid ref name: revision syntax (~1, ^, @{…}, :) names a "
                            "commit relative to a ref, not a ref")
    code, out = git("for-each-ref", "--format=%(refname)%00%(symref)%00%(objectname)%00",
                    namespace)
    if code != 0:
        return None, name, "could not be looked up: git for-each-ref failed"
    listed, bad = _ref_records(out, namespace)
    if listed is None:
        return None, name, f"could not be looked up: {bad}"
    target = name
    for _hop in range(_SYMREF_HOPS + 1):
        if target not in listed:
            via = f" (through the symbolic ref to {target})" if target != name else ""
            return None, target, (f"names no {kind} that exists under exactly that name{via}: "
                                  f"git's ref-name expansion (refs/heads/{target}, …) is never "
                                  "followed")
        symbolic, oid = listed[target]
        if not symbolic:
            break
        # %(symref) above is the chain's END; the next hop is read on its own. Only the one LF
        # git appends is dropped: str.strip() would also eat U+2028/U+2029/U+0085, which a
        # refname may end with, and turn one name into another.
        code, out = git("symbolic-ref", "-q", "--no-recurse", target)
        hop = (out[:-1] if out.endswith("\n") else out) if code == 0 else ""
        if not hop or "\n" in hop or "\0" in hop:
            return None, target, ("is a symbolic ref whose chain cannot be read one hop at a time "
                                  "here (git symbolic-ref --no-recurse, git 2.39+): refused rather "
                                  "than trusted on its recursively resolved target")
        if not hop.startswith(namespace):
            return None, hop, f"is a symbolic ref to {hop}, which {outside}"
        target = hop
    else:
        return None, target, f"is a symbolic-ref chain longer than {_SYMREF_HOPS} hops"
    code, out = git("rev-parse", "--verify", "-q", f"{oid}^{{commit}}")
    commit = out.strip()
    if code != 0 or not COMMIT_ID.fullmatch(commit):
        return None, target, f"reaches {target}, which points at no commit"
    return commit, target, None


def _ref_records(out, namespace):
    """``({refname: (symref, oid)}, None)`` from ``for-each-ref`` output whose format ends every
    record in NUL and git's LF, or ``(None, why)``. The split is on that NUL+LF terminator ONLY:
    no field can hold NUL or LF (check-ref-format refuses both), while a refname MAY hold
    U+2028, U+2029 and U+0085 — each a line break to ``str.splitlines()``, so a fetched branch
    ``x<U+2028>refs/remotes/origin/main`` parsed as a second record that REPLACED the real
    origin/main in a last-wins dict (independent re-attack). A record that is not exactly three
    fields under ``namespace``, or a refname seen twice, refuses the whole listing: fail closed.
    A runner that stripped the final LF is tolerated (its last record still ends in NUL)."""
    if not out:
        return {}, None
    if out.endswith("\0\n"):
        body = out[:-2]
    elif out.endswith("\0"):
        body = out[:-1]
    else:
        return None, "the for-each-ref listing is not NUL-terminated records"
    listed = {}
    for record in body.split("\0\n"):
        fields = record.split("\0")
        if len(fields) != 3 or not fields[0].startswith(namespace):
            return None, "the for-each-ref listing holds a malformed record"
        if fields[0] in listed:
            return None, f"the for-each-ref listing names {fields[0]!r} twice"
        listed[fields[0]] = (fields[1], fields[2])
    return listed, None


# A caller that sets one of these claims a sound (off-worker) lane: the predicate decisions.py,
# gate-batch.py and run_report.py already apply (each keeps its copy), here for floor_guard.py and
# diff_scope.py, which refuse a LOCAL base on such a lane.
PROVENANCE_VARS = ("OPEN_FLEET_PROVENANCE", "ORCA_PROVENANCE")


def sound_lane(environ=None):
    """`VAR=value` for the first provenance variable set (a lane claiming soundness), or None."""
    env = os.environ if environ is None else environ
    return next((f"{var}={env[var]}" for var in PROVENANCE_VARS
                 if (env.get(var) or "").strip()), None)


# --- A diff base by exact names (floor_guard.py, diff_scope.py; W3-07 class) -------------------
# Both resolved a base with `rev-parse <base>^{commit}` and, unnamed, cut origin/HEAD's target to
# the SHORT name `origin/<x>`: gitrevisions tries refs/tags/ and refs/heads/ before refs/remotes/,
# so a tag or local branch spelled `origin/main` stood in for the remote-tracking branch — and the
# base is where floor_guard reads its waivers and the human-grant pin. A symbolic origin/HEAD that
# pointed at a local branch was used as-is.
DEFAULT_BASES = ("refs/remotes/origin/HEAD", "refs/remotes/origin/main",
                 "refs/remotes/origin/master", "refs/heads/main", "refs/heads/master")


ABBREVIATED_ID = re.compile(r"[0-9a-f]{4,63}")


def _abbreviated_commit(git, prefix):
    """``(commit, None)`` for the ONE commit object whose id starts with ``prefix``, or
    ``(None, why)``. ``rev-parse --disambiguate`` lists object ids by prefix and never consults
    refs, so a planted ``refs/heads/<prefix>`` is never what an abbreviation names (where
    ``rev-parse <prefix>`` tries the ref FIRST — independent re-attack)."""
    code, out = git("rev-parse", f"--disambiguate={prefix}")
    commits = []
    for oid in (out.split() if code == 0 else []):
        if COMMIT_ID.fullmatch(oid):
            kind_code, kind = git("cat-file", "-t", oid)
            if kind_code == 0 and kind.strip() == "commit":
                commits.append(oid)
    if len(commits) != 1:
        return None, (f"abbreviates {len(commits)} commit objects here, not one (an abbreviated id "
                      "is read as an object id only, never as a ref of that spelling)")
    return commits[0], None


def _short(ref):
    for prefix in (REMOTE_TRACKING, LOCAL_BRANCH):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref


def base_commit(git, base=None):
    """``(commit, shown, local, None)`` for a diff base, or ``(None, shown, None, why)``.

    Every name is looked up EXACTLY; nothing is handed to git to expand, and the caller diffs and
    reads at ``commit``, never at the name. ``shown`` is the human label. ``local`` is False for
    an anchor; for an ADVISORY base it says which kind ("a LOCAL branch", "HEAD, a LOCAL name",
    "an abbreviated commit id") — not a trust anchor (the checked change can move the first two,
    and nothing binds the third), so the caller refuses it on a lane claiming soundness
    (sound_lane) and says so in a NOTE elsewhere.

    Named: a full commit id or a full ``refs/remotes/…`` ref goes through remote_tracking_commit;
    a short name with a slash (``origin/main``) is the remote-tracking ref ``refs/remotes/<name>``
    under that rule and nothing else (never a tag or local branch of that spelling); ``HEAD`` is
    the checkout's HEAD; 4 to 63 hex digits are an ABBREVIATED commit id, resolved as an object id
    only (``rev-parse --disambiguate``, which never consults refs — a branch spelled like the
    abbreviation is never read) and only when it names exactly one commit; a full
    ``refs/heads/…`` ref or another bare name (``main``) is that local branch under its exact
    name; anything else — a tag, a revision suffix — is refused. Unnamed: DEFAULT_BASES in order,
    origin/HEAD's target included, the remote-tracking ones under remote_tracking_commit (one that
    points at a local branch is skipped), then the local main and master."""
    if base:
        if base.startswith("-"):
            return None, base, None, "is an option, not a ref"
        if COMMIT_ID.fullmatch(base.lower()) or base.startswith(REMOTE_TRACKING):
            commit, _target, why = remote_tracking_commit(git, base)
            return (commit, base, False, None) if commit else (None, base, None, why)
        if base == "HEAD":
            code, out = git("rev-parse", "--verify", "-q", "HEAD^{commit}")
            commit = out.strip()
            if code != 0 or not COMMIT_ID.fullmatch(commit):
                return None, base, None, "names no commit (an unborn or detached-broken HEAD)"
            return commit, base, "HEAD, a LOCAL name", None
        if ABBREVIATED_ID.fullmatch(base.lower()):
            commit, why = _abbreviated_commit(git, base.lower())
            return ((commit, base, "an abbreviated commit id", None) if commit
                    else (None, base, None, why))
        if base.startswith(LOCAL_BRANCH) or not (base.startswith("refs/") or "/" in base):
            full = base if base.startswith(LOCAL_BRANCH) else LOCAL_BRANCH + base
            commit, _target, why = local_branch_commit(git, full)
            return ((commit, base, "a LOCAL branch", None) if commit
                    else (None, base, None, f"({full}) {why}"))
        if base.startswith("refs/"):
            return None, base, None, ("is neither remote-tracking (refs/remotes/…) nor a local "
                                      "branch (refs/heads/…): a tag or other ref is no base")
        full = REMOTE_TRACKING + base
        commit, _target, why = remote_tracking_commit(git, full)
        return (commit, base, False, None) if commit else (None, base, None, f"({full}) {why}")
    skipped = []
    for name in DEFAULT_BASES:
        local = name.startswith(LOCAL_BRANCH)
        rule = local_branch_commit if local else remote_tracking_commit
        commit, target, why = rule(git, name)
        if commit is not None:
            return commit, _short(target), "a LOCAL branch" if local else False, None
        skipped.append(f"{name} {why}")
    return None, ", ".join(_short(n) for n in DEFAULT_BASES), None, "; ".join(skipped)

# ---------------------------------------------------------------------------------------------
# Git custody (W4-01/W4-02; PR #720 Codex round 3, shared since the W4 custody sweep)
# ---------------------------------------------------------------------------------------------
# driver_blanks lists the drivers a config declares and THEN the call reads that config again: a
# filter, textconv or merge driver a concurrent writer adds in between runs unblanked. A git that
# could apply an attribute-selected driver therefore never reads a config a worker can write: it
# runs against a git dir the coordinator builds (custody_git_dir), whose config declares no driver,
# so a driver added at any moment is simply undefined there. runtime/providers/posix.py run_git
# (every provider git) and the read-side tools (floor_guard, diff_scope, hint_provenance, verify's
# negative control) share what follows.

class GitCustodyRefused(OSError):
    """A git command the custody will not run: it could apply an attribute-selected driver (or
    otherwise run a program the repository names) and the custody has no driver-free way to run
    it, or the repository holds something the custody cannot honour or read safely. An OSError,
    so every caller's could-not-run handler applies: it is refused, never run."""


# Variables that choose the repository, worktree, index, object store or attribute source a git
# call reads, or that inject config, templates or git's own helper programs. Handed to a custody
# git in an inherited env, they pointed the call at a repository the custody never looked at, and
# its smudge filter ran (PR #720 Codex round 2): `-C`/cwd/`--git-dir`/`--work-tree` is the only
# way a custody call names its repository. custody_env() drops them.
SELECTOR_ENV = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_ATTR_SOURCE", "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_EXEC_PATH", "GIT_TEMPLATE_DIR",
})

# Fixed config keys, on top of the HARDENED floor, that name a program (or a transport that runs
# one) a custody-floored git could reach through the repository's config. A fixed key is
# overridden atomically on git's own command line (GIT_CONFIG_COUNT pairs outrank every config
# file), so no read-then-use window exists:
#   core.alternateRefsCommand - `fetch` runs it for an alternate the SHARED objects/info/alternates
#     names (the posix sandbox sync's fetch did, as the coordinator);
#   submodule.recurse / fetch.recurseSubmodules / status.submoduleSummary - git starts a CHILD git
#     in a submodule, under the submodule's own config (and without the replace/graft belt, which
#     git drops for it); the dirtiness probe a work-tree diff starts is NO_SUBMODULE_CHILD's;
#   log.showSignature + gpg.*.program - `log` verifying a signed commit runs gpg.program;
#   maintenance.auto / gc.auto - no auto-maintenance child after a fetch.
CUSTODY_FLOOR = (
    ("core.alternateRefsCommand", "exit 0"),
    ("submodule.recurse", "false"),
    ("fetch.recurseSubmodules", "false"),
    ("status.submoduleSummary", "false"),
    ("log.showSignature", "false"),
    ("gpg.program", os.devnull),
    ("gpg.openpgp.program", os.devnull),
    ("gpg.x509.program", os.devnull),
    ("gpg.ssh.program", os.devnull),
    ("maintenance.auto", "false"),
    ("gc.auto", "0"),
)
# Environment no repository config can outrank:
#   GIT_ALLOW_PROTOCOL=file - git documents it overrides ANY `protocol.*.allow`, so a worker's
#     `protocol.ssh.allow=always` cannot re-enable ssh (and `core.sshCommand`) for a
#     `url.ssh://....insteadOf=<path>` rewrite, nor `protocol.<helper>.allow=always` an
#     `<helper>::` remote (PR #720 Codex round 4);
#   GIT_NO_LAZY_FETCH=1 - a worker's `extensions.partialClone` + `remote.<n>.promisor` +
#     `remote.<n>.uploadpack=<payload>` makes even a plain `rev-parse <ref>^{commit}` lazily fetch
#     a missing object and run the payload (or a credential helper, or core.sshCommand) as the
#     coordinator; this refuses the fetch, so a missing object is a could-not-run instead.
CUSTODY_ENV = {"GIT_ALLOW_PROTOCOL": "file", "GIT_NO_LAZY_FETCH": "1"}

# Data-only (never a command) core.* settings that change whether a working-tree file reads clean
# or dirty, or which bytes a diff of it reads. Without them a custody `status` can read a clean
# worktree as modified (a false DIRTY that blocks an unforced removal): `filemode`/`symlinks` (an
# exec bit or a symlink the filesystem cannot keep), `ignorecase`/`precomposeunicode`/`protecthfs`/
# `protectntfs` (name folding), `sparsecheckout`/`sparsecheckoutcone` (cone matching for
# `info/sparse-checkout`), `autocrlf`/`eol` (built-in line-ending conversion), `checkstat`/
# `trustctime` (which stat fields count), `safecrlf`/`checkroundtripencoding` (when a conversion
# refuses). Read from the repository and passed as the custody call's own GIT_CONFIG pairs. NOT
# `core.excludesFile`: honouring a worker-set ignore file could HIDE an untracked file and lose its
# work, so the custody errs toward DIRTY there (`info/exclude`, the repo's own, is copied). NOT
# `core.attributesFile` either (a path the worker names, which git would open and read whatever
# it is); `info/attributes`, the repo's own, is copied (custody_git_dir).
CUSTODY_CORE_KEYS = (
    "filemode", "symlinks", "ignorecase", "precomposeunicode", "protecthfs", "protectntfs",
    "sparsecheckout", "sparsecheckoutcone", "autocrlf", "eol", "safecrlf", "checkroundtripencoding",
    "checkstat", "trustctime",
)
# Repository-format extensions the custody git dir reproduces (object format is written into its
# config; the others do not change the objects it reads through the alternate or the index it
# copies). Any OTHER `extensions.*` - `partialClone` above all - is refused: the custody dir cannot
# honour it, and guessing a verdict without it would be wrong (PR #720 Codex round 4).
HONOURABLE_EXTENSIONS = frozenset(
    b"objectformat compatobjectformat worktreeconfig refstorage relativeworktrees".split())

# The one option every custody git that compares the WORK TREE with a tree or the index carries.
# For a gitlink whose submodule is checked out, `diff`, `diff-files` and `status` otherwise start a
# child `git status` INSIDE the submodule to ask whether it is dirty, and that child runs under the
# submodule's own config and attributes - a filter (or anything else name-indexed) the custody
# never sees (Codex on PR #724). `dirty` still compares the submodule's checked-out commit with the
# one recorded (read from its refs in-process) and reports a moved gitlink; only the dirtiness
# probe - the child - is skipped. `git add` has no such option and ignores the config that would
# set it: a caller that stages a work tree must keep its gitlinks out of `add` (see wtree.sh).
NO_SUBMODULE_CHILD = "--ignore-submodules=dirty"


def custody_env(base=None, blanks=()):
    """env(base, blanks) for a git that must run nothing the repository names: SELECTOR_ENV
    dropped from ``base`` (os.environ when None), CUSTODY_FLOOR appended to the hardened pairs
    (before ``blanks``), and CUSTODY_ENV set last, where no config can outrank it."""
    src = os.environ if base is None else base
    out = env({k: v for k, v in src.items() if k not in SELECTOR_ENV},
              blanks=[*CUSTODY_FLOOR, *blanks])
    out.update(CUSTODY_ENV)
    return out


def _line(out):
    """One value git printed: its trailing newline removed and nothing else (a path may end in a
    space, `\\r` or `\\t`, which `.strip()` would cut)."""
    return out[:-1] if out[-1:] in ("\n", b"\n") else out


def _c_quote(raw):
    """``raw`` C-quoted as git reads a quoted `objects/info/alternates` line: any byte, `\\n` included."""
    return b'"' + b"".join(bytes([c]) if 0x20 <= c < 0x7F and c not in b'"\\' else b"\\%03o" % c
                           for c in raw) + b'"'


def _read_regular(path):
    """A worker-writable file's bytes and stat, read without following a symlink or blocking on a
    FIFO; None if absent. Anything but a regular file is a refusal, never a guess."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise GitCustodyRefused(f"git custody: cannot read {path!r} as a regular file: {exc}") from exc
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise GitCustodyRefused(f"git custody: {path!r} is not a regular file")
        return fh.read(), st


def _copy_regular(src, dst):
    """Copy ``src`` (bytes + mtime) to ``dst`` if it is a regular file; a missing one is skipped, a
    non-regular one refuses (so a worker FIFO or symlink at an expected path is never followed)."""
    got = _read_regular(src)
    if got is not None:
        with open(dst, "wb") as fh:
            fh.write(got[0])
        os.utime(dst, ns=(got[1].st_atime_ns, got[1].st_mtime_ns))


@contextlib.contextmanager
def custody_git_dir(common, object_format, head=None, gitdir=None, *, objects="alternate", bare=True):
    """A git dir the coordinator builds and no worker can name: its own config (no filter, diff or
    merge driver, so none can be added between a check and a use), the repository's objects, HEAD
    pinned to ``head`` (a commit id; None leaves it unborn), and copies of what a `status`/
    `read-tree`/`diff` there must read to match the repository's own verdict: the common
    `info/exclude`, `info/attributes` and `shallow`, and - when ``gitdir`` names the per-worktree
    admin dir - its
    `index` (mtime kept, so racy-git reads it as the repository does), every `sharedindex.<hash>`
    the index references (a split index, PR #720 Codex round 4) and `info/sparse-checkout`. The
    data-only `core.*` settings (filemode, ignorecase, sparse, ...) ride as the call's own
    GIT_CONFIG pairs (custody_settings), not this file. Removed on exit.

    ``objects``: "alternate" (the default) gives the dir an object store of its own whose
    `objects/info/alternates` names the repository's, so the repository's store is read and never
    written; "shared" makes `objects` a symlink to the repository's store, so an object the custody
    call writes (a merge-tree result, a sealed control commit) lands where a later git in the
    repository resolves it. Objects are content-addressed data: neither mode lets the repository
    name a command. ``bare=False`` writes `core.bare = false`, for a caller that reaches the dir
    through a `.git` gitfile in its work tree (verify.py's control) rather than `--work-tree`."""
    if object_format not in ("sha1", "sha256"):
        raise GitCustodyRefused(f"git custody: unknown object format {object_format!r}")
    if objects not in ("alternate", "shared"):
        raise ValueError(f"custody_git_dir: objects={objects!r}")
    root = tempfile.mkdtemp(prefix="open-fleet-git-custody-")
    try:
        for sub in ("refs/heads", "refs/tags", "info"):
            os.makedirs(os.path.join(root, sub))
        cfg = "[core]\n\trepositoryformatversion = {v}\n\tbare = {b}\n".format(
            v=0 if object_format == "sha1" else 1, b="true" if bare else "false")
        if object_format != "sha1":
            cfg += f"[extensions]\n\tobjectformat = {object_format}\n"
        with open(os.path.join(root, "config"), "w", encoding="utf-8") as fh:
            fh.write(cfg)
        with open(os.path.join(root, "HEAD"), "w", encoding="utf-8") as fh:
            fh.write(f"{head}\n" if head else "ref: refs/heads/open-fleet-unborn\n")
        if objects == "shared":
            os.symlink(os.path.join(common, "objects"), os.path.join(root, "objects"))
        else:
            os.makedirs(os.path.join(root, "objects", "info"))
            with open(os.path.join(root, "objects", "info", "alternates"), "wb") as fh:
                fh.write(_c_quote(os.fsencode(os.path.join(common, "objects"))) + b"\n")
        _copy_regular(os.path.join(common, "info", "exclude"), os.path.join(root, "info", "exclude"))
        # Data: `text`/`eol`/`working-tree-encoding`/`ident` steer how a work-tree file reads as a
        # blob (a CRLF checkout of an `eol=crlf` path is unchanged, not modified), and a line that
        # selects `filter=`/`diff=`/`merge=<name>` names a driver this config never defines.
        _copy_regular(os.path.join(common, "info", "attributes"), os.path.join(root, "info", "attributes"))
        _copy_regular(os.path.join(common, "shallow"), os.path.join(root, "shallow"))
        if gitdir is not None:
            _copy_regular(os.path.join(gitdir, "index"), os.path.join(root, "index"))
            _copy_regular(os.path.join(gitdir, "info", "sparse-checkout"), os.path.join(root, "info", "sparse-checkout"))
            for name in (sorted(os.listdir(gitdir)) if os.path.isdir(gitdir) else []):
                if name.startswith("sharedindex."):
                    _copy_regular(os.path.join(gitdir, name), os.path.join(root, name))
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def custody_facts(run):
    """``{gitdir, common, format, top, head}`` of the repository ``run`` names, where ``run(args)``
    runs ``git <args>`` there (under a custody floor) and returns a CompletedProcess with BYTES
    output. ``top`` is None for a repository with no work tree and ``head`` for an unborn HEAD;
    the others missing is a refusal (GitCustodyRefused). Only rev-parse runs, which reads refs and
    paths and never a working-tree file."""
    def rev_parse(*args):
        proc = run(["rev-parse", *args])
        return os.fsdecode(_line(proc.stdout)) if proc.returncode == 0 and proc.stdout else None
    facts = {
        "gitdir": rev_parse("--absolute-git-dir"),
        "common": rev_parse("--path-format=absolute", "--git-common-dir"),
        "format": rev_parse("--show-object-format"),
        "top": rev_parse("--show-toplevel"),
        "head": rev_parse("--verify", "-q", "HEAD^{commit}"),
    }
    if not (facts["gitdir"] and facts["common"] and facts["format"]):
        raise GitCustodyRefused("git custody: cannot resolve the repository this call names")
    return facts


def custody_settings(run):
    """The data-only `core.*` pairs (CUSTODY_CORE_KEYS) the repository ``run`` names declares (see
    custody_facts for ``run``), read effectively (`config --get`, honouring `includeIf` and
    `extensions.worktreeConfig`), to pass as a custody call's own GIT_CONFIG pairs so its `status`/
    `read-tree`/`diff` matches the repository's own clean/dirty verdict. Refuses first if the
    repository declares any `extensions.*` the custody git dir cannot honour (a partial clone above
    all): the verdict would be wrong (PR #720 Codex round 4). Reads bytes; never runs a config VALUE
    (these keys are data, not commands)."""
    ext = run(["config", "-z", "--get-regexp", r"^extensions\."])
    if ext.returncode not in (0, 1):
        raise GitCustodyRefused("git custody: cannot read the repository's extensions: "
                                f"{os.fsdecode(ext.stderr).strip()[:200]}")
    for record in ext.stdout.split(b"\0"):
        if not record:
            continue
        name = record.split(b"\n", 1)[0].split(b".", 1)[1].lower()
        if name not in HONOURABLE_EXTENSIONS:
            raise GitCustodyRefused(f"git custody: the repository declares extensions.{os.fsdecode(name)}, "
                                    "which the custody git dir cannot honour")
    pairs = []
    for key in CUSTODY_CORE_KEYS:
        got = run(["config", "-z", "--get", f"core.{key}"])
        if got.returncode == 0 and got.stdout:
            pairs.append((f"core.{key}", os.fsdecode(got.stdout.split(b"\0")[0])))
    return pairs


class Custody:
    """Where a content-reading git runs in custody: ``lead`` is its global options - ``-C <cwd>``
    (the directory the caller named, so relative paths and pathspecs mean what they meant), then
    ``--git-dir`` (the coordinator-built dir) and ``--work-tree`` (the repository's own top) - and
    ``pairs`` the repository's data-only core settings (custody_settings), GIT_CONFIG pairs the call
    carries beside CUSTODY_FLOOR. With no ``git_dir`` the lead is ``-C <cwd>`` alone: the call runs in the repository
    itself, outside custody (what a mutation control uses to show the custody is load-bearing)."""

    def __init__(self, git_dir, work_tree, pairs, cwd):
        self.git_dir, self.work_tree, self.pairs, self.cwd = git_dir, work_tree, list(pairs), str(cwd)

    @property
    def lead(self):
        if self.git_dir is None:
            return ["-C", self.cwd]
        return ["-C", self.cwd, "--git-dir", self.git_dir,
                *(["--work-tree", self.work_tree] if self.work_tree else [])]

    def argv(self, *args):
        """argv() for ``git <lead> <args>``."""
        return argv(*self.lead, *args)

    def env(self, base=None, blanks=()):
        """custody_env() carrying this custody's pairs, then ``blanks``."""
        return custody_env(base, blanks=[*self.pairs, *blanks])


@contextlib.contextmanager
def custody(repo, *, run=None, index=True, objects="alternate", base=None, timeout=60):
    """A Custody for a git that reads ``repo``'s working-tree content (a `diff` of the work tree,
    a `merge-tree`): the repository's facts and data-only settings read through ``run`` (default:
    gitexec's own git under custody_env, at ``repo``), then a custody_git_dir over its objects with
    its index (``index=True``), HEAD at its HEAD commit, and the work tree its own top. Nothing in
    the dir names a filter, textconv, diff or merge driver, so a `.gitattributes` or
    `info/attributes` line selecting one selects nothing, and a driver added to the repository's
    config while the call runs is never read. Raises GitCustodyRefused (an OSError) when the
    repository cannot be resolved or declares an extension the custody cannot honour."""
    if run is None:
        def run(args):
            return subprocess.run(argv("-C", str(repo), *args), capture_output=True, timeout=timeout,
                                  env=custody_env(base), stdin=subprocess.DEVNULL)
    facts = custody_facts(run)
    pairs = custody_settings(run)
    with custody_git_dir(facts["common"], facts["format"], facts["head"],
                         facts["gitdir"] if index else None, objects=objects) as gd:
        yield Custody(gd, facts["top"], pairs, repo)
