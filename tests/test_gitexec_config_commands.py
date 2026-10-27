#!/usr/bin/env python3
"""#629: the coordinator-side gates must not run a command the worker named in its own repo.

Global and system git config were already off, but a worker that can write its worktree's
`.git/config` (and `.git/info/attributes`) could still get a command run on the COORDINATOR
the next time a gate diffs or reads its work, through a repository-config channel git honours:

  - a `filter.<driver>.clean/smudge/process` selected by `.gitattributes`, run when a gate
    materialises or diffs a working-tree file;
  - `core.fsmonitor`, run on `status`/`add`;
  - and the diff/textconv/hook/replace/graft channels the fixed belt and the
    `--no-ext-diff`/`--no-textconv` flags already closed, pinned here so they stay closed.

Each gate is driven the way the coordinator runs it, against a repo whose config names a
harmless probe that only touches a marker file in this test's temp dir. GREEN = the marker
is never created. Every case carries its mutation control: with the hardening removed the
marker comes back, so the test proves the hardening is load-bearing, not that the channel
was dormant. Stdlib only; no network.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "runtime" / "scripts"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gitexec = _load("gitexec", "gitexec.py")
floor_guard = _load("floor_guard", "floor_guard.py")
diff_scope = _load("diff_scope", "diff_scope.py")
evidence_run = _load("evidence_run", "evidence-run.py")


def _load_with_siblings(name, filename):
    """hint_provenance imports its siblings by name (diff_scope, gitexec), as it does when it runs
    from runtime/scripts/; the directory is on the path only while it loads."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        return _load(name, filename)
    finally:
        sys.path.remove(str(SCRIPTS))


hint_provenance = _load_with_siblings("hint_provenance", "hint_provenance.py")

# The setup git runs with global/system config off, so the only driver the fixtures declare is
# the probe (a stray ~/.gitconfig git-lfs filter never changes a test's outcome).
_CLEAN_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class _Probe:
    """A git repo whose config names a probe on every exec channel. The probe appends ONE token
    per fire to a marker file; `fired()` returns the set of channels seen."""

    def __init__(self, tmp):
        self.dir = Path(tmp)
        self.repo = self.dir / "repo"
        self.marker = self.dir / "marker"
        self.probe = self.dir / "probe.sh"
        # The probe ONLY touches its marker and never reads stdin: git hands an fsmonitor hook
        # its own stdin, so a probe that read it blocked forever under an inherited pipe that
        # never closes. A filter that fires is the failure under test, so what it outputs (here,
        # nothing) never matters to a GREEN case; the 'process' protocol is never selected.
        self.probe.write_text('#!/bin/sh\necho "$1" >> ' + _sh(self.marker) + "\nexit 0\n",
                              encoding="utf-8")
        self.probe.chmod(0o755)
        self.repo.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")
        self._git("config", "user.email", "a@b")
        self._git("config", "user.name", "a")

    def _git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args], env=_CLEAN_ENV,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)

    def commit(self, name, body):
        (self.repo / name).write_text(body, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", name)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def arm_filter(self, pattern="*.txt"):
        """Select a clean/smudge filter whose command is the probe, via $GIT_DIR/info/attributes
        (the vector --attr-source cannot override) so blanking the config command is the only
        defence."""
        for key in ("filter.p.clean", "filter.p.smudge"):
            self._git("config", key, f"{self.probe} {key.split('.')[-1]}")
        info = self.repo / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "attributes").write_text(f"{pattern} filter=p\n", encoding="utf-8")

    def arm_fsmonitor(self):
        self._git("config", "core.fsmonitor", f"{self.probe} fsmonitor")

    def fired(self):
        if not self.marker.exists():
            return set()
        seen = {ln.strip() for ln in self.marker.read_text().splitlines() if ln.strip()}
        self.marker.unlink()
        return seen


def _sh(path):
    return "'" + str(path).replace("'", "'\\''") + "'"


class GitexecDriverBlanks(unittest.TestCase):
    """gitexec.driver_blanks reads the driver names the repo's OWN config declares and blanks
    each command — the attribute-selected channel a fixed -c cannot name."""

    def _repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        p.commit("a.txt", "one\n")
        return p

    def test_a_clean_repo_declares_no_drivers(self):
        self.assertEqual(gitexec.driver_blanks(self._repo().repo), [])

    def test_every_declared_filter_and_diff_driver_command_is_blanked(self):
        p = self._repo()
        p._git("config", "filter.media.clean", "danger clean")
        p._git("config", "filter.media.smudge", "danger smudge")
        p._git("config", "filter.media.process", "danger process")
        p._git("config", "diff.jpg.textconv", "danger textconv")
        p._git("config", "diff.jpg.command", "danger command")
        # A driver name with a dot is still one subsection, so it is still covered.
        p._git("config", "filter.my.lfs.clean", "danger clean")
        # (key, value) pairs for gitexec.env(blanks=...), each key exactly as declared, each
        # value empty (git runs no command): an env pair, never a `-c` token (PR #649 review).
        # A filter is neutralised WHOLE — every command blank and required=false (PR #649).
        self.assertEqual(set(gitexec.driver_blanks(p.repo)), {
            ("filter.media.clean", ""), ("filter.media.smudge", ""), ("filter.media.process", ""),
            ("filter.media.required", "false"),
            ("diff.jpg.textconv", ""), ("diff.jpg.command", ""),
            ("filter.my.lfs.clean", ""), ("filter.my.lfs.smudge", ""),
            ("filter.my.lfs.process", ""), ("filter.my.lfs.required", "false")})

    def test_a_non_command_key_is_not_blanked(self):
        p = self._repo()
        p._git("config", "filter.media.required", "true")
        p._git("config", "diff.jpg.binary", "true")
        # PR #649 review (PRRT_kwDOTWxN9c6vvon0): a declared filter is neutralised whole even with
        # no command (git dies on a required one), while a diff driver's non-command key is not.
        self.assertEqual(gitexec.driver_blanks(p.repo), [
            ("filter.media.clean", ""), ("filter.media.smudge", ""),
            ("filter.media.process", ""), ("filter.media.required", "false")])

    def test_the_toolchain_copies_blank_exactly_what_gitexec_blanks(self):
        # diff_scope.py inlines driver_blanks and verify.py's _Authority mirrors it (each runs its
        # own git under its own env); a copy that falls behind reopens the channel at that gate.
        verify = _load("verify_parity", "verify.py")
        verify._Authority.reset()
        self.addCleanup(verify._Authority.reset)
        p = self._repo()
        for key in ("filter.media.clean", "filter.media.smudge", "filter.media.process",
                    "diff.jpg.textconv", "diff.jpg.command", "filter.my.lfs.clean",
                    "merge.union.driver", "merge.union.recursive", "merge.inner.driver"):
            p._git("config", key, "danger")
        p._git("config", "filter.media.required", "true")
        want = gitexec.driver_blanks(p.repo)
        # 8 filter + 2 diff + 2 merge (union, inner — one driver override per declared name).
        self.assertEqual(len(want), 12)
        self.assertIn(("merge.union.driver", "exit 1"), want)
        self.assertIn(("merge.inner.driver", "exit 1"), want)
        self.assertEqual(diff_scope._driver_blanks(p.repo), want)
        self.assertEqual(verify._Authority.driver_blanks(p.repo), want)

    def test_a_git_dir_reads_the_config_that_git_dir_resolves(self):
        # W4-01: posix.py names a worktree by its admin git dir (`--git-dir`) and never through the
        # worktree's own `.git` pointer, so the drivers come from where that call runs: here a
        # linked worktree's admin dir, whose `includeIf gitdir:` the main checkout never matches.
        p = self._repo()
        inc = p.dir / "linked-only.gitconfig"
        inc.write_text('[filter "inc"]\n\tsmudge = danger\n', encoding="utf-8")
        p._git("config", "includeIf.gitdir:**/worktrees/**.path", str(inc))
        p._git("worktree", "add", "-q", "--detach", str(p.dir / "wt"))
        admin = p.repo / ".git" / "worktrees" / "wt"
        linked = gitexec.driver_blanks(None, git_dir=admin)
        self.assertIn(("filter.inc.smudge", ""), linked)
        self.assertEqual(linked, gitexec.driver_blanks(p.dir / "wt"))
        self.assertEqual(gitexec.driver_blanks(None, git_dir=p.repo / ".git"), [])


class StaticBeltClosesTheFixedKeyChannels(unittest.TestCase):
    """The env belt (command-line precedence, so it overrides repo .git/config) names every
    command-bearing key a fixed -c can name."""

    def test_belt_pins_the_command_bearing_keys(self):
        env = gitexec.env({"LANG": "C"})
        pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
                 for i in range(int(env["GIT_CONFIG_COUNT"]))}
        self.assertEqual(pairs["core.fsmonitor"], "false")
        self.assertEqual(pairs["core.hooksPath"], os.devnull)
        self.assertEqual(pairs["diff.external"], "")
        self.assertEqual(pairs["protocol.ext.allow"], "never")
        self.assertEqual(env["GIT_NO_REPLACE_OBJECTS"], "1")
        self.assertEqual(env["GIT_GRAFT_FILE"], os.devnull)

    def test_an_inherited_config_channel_neither_blinds_nor_outranks_the_floor(self):
        # W4-07 sweep: GIT_CONFIG_PARAMETERS (inherited `-c` pairs) is read AFTER the
        # GIT_CONFIG_COUNT pairs, so it outranks the floor; GIT_CONFIG names the ONE file
        # `git config --list` reads, so driver_blanks listed nothing while `diff`/`add` still
        # loaded the repo config and ran its filter. Neither reaches a floored child.
        inherited = {"GIT_CONFIG": os.devnull, "GIT_CONFIG_PARAMETERS": "'core.fsmonitor'='danger'"}
        env = gitexec.env(inherited)
        self.assertNotIn("GIT_CONFIG", env)
        self.assertNotIn("GIT_CONFIG_PARAMETERS", env)
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        p.commit("a.txt", "one\n")
        p._git("config", "filter.media.clean", "danger")
        with mock.patch.dict(os.environ, inherited):
            self.assertIn(("filter.media.clean", ""), gitexec.driver_blanks(p.repo))
            got = subprocess.run(gitexec.argv("-C", str(p.repo), "config", "--get", "core.fsmonitor"),
                                 env=gitexec.env(), capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(got.stdout.strip(), "false")

    def test_diff_scope_drops_the_same_inherited_channels(self):
        # diff_scope inlines the floor (it is in the verifier toolchain), so it must drop the same
        # inherited variables gitexec drops, or its own driver enumeration is blinded.
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        p.commit("a.txt", "one\n")
        p._git("config", "filter.media.clean", "danger")
        inherited = {k: "x" for k in gitexec._INHERITED_DROPPED}
        inherited["GIT_CONFIG"] = os.devnull
        with mock.patch.dict(os.environ, inherited):
            env = diff_scope._git_env()
            self.assertIn(("filter.media.clean", ""), diff_scope._driver_blanks(p.repo))
        self.assertEqual(set(env) & gitexec._INHERITED_DROPPED, set())

    def test_diff_scope_mirrors_the_whole_gitexec_floor(self):
        env = diff_scope._git_env()
        plain = {k: v for k, v in gitexec.HARDENED.items()
                 if not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_", "GIT_CONFIG_COUNT"))}
        self.assertEqual({k: env.get(k) for k in plain}, plain)

        def pairs(e):
            return {e[f"GIT_CONFIG_KEY_{i}"]: e[f"GIT_CONFIG_VALUE_{i}"]
                    for i in range(int(e["GIT_CONFIG_COUNT"]))}
        ours = pairs(env)
        self.assertEqual({k: ours.get(k) for k in pairs(gitexec.HARDENED)}, pairs(gitexec.HARDENED))


class FloorGuardWorktreeDiff(unittest.TestCase):
    """floor_guard diffs the working tree against the base — which runs a repo-config clean
    filter a .gitattributes selects, the one channel --no-ext-diff/--no-textconv leave open."""

    def _repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        base = p.commit("a.txt", "line1\nline2\n")
        p.arm_filter()
        (p.repo / "a.txt").write_text("line1\nCHANGED\n", encoding="utf-8")
        (p.repo / "b.txt").write_text("brand new\n", encoding="utf-8")  # untracked -> --no-index
        return p, base

    def _collect(self, p, base):
        mb = floor_guard.merge_base(p.repo, base)
        floor_guard.collect_diff(p.repo, mb)

    def test_no_driver_command_runs_when_the_guard_reads_the_diff(self):
        p, base = self._repo()
        self._collect(p, base)
        self.assertEqual(p.fired(), set(), "a repo-config filter ran inside floor_guard")

    def test_mutation_control_without_the_blanks_the_filter_fires(self):
        p, base = self._repo()
        with mock.patch.object(floor_guard.gitexec, "driver_blanks", lambda repo: []):
            self._collect(p, base)
        self.assertIn("clean", p.fired(),
                      "control: with the driver blanks removed the clean filter must fire")


class DiffScopeWorktreeDiff(unittest.TestCase):
    """diff_scope classifies the changed paths, diffing the working tree against the base."""

    def _repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        base = p.commit("a.txt", "line1\nline2\n")
        p.arm_filter()
        (p.repo / "a.txt").write_text("line1\nCHANGED\n", encoding="utf-8")
        return p, base

    def test_no_driver_command_runs_when_scope_reads_the_diff(self):
        p, base = self._repo()
        diff_scope.scope(p.repo, base)
        self.assertEqual(p.fired(), set(), "a repo-config filter ran inside diff_scope")

    def test_mutation_control_without_the_blanks_the_filter_fires(self):
        p, base = self._repo()
        with mock.patch.object(diff_scope, "_driver_blanks", lambda repo: []):
            diff_scope.scope(p.repo, base)
        self.assertIn("clean", p.fired(),
                      "control: with the driver blanks removed the clean filter must fire")


class HintProvenanceWorktreeDiff(unittest.TestCase):
    """hint_provenance reads a worker's live checkout to decide whether a recorded hint is still
    current: in working-tree mode changes_since() diffs the disk against the hint's source rev,
    which runs a repo-config clean filter a `$GIT_DIR/info/attributes` line selects."""

    def _repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        base = p.commit("a.txt", "line1\nline2\n")
        p.arm_filter()
        (p.repo / "a.txt").write_text("line1\nCHANGED\n", encoding="utf-8")
        return p, base

    def _changes(self, p, base):
        return hint_provenance.LiveSource(str(p.repo)).changes_since(base)

    def test_no_driver_command_runs_when_a_hint_reads_the_live_tree(self):
        p, base = self._repo()
        self.assertEqual(self._changes(p, base), {"a.txt": ("M", None)})
        self.assertEqual(p.fired(), set(), "a repo-config filter ran inside hint_provenance")

    def test_mutation_control_without_the_blanks_the_filter_fires(self):
        p, base = self._repo()
        with mock.patch.object(hint_provenance.gitexec, "driver_blanks", lambda repo: []):
            self._changes(p, base)
        self.assertIn("clean", p.fired(),
                      "control: with the driver blanks removed the clean filter must fire")


class WtreeFingerprint(unittest.TestCase):
    """evidence-run.py fingerprints the working tree through wtree.sh (`git add -A` + write-tree),
    which runs both core.fsmonitor and a selected clean filter against the worker's repo."""

    def _repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        p.commit("a.txt", "line1\nline2\n")
        p.arm_filter()
        p.arm_fsmonitor()
        (p.repo / "a.txt").write_text("line1\nDIRTY\n", encoding="utf-8")  # dirty -> add re-hashes
        return p

    def test_the_fingerprint_runs_no_config_command(self):
        p = self._repo()
        out, err = evidence_run.working_tree_fingerprint(str(p.repo))
        self.assertEqual(p.fired(), set(), "wtree.sh ran a repo-config command on the coordinator")
        # The dirty a.txt is filtered by the repo-declared `p`: unverifiable without running it, so
        # wtree.sh refuses honestly (exit 3) rather than fingerprint unfiltered bytes (PR #649).
        self.assertIsNone(out)
        self.assertIsInstance(err, evidence_run.WtreeUnverifiable)

    def test_mutation_control_a_stripped_wtree_fires_fsmonitor_and_the_filter(self):
        # The control is a COPY of wtree.sh with the two hardening hunks removed, run the same way,
        # so the planted channels prove they were dormant only because of the hardening.
        p = self._repo()
        src = (SCRIPTS / "wtree.sh").read_text(encoding="utf-8")
        # Every hardening pair — the env belt and the driver blanks — rides the GIT_CONFIG_* pairs
        # wtree.sh exports, counted by one final assignment (PR #649). Zero it: core.fsmonitor is
        # honoured again and no filter key is blanked.
        self.assertEqual(src.count("GIT_CONFIG_COUNT=$_n"), 1, "the count assignment moved")
        stripped = src.replace("GIT_CONFIG_COUNT=$_n", "GIT_CONFIG_COUNT=0")
        self.assertNotEqual(stripped, src, "the control did not change wtree.sh")
        mutant = p.dir / "wtree_control.sh"
        mutant.write_text(stripped, encoding="utf-8")
        subprocess.run(["sh", str(mutant), str(p.repo)], capture_output=True, timeout=120,
                       stdin=subprocess.DEVNULL)
        self.assertTrue(p.fired() & {"clean", "fsmonitor"},
                        "control: the stripped wtree.sh must run a planted channel")


# PR #649 review (PRRT_kwDOTWxN9c6vvony): a driver name is BYTES. git accepts 0xff, an invalid
# UTF-8 sequence, a `.` or an `=` in a `filter.<driver>.*` subsection, and a .gitattributes line
# selects that exact name. A blank that decodes the name as text (0xff -> U+FFFD) names a
# different driver, and one passed as `-c <key>=` splits a name holding `=` at its first `=`;
# either way the planted command still runs. Whitespace cannot be selected by an attribute, so
# those names are checked at the enumeration only.
_SELECTABLE = (b"\xff", b"\xc3\x28", b"x\x80y", b"\xed\xa0\x80", b"a.b", b"a=b")
_UNSELECTABLE = (b"a b", b"a\tb")


def _bgit(repo, *args):
    """git with BYTES argv, so a non-UTF-8 driver name reaches git exactly."""
    argv = [b"git", b"-C", os.fsencode(str(repo))]
    argv += [a if isinstance(a, bytes) else a.encode("utf-8") for a in args]
    return subprocess.run(argv, env=_CLEAN_ENV, capture_output=True, stdin=subprocess.DEVNULL,
                          timeout=60)


class ByteExactDriverNames(unittest.TestCase):
    """Every gate blanks the driver the attribute ACTUALLY selects, byte for byte."""

    def _repo(self, name, filtered="*.txt"):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        base = p.commit("a.txt", "line1\nline2\n")
        r = _bgit(p.repo, b"config", b"filter." + name + b".clean", os.fsencode(str(p.probe)) + b" clean")
        self.assertEqual(r.returncode, 0, r.stderr)
        info = p.repo / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "attributes").write_bytes(filtered.encode() + b" filter=" + name + b"\n")
        (p.repo / "a.txt").write_text("line1\nCHANGED\n", encoding="utf-8")
        # Positive control: plain git runs the planted filter, so a GREEN below is not vacuous.
        _bgit(p.repo, "diff", "--no-ext-diff", "--no-textconv", "HEAD", "--")
        self.assertIn("clean", p.fired(), f"the planted {name!r} filter is not live on bare git")
        return p, base

    def test_floor_guard_runs_no_filter_whatever_its_name(self):
        for name in _SELECTABLE:
            with self.subTest(name=name):
                p, base = self._repo(name)
                floor_guard.collect_diff(p.repo, floor_guard.merge_base(p.repo, base))
                self.assertEqual(p.fired(), set(), f"floor_guard ran the {name!r} filter")

    def test_diff_scope_runs_no_filter_whatever_its_name(self):
        for name in _SELECTABLE:
            with self.subTest(name=name):
                p, base = self._repo(name)
                diff_scope.scope(p.repo, base)
                self.assertEqual(p.fired(), set(), f"diff_scope ran the {name!r} filter")

    def test_the_wtree_fingerprint_runs_no_filter_whatever_its_name(self):
        for name in _SELECTABLE:
            with self.subTest(name=name):
                p, _ = self._repo(name)
                out, err = evidence_run.working_tree_fingerprint(str(p.repo))
                self.assertEqual(p.fired(), set(), f"wtree.sh ran the {name!r} filter")
                # Refused as unverifiable (PR #649): which also proves the attribute's value and the
                # declared name matched byte for byte, or a fingerprint would have been printed.
                self.assertIsNone(out)
                self.assertIsInstance(err, evidence_run.WtreeUnverifiable)

    def test_the_enumeration_names_the_exact_declared_bytes(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        p.commit("a.txt", "one\n")
        for name in _SELECTABLE + _UNSELECTABLE:
            self.assertEqual(_bgit(p.repo, b"config", b"filter." + name + b".clean", b"x").returncode, 0)
        keys = {os.fsencode(k) for k, v in gitexec.driver_blanks(p.repo) if v == ""}
        for name in _SELECTABLE + _UNSELECTABLE:
            self.assertIn(b"filter." + name + b".clean", keys, f"{name!r} is not blanked byte-exactly")

    def test_the_toolchain_copies_enumerate_the_same_bytes(self):
        verify = _load("verify_bytes_parity", "verify.py")
        verify._Authority.reset()
        self.addCleanup(verify._Authority.reset)
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        p.commit("a.txt", "one\n")
        for name in _SELECTABLE + _UNSELECTABLE:
            _bgit(p.repo, b"config", b"filter." + name + b".clean", b"x")
        want = gitexec.driver_blanks(p.repo)
        self.assertTrue(want)
        self.assertEqual(diff_scope._driver_blanks(p.repo), want)
        self.assertEqual(verify._Authority.driver_blanks(p.repo), want)


# PR #649 review (PRRT_kwDOTWxN9c6vvon0): `filter.<driver>.required=true` makes git DIE when the
# filter does not run (`clean filter '<driver>' failed`) — with its command blanked, or with no
# command declared at all. A worker could plant one and stop every gate that reads a matching
# file: a denial of service on the coordinator. Each gate must override it to false, run
# nothing, and still read the working-tree bytes exactly as they are.
_RAW_LINE = "RAW-WORKTREE-LINE"


class RequiredFilters(unittest.TestCase):

    def _repo(self, with_command):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        base = p.commit("a.txt", "line1\nline2\n")
        p._git("config", "filter.req.required", "true")
        if with_command:
            for var in ("clean", "smudge"):
                p._git("config", f"filter.req.{var}", f"{p.probe} {var}")
        info = p.repo / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "attributes").write_text("*.txt filter=req\n", encoding="utf-8")
        (p.repo / "a.txt").write_text(f"line1\n{_RAW_LINE}\n", encoding="utf-8")
        (p.repo / "b.txt").write_text("brand new\n", encoding="utf-8")
        # Positive control: plain git honours the required filter — it runs the planted command,
        # or, with none declared, dies — so a GREEN below is not vacuous.
        plain = p._git("diff", "--no-ext-diff", "--no-textconv", "HEAD", "--")
        if with_command:
            self.assertIn("clean", p.fired(), "the planted required filter is not live")
        else:
            self.assertNotEqual(plain.returncode, 0, "a required filter with no command did not stop git")
            self.assertIn("filter 'req' failed", plain.stderr)
        return p, base

    def test_floor_guard_reads_raw_bytes_and_neither_runs_nor_dies(self):
        for with_command in (True, False):
            with self.subTest(with_command=with_command):
                p, base = self._repo(with_command)
                text = floor_guard.collect_diff(p.repo, floor_guard.merge_base(p.repo, base))
                self.assertIn("+" + _RAW_LINE, text)
                self.assertIn("+brand new", text)
                self.assertEqual(p.fired(), set(), "floor_guard ran the required filter")

    def test_diff_scope_reads_the_change_and_neither_runs_nor_dies(self):
        for with_command in (True, False):
            with self.subTest(with_command=with_command):
                p, base = self._repo(with_command)
                self.assertIn("a.txt", diff_scope.changed_files(p.repo, base))
                diff_scope.scope(p.repo, base)
                self.assertEqual(p.fired(), set(), "diff_scope ran the required filter")

    def test_the_wtree_fingerprint_refuses_honestly_and_neither_runs_nor_dies(self):
        # The changed a.txt is filtered by the repo-declared `req`: wtree.sh does not run it, does
        # not die on `required`, and refuses as unverifiable (exit 3) instead of printing a tree of
        # bytes the committed one was never built from (PR #649 review, PRRT_kwDOTWxN9c6vwb7P).
        for with_command in (True, False):
            with self.subTest(with_command=with_command):
                p, _ = self._repo(with_command)
                out, err = evidence_run.working_tree_fingerprint(str(p.repo))
                self.assertEqual(p.fired(), set(), "wtree.sh ran the required filter")
                self.assertIsNone(out)
                self.assertIsInstance(err, evidence_run.WtreeUnverifiable)
                self.assertNotIn("filter 'req' failed", err)

    def test_the_enumeration_overrides_required_for_every_declared_filter(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        p.commit("a.txt", "one\n")
        p._git("config", "filter.req.required", "true")      # no command at all
        p._git("config", "diff.jpg.binary", "true")           # not a command: nothing to blank
        blanks = dict(gitexec.driver_blanks(p.repo))
        self.assertEqual(blanks.get("filter.req.required"), "false")
        for var in ("clean", "smudge", "process"):
            self.assertEqual(blanks.get(f"filter.req.{var}"), "")
        self.assertFalse([k for k in blanks if k.startswith("diff.jpg.")], blanks)


# PR #649 review (PRRT_kwDOTWxN9c6vwb7P): with a REPO-declared clean filter blanked, a filtered file
# whose stat changed is re-staged from its smudged working-tree bytes, so the fingerprint differs
# from HEAD and a good run read as STALE. Mapping those bytes back to the committed clean blob
# needs the repository's own command, which the coordinator must not run. wtree.sh therefore says
# so: exit 3 with the reason, which evidence-run.py records and verify.py check_commands reports in
# place of "STALE". An untouched file still fingerprints as HEAD (the stat cache never re-hashes),
# and a filter declared in the coordinator's OWN global config still runs, so it keeps fidelity.
_UNVERIFIABLE = "cannot be compared to the committed tree without running repository-supplied commands"


class FilteredFileFidelity(unittest.TestCase):

    def _repo(self, scope="local"):
        """A checkout whose `x` filter EXPANDS stored content: the committed blob is `hello`, the
        working tree holds `EXPANDED-hello`, and the index stat cache is current and not racy.
        `scope` is where the driver is declared: the repo's own config, or a global file."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        clean = p.dir / "clean.sh"
        clean.write_text("#!/bin/sh\necho clean >> " + _sh(p.marker) + "\nexec sed -e 's/^EXPANDED-//'\n",
                         encoding="utf-8")
        clean.chmod(0o755)
        driver = {"filter.x.clean": str(clean), "filter.x.smudge": "sed -e 's/^/EXPANDED-/'"}
        env = dict(_CLEAN_ENV)
        if scope == "global":
            glob = p.dir / "global.gitconfig"
            glob.write_text("[filter \"x\"]\n" + "".join(
                f"\t{k.split('.')[-1]} = {v}\n" for k, v in driver.items()), encoding="utf-8")
            env["GIT_CONFIG_GLOBAL"] = str(glob)
        else:
            for key, value in driver.items():
                p._git("config", key, value)
        self.env = env

        def git(*a):
            return subprocess.run(["git", "-C", str(p.repo), *a], env=env, check=True,
                                  capture_output=True, text=True, stdin=subprocess.DEVNULL)
        (p.repo / ".git" / "info").mkdir(parents=True, exist_ok=True)
        (p.repo / ".git" / "info" / "attributes").write_text("*.txt filter=x\n", encoding="utf-8")
        (p.repo / "f.txt").write_text("hello\n", encoding="utf-8")
        git("add", "f.txt")
        git("commit", "-qm", "filtered")
        (p.repo / "f.txt").unlink()
        git("checkout", "--", "f.txt")
        self.assertEqual((p.repo / "f.txt").read_text(), "EXPANDED-hello\n", "fixture: smudge did not run")
        past = time.time() - 120
        os.utime(p.repo / "f.txt", (past, past))
        git("update-index", "--refresh")
        self.head_tree = git("rev-parse", "HEAD^{tree}").stdout.strip()
        p.fired()
        return p

    def _touch(self, p):
        later = time.time() - 60
        os.utime(p.repo / "f.txt", (later, later))

    def _fingerprint(self, p):
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": self.env["GIT_CONFIG_GLOBAL"]}):
            return evidence_run.working_tree_fingerprint(str(p.repo))

    def test_an_untouched_filtered_file_still_fingerprints_as_head(self):
        p = self._repo()
        out, err = self._fingerprint(p)
        self.assertIsNone(err, err)
        self.assertEqual(out, self.head_tree)
        self.assertEqual(p.fired(), set())

    def test_a_touched_filtered_file_is_unverifiable_not_stale(self):
        p = self._repo()
        self._touch(p)
        out, err = self._fingerprint(p)
        self.assertIsNone(out, "a fingerprint was produced for content it cannot compare")
        self.assertIn(_UNVERIFIABLE, err)
        self.assertIn("f.txt", err)
        self.assertIsInstance(err, evidence_run.WtreeUnverifiable)
        self.assertEqual(p.fired(), set(), "the repo-declared filter ran to make the comparison")
        r = subprocess.run(["sh", str(SCRIPTS / "wtree.sh"), str(p.repo)], env=self.env,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(r.stdout, "")

    def test_mutation_control_with_the_blanks_stripped_the_filter_runs(self):
        # The trade-off, measured: let the repo's filter run and it maps the bytes back to HEAD —
        # which is exactly the repository-supplied command the coordinator must not execute.
        p = self._repo()
        self._touch(p)
        src = (SCRIPTS / "wtree.sh").read_text(encoding="utf-8")
        self.assertEqual(src.count("GIT_CONFIG_COUNT=$_n"), 1)
        mutant = p.dir / "wtree_control.sh"
        mutant.write_text(src.replace("GIT_CONFIG_COUNT=$_n", "GIT_CONFIG_COUNT=0"), encoding="utf-8")
        r = subprocess.run(["sh", str(mutant), str(p.repo)], env=self.env, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL, timeout=120)
        self.assertIn("clean", p.fired(), "control: the stripped wtree.sh must run the filter")
        self.assertEqual(r.stdout.strip(), self.head_tree)

    def test_a_filter_from_the_coordinators_own_global_config_keeps_fidelity(self):
        p = self._repo(scope="global")
        self._touch(p)
        out, err = self._fingerprint(p)
        self.assertIsNone(err, err)
        self.assertEqual(out, self.head_tree)
        self.assertIn("clean", p.fired(), "the global (coordinator-supplied) filter should run")

    def test_a_repo_key_shadowing_a_global_driver_is_still_blanked(self):
        p = self._repo(scope="global")
        p._git("config", "filter.x.process", "")  # a repo-scope key naming the same driver
        self._touch(p)
        out, err = self._fingerprint(p)
        self.assertIsNone(out)
        self.assertIn(_UNVERIFIABLE, err)
        self.assertEqual(p.fired(), set())

    def test_evidence_run_and_verify_report_unverifiable_not_stale(self):
        p = self._repo()
        self._touch(p)
        runner = SCRIPTS / "evidence-run.py"
        r = subprocess.run([sys.executable, str(runner), "--label", "t", "--manifest", "m.json",
                            "--", sys.executable, "-c", "pass"], cwd=p.repo, env=self.env,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(_UNVERIFIABLE, r.stderr)
        self.assertNotIn("STALE", r.stderr)
        manifest = json.loads((p.repo / "m.json").read_text(encoding="utf-8"))
        rec = manifest["commands"][0]
        self.assertIsNone(rec["wtree"])
        self.assertIn(_UNVERIFIABLE, rec["wtree_unverifiable"])
        verify = _load("verify_unverifiable", "verify.py")
        verify._Authority.reset()
        self.addCleanup(verify._Authority.reset)
        head = subprocess.run(["git", "-C", str(p.repo), "rev-parse", "HEAD"], env=self.env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
        with mock.patch.dict(verify._ROOTS, {"git": str(p.repo)}):
            errs = verify.check_commands({"head_sha": head, "commands": [rec]}, True)
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("UNVERIFIABLE", errs[0])
        self.assertIn(_UNVERIFIABLE, errs[0])
        self.assertNotIn("STALE", errs[0])


# PR #649 review (PRRT_kwDOTWxN9c6vxaeq): an `includeIf` makes the effective config depend on WHERE
# and in WHAT ref state git runs — `gitdir:` (a linked worktree's own git dir), `onbranch:` (the
# checked-out branch), `hasconfig:remote.*.url:` (another key's value). The rule is to read the
# drivers in the same directory and ref state as the git call that could run them. verify.py's
# control worktree broke it (test_verify ConditionalIncludeFilterNeverRunsInTheControl); these pin
# that every other gate holds it when it runs in a worker's LINKED worktree.
_CONDITIONS = (
    ("gitdir", "includeIf.gitdir:**/worktrees/**.path"),
    ("onbranch", "includeIf.onbranch:work.path"),
    ("hasconfig", "includeIf.hasconfig:remote.*.url:https://example.invalid/**.path"),
)


class ConditionalIncludesAreReadWhereGitRuns(unittest.TestCase):

    def _linked(self, condition, key):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        base = p.commit("a.txt", "line1\nline2\n")
        include = p.dir / f"{condition}.gitconfig"
        include.write_text(f'[filter "{condition}"]\n\tclean = {p.probe} clean\n'
                           f'\tsmudge = {p.probe} smudge\n', encoding="utf-8")
        p._git("remote", "add", "origin", "https://example.invalid/r.git")
        p._git("config", key, str(include))
        linked = p.dir / "linked"
        r = p._git("worktree", "add", "-q", "-b", "work", str(linked), base)
        self.assertEqual(r.returncode, 0, r.stderr)
        info = p.repo / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "attributes").write_text(f"*.txt filter={condition}\n", encoding="utf-8")
        (linked / "a.txt").write_text("line1\nCHANGED\n", encoding="utf-8")
        p.fired()
        # Positive control: plain git in the linked worktree runs the conditionally loaded filter.
        p._git("diff", "--no-ext-diff", "--no-textconv", "HEAD", "--", cwd=linked)
        self.assertIn("clean", p.fired(), f"the {condition}: include is not live in the worktree")
        return p, linked, base

    def test_every_gate_in_a_linked_worktree_blanks_a_conditionally_included_filter(self):
        for condition, key in _CONDITIONS:
            with self.subTest(condition=condition):
                p, linked, base = self._linked(condition, key)
                floor_guard.collect_diff(linked, floor_guard.merge_base(linked, base))
                self.assertEqual(p.fired(), set(), f"floor_guard ran the {condition}: filter")
                diff_scope.scope(linked, base)
                self.assertEqual(p.fired(), set(), f"diff_scope ran the {condition}: filter")
                out, err = evidence_run.working_tree_fingerprint(str(linked))
                self.assertEqual(p.fired(), set(), f"wtree.sh ran the {condition}: filter")
                self.assertIsInstance(err, evidence_run.WtreeUnverifiable)

    def test_the_enumeration_in_the_linked_worktree_sees_what_the_source_does_not(self):
        p, linked, _ = self._linked("gitdir", _CONDITIONS[0][1])
        self.assertFalse([k for k, _ in gitexec.driver_blanks(p.repo) if k.startswith("filter.gitdir.")])
        self.assertTrue([k for k, _ in gitexec.driver_blanks(linked) if k.startswith("filter.gitdir.")])


# PR #649 review (merge-driver class): a `merge.<driver>.driver`, selected by a `merge=<driver>`
# attribute, is a command git runs when it 3-way-merges a path — on the read side through
# `git merge-tree` (diff_scope.predict_merge, and wtree.sh predict-merge, which execs it). It is
# neutralised by overriding `merge.<driver>.driver` to `exit 1` (a shell builtin that runs nothing
# and fails the merge closed). A linear in-order range revert is trivial at every step, so verify's
# revert leg cannot reach a merge driver; it carries the override defensively all the same.
class MergeDriverNeutralised(unittest.TestCase):

    def _repo(self, recursive=False):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        # The probe RESOLVES the merge (writes a result and exits 0), so a merge that runs it looks
        # clean; neutralised, the same merge is a genuine textual conflict. That difference is how a
        # fired driver is told from a blanked one, independent of the marker.
        p.probe.write_text("#!/bin/sh\necho merge >> " + _sh(p.marker) + "\n"
                           ": > \"$2\"\nexit 0\n", encoding="utf-8")
        p.probe.chmod(0o755)
        p.commit("shared.txt", "base\n")
        p._git("checkout", "-q", "-b", "side")
        (p.repo / "shared.txt").write_text("side\n", encoding="utf-8")
        p._git("commit", "-qam", "side")
        p._git("checkout", "-q", "main" if p._git("rev-parse", "--verify", "-q", "main").returncode == 0 else "master")
        (p.repo / "shared.txt").write_text("mainline\n", encoding="utf-8")
        p._git("commit", "-qam", "main")
        self.main = "main" if p._git("rev-parse", "--verify", "-q", "main").returncode == 0 else "master"
        p._git("config", "merge.m.driver", f"{p.probe} %O %A %B")
        if recursive:
            p._git("config", "merge.m.recursive", "m2")
            p._git("config", "merge.m2.driver", f"{p.probe} rec %O %A %B")
        (p.repo / ".git" / "info" / "attributes").write_text("shared.txt merge=m\n", encoding="utf-8")
        p.fired()
        # Positive control: plain merge-tree runs the driver, which resolves (exit 0) — so a GREEN
        # below both suppresses the marker AND flips the verdict back to a real conflict.
        clean = p._git("merge-tree", "--write-tree", self.main, "side")
        self.assertEqual(clean.returncode, 0, "fixture: the merge driver did not resolve on bare git")
        self.assertIn("merge", p.fired())
        return p

    def test_predict_merge_runs_no_merge_driver(self):
        p = self._repo()
        # predict_merge returns (clean, conflicts, ...): neutralised, the divergent merge that the
        # driver would have resolved is left as a real conflict — the fail-closed direction.
        result = diff_scope.predict_merge(p.repo, self.main, "side")
        self.assertEqual(p.fired(), set(), "diff_scope.predict_merge ran the merge driver")
        self.assertFalse(result["clean"], "neutralised, the divergent merge must read as a conflict")
        self.assertIn("shared.txt", result["conflicts"])

    def test_mutation_control_without_the_blanks_the_merge_driver_runs(self):
        p = self._repo()
        with mock.patch.object(diff_scope, "_driver_blanks", lambda repo: []):
            diff_scope.predict_merge(p.repo, self.main, "side")
        self.assertIn("merge", p.fired(),
                      "control: with the blanks removed the merge driver must run")

    def test_the_recursive_inner_driver_is_neutralised_too(self):
        p = self._repo(recursive=True)
        pairs = dict(gitexec.driver_blanks(p.repo))
        self.assertEqual(pairs.get("merge.m.driver"), "exit 1")
        self.assertEqual(pairs.get("merge.m2.driver"), "exit 1", "the recursive inner driver is not neutralised")

    def test_wtree_predict_merge_entry_runs_no_merge_driver(self):
        # `wtree.sh predict-merge` execs diff_scope.py --predict-merge; cover that entry point too.
        p = self._repo()
        r = subprocess.run(["sh", str(SCRIPTS / "wtree.sh"), str(p.repo), "predict-merge",
                            self.main, "side"], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(p.fired(), set(), "wtree.sh predict-merge ran the merge driver")
        self.assertEqual(r.returncode, 1, "a divergent merge must predict a conflict (exit 1)")


# PR #649 review (PRRT_kwDOTWxN9c6vzAIE): an empty blank list must mean "no driver declared",
# never "could not tell". A config query that errors, times out, or prints output that cannot be
# parsed used to return [] and let the gate run its content-reading git command with every planted
# driver live. Each copy now stops the gate in its own vocabulary. git itself answers an EMPTY but
# valid config with exit 0 and no output (pinned below), so exit 0 + nothing matching proceeds,
# and anything else stops.
_REAL_GIT = shutil.which("git")


def _fake_git(dirpath, mode):
    """A `git` that misbehaves ONLY for `config --list` — `fail` exits 128, `garbage` exits 0
    with output no NUL terminates — and delegates every other call to the real git, so the gate's
    content-reading command still runs (and would run any planted driver)."""
    action = {"fail": 'echo "fatal: forced config failure" >&2; exit 128',
              "garbage": "printf 'filter.x.clean'; exit 0"}[mode]
    script = Path(dirpath) / "git"
    script.write_text('#!/bin/sh\ncase " $* " in\n  *" config --list "*) ' + action + " ;;\nesac\n"
                      "exec " + _sh(_REAL_GIT) + ' "$@"\n', encoding="utf-8")
    script.chmod(0o755)
    return script


class DriverQueryFailsClosed(unittest.TestCase):

    def _repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        base = p.commit("a.txt", "line1\nline2\n")
        p.arm_filter()
        (p.repo / "a.txt").write_text("line1\nCHANGED\n", encoding="utf-8")
        return p, base

    def test_git_answers_an_empty_valid_config_with_exit_0_and_no_output(self):
        # The contract the copies lean on: NOT exit 1 (that is `git config --get`'s "missing").
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        subprocess.run(["git", "init", "-q", str(tmp / "r")], env=_CLEAN_ENV, check=True,
                       stdin=subprocess.DEVNULL)
        (tmp / "r" / ".git" / "config").write_text("", encoding="utf-8")
        env = {k: v for k, v in _CLEAN_ENV.items() if not k.startswith("GIT_CONFIG_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        r = subprocess.run(["git", "-C", str(tmp / "r"), "config", "--list", "-z", "--name-only"],
                           env=env, capture_output=True, stdin=subprocess.DEVNULL)
        self.assertEqual((r.returncode, r.stdout), (0, b""))

    def test_none_declared_proceeds_in_every_copy(self):
        verify = _load("verify_failclosed_none", "verify.py")
        verify._Authority.reset()
        self.addCleanup(verify._Authority.reset)
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        p.commit("a.txt", "one\n")
        self.assertEqual(gitexec.driver_blanks(p.repo), [])
        self.assertEqual(diff_scope._driver_blanks(p.repo), [])
        self.assertEqual(verify._Authority.driver_blanks(p.repo), [])

    def test_every_copy_refuses_a_failed_or_unparseable_query(self):
        # The parity of the fail-closed contract: same failure, each copy refuses in its own terms.
        verify = _load("verify_failclosed", "verify.py")
        verify._Authority.reset()
        self.addCleanup(verify._Authority.reset)
        p, _ = self._repo()
        for mode in ("fail", "garbage"):
            with self.subTest(mode=mode):
                fake = str(_fake_git(p.dir, mode))
                with mock.patch.object(gitexec, "GIT", fake):
                    with self.assertRaises(gitexec.DriverQueryFailed):
                        gitexec.driver_blanks(p.repo)
                with mock.patch.object(diff_scope, "GIT", fake):
                    with self.assertRaises(diff_scope.ScopeError) as cm:
                        diff_scope._driver_blanks(p.repo)
                    self.assertEqual(cm.exception.kind, "diff_failed")
                with mock.patch.object(verify._Authority, "git", fake):
                    with self.assertRaises(verify._Authority.DriverQueryFailed):
                        verify._Authority.driver_blanks(p.repo)

    def test_a_timed_out_query_refuses(self):
        p, _ = self._repo()
        real_run = subprocess.run

        def slow(argv, *a, **kw):
            if "config" in argv and "--list" in argv:
                raise subprocess.TimeoutExpired(argv, kw.get("timeout", 30))
            return real_run(argv, *a, **kw)
        with mock.patch.object(gitexec.subprocess, "run", side_effect=slow):
            with self.assertRaises(gitexec.DriverQueryFailed):
                gitexec.driver_blanks(p.repo)
        with mock.patch.object(diff_scope.subprocess, "run", side_effect=slow):
            with self.assertRaises(diff_scope.ScopeError):
                diff_scope._driver_blanks(p.repo)

    def test_floor_guard_stops_and_runs_no_filter(self):
        for mode in ("fail", "garbage"):
            with self.subTest(mode=mode):
                p, base = self._repo()
                mb = floor_guard.merge_base(p.repo, base)
                # floor_guard loads its OWN gitexec (_sibling), so patch that module's GIT.
                with mock.patch.object(floor_guard.gitexec, "GIT", str(_fake_git(p.dir, mode))):
                    with self.assertRaises(floor_guard.GuardError) as cm:
                        floor_guard.collect_diff(p.repo, mb)
                self.assertIn("driver config", str(cm.exception))
                self.assertEqual(p.fired(), set(), "floor_guard ran a filter with no blanks")

    def test_diff_scope_stops_and_runs_no_filter(self):
        for mode in ("fail", "garbage"):
            with self.subTest(mode=mode):
                p, base = self._repo()
                with mock.patch.object(diff_scope, "GIT", str(_fake_git(p.dir, mode))):
                    with self.assertRaises(diff_scope.ScopeError) as cm:
                        diff_scope.changed_files(p.repo, base)
                self.assertEqual(cm.exception.kind, "diff_failed")
                self.assertEqual(p.fired(), set(), "diff_scope ran a filter with no blanks")

    def test_wtree_stops_with_no_fingerprint_and_runs_no_filter(self):
        for mode in ("fail", "garbage"):
            with self.subTest(mode=mode):
                p, _ = self._repo()
                bindir = p.dir / f"bin-{mode}"
                bindir.mkdir()
                _fake_git(bindir, mode)
                path = str(bindir) + os.pathsep + os.environ["PATH"]
                with mock.patch.dict(os.environ, {"PATH": path}):
                    out, err = evidence_run.working_tree_fingerprint(str(p.repo))
                self.assertIsNone(out)
                self.assertNotIsInstance(err, evidence_run.WtreeUnverifiable)
                self.assertIn("config", err)
                self.assertEqual(p.fired(), set(), "wtree.sh ran a filter with no blanks")


if __name__ == "__main__":
    unittest.main()
