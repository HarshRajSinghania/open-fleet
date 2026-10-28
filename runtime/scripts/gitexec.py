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
worker writes (W4-01).

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
any ``--attr-source`` the belt could set). ``driver_blanks(repo)`` closes them by reading
the driver names the repo's OWN config declares and blanking each — the only place such a
command can come from. A worktree-materialising read (floor_guard's, diff_scope's and
hint_provenance's ``diff`` of the working tree, _trajectories.py's replay, verify.py's
negative-control ``checkout``) passes its pairs;
a read of committed objects alone (inventory, decisions ``--pin-ref``) never selects a
filter and does not need them. The listing and the call are two steps: a driver a concurrent
writer of that config adds between them runs unblanked, so the pairs close the channel only for
a config nobody writes while the call runs. The providers' git custody (runtime/providers/posix.py
``run_git``) does not rely on them: a provider git that could apply a driver runs against a git
dir the coordinator builds, whose config declares none (PR #720 Codex round 3).

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

``remote_tracking_commit(git, name)`` is the one rule a TRUST ANCHOR named by its caller answers
to (W3-07): a commit id, read as an object id only, or a full ``refs/remotes/…`` ref that exists
under exactly that name, every symbolic hop remote-tracking too. It holds the rule, not a git:
each caller passes its own executor (verify.py its custody-classed one), so decisions.py
``--pin-ref``, gate-batch.py ``--pin-ref``, run_report.py's trusted base, verify.py's trust keys
and release_check.py's gate-1 anchor resolve a name the same way. verify-gate.sh mirrors it in sh.

Library only: no CLI, no exit codes.
"""
import os
import re
import shutil
import subprocess


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
    code, out = git("for-each-ref", "--format=%(refname)%00%(symref)%00%(objectname)", namespace)
    if code != 0:
        return None, name, "could not be looked up: git for-each-ref failed"
    listed = {}
    for line in out.splitlines():
        fields = line.split("\0")
        if len(fields) == 3:
            listed[fields[0]] = (fields[1], fields[2])
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
        # %(symref) above is the chain's END; the next hop is read on its own.
        code, out = git("symbolic-ref", "-q", "--no-recurse", target)
        hop = out.strip() if code == 0 else ""
        if not hop:
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


def _short(ref):
    for prefix in (REMOTE_TRACKING, LOCAL_BRANCH):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref


def base_commit(git, base=None):
    """``(commit, shown, local, None)`` for a diff base, or ``(None, shown, None, why)``.

    Every name is looked up EXACTLY; nothing is handed to git to expand, and the caller diffs and
    reads at ``commit``, never at the name. ``shown`` is the human label; ``local`` is True when
    the base is a local branch — not a trust anchor (the checked change can move one), so the
    caller refuses it on a lane claiming soundness (sound_lane) and says so in a NOTE elsewhere.

    Named: a commit id or a full ``refs/remotes/…`` ref goes through remote_tracking_commit; a
    short name with a slash (``origin/main``) is the remote-tracking ref ``refs/remotes/<name>``
    under that rule and nothing else (never a tag or local branch of that spelling); a full
    ``refs/heads/…`` ref or a bare name (``main``) is that local branch under its exact name;
    anything else — a tag, ``HEAD``, a revision suffix — is refused. Unnamed: DEFAULT_BASES in
    order, origin/HEAD's target included, the remote-tracking ones under remote_tracking_commit
    (one that points at a local branch is skipped), then the local main and master."""
    if base:
        if base.startswith("-"):
            return None, base, None, "is an option, not a ref"
        if COMMIT_ID.fullmatch(base.lower()) or base.startswith(REMOTE_TRACKING):
            commit, _target, why = remote_tracking_commit(git, base)
            return (commit, base, False, None) if commit else (None, base, None, why)
        if base.startswith(LOCAL_BRANCH) or not (base.startswith("refs/") or "/" in base):
            full = base if base.startswith(LOCAL_BRANCH) else LOCAL_BRANCH + base
            commit, _target, why = local_branch_commit(git, full)
            return (commit, base, True, None) if commit else (None, base, None, f"({full}) {why}")
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
            return commit, _short(target), local, None
        skipped.append(f"{name} {why}")
    return None, ", ".join(_short(n) for n in DEFAULT_BASES), None, "; ".join(skipped)
