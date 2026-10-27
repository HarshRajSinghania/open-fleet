#!/usr/bin/env python3
"""Build self-contained missions for installers that copy skill directories.

The three-layer separation is why the catalog works: a mission references its
playbooks and runtime policies by BARE NAME, and they live two directories up.
A symlink install preserves that. A plugin install copies the whole repo, so it
preserves it too. An installer that copies `skills/<name>/` *out* of the tree
severs every one of those references, and the mission then runs half-blind with
nothing saying so (docs/reviews/2026-09-10-review.md §8 P2-18).

This makes a distribution tree where each mission carries its own copies:

    dist/skills/<name>/SKILL.md
    dist/skills/<name>/references/<protocol>.md      one per composed/ridden doc
    dist/skills/<name>/references/ARCHITECTURE.md    root docs it links
    dist/skills/<name>/runtime/scripts/             executable runtime + helpers
    dist/skills/<name>/runtime/*.json               runtime data
    dist/skills/<name>/docs/runs/TEMPLATE.md        mandatory run-report template

Every `runtime/scripts/<file>` a vendored document names becomes
`"$OPEN_FLEET_ROOT/runtime/scripts/<file>"`, so a worker running from the project repository
can execute the documented command as written instead of substituting the root by hand.

It also rewrites the SKILL.md so nothing points outside the mission directory:
`](../../ARCHITECTURE.md)` becomes `](references/ARCHITECTURE.md)`, and one line
points at `references/README.md`, the generated index naming each protocol's local
copy. Bare names in the Composes/rides clause are left alone — they are the
mission's vocabulary, not paths — and that index is what resolves them.

`dist/` is generated, never committed: vendoring one copy of the doctrine tree per mission
into git would make every runtime edit a many-file diff and the copies would rot
between edits. Build it at release time, or before running a copy installer.

    python3 scripts/bundle.py                 # build dist/
    python3 scripts/bundle.py --out /tmp/x    # build somewhere else
    python3 scripts/bundle.py --check         # build to a temp dir and verify only

A build records every file it writes, with its sha256, in `<out>/.open-fleet-bundle.json`. That
marker sits in --out, so it only names candidates. The build also keeps a record of the same
digests OUTSIDE --out (one file per --out in `open-fleet-bundle/` under the source checkout's git
directory, or in $OPEN_FLEET_BUNDLE_RECORDS), and a listed file is the bundle's only when that
record holds its exact bytes, when its exact bytes are a blob the source repository committed at
the path the build copies it from, or when they are the bytes this build writes there anyway.
Such a file is overwritten, or deleted once no longer written; any other stale listed file is left
in place and named on stderr. A build refuses (exit 2, nothing deleted or written) when an
unlisted file, a changed listed file, a symlink or a non-file sits where it writes, when it would
overwrite a file it cannot prove its own, or when the marker lists a name no build writes, a file
without a digest, or is itself a symlink or FIFO. A `--out` built before records (or from another
checkout) therefore refuses once if anything the build changes is there: move it away and
rebuild. A mission shipping `.gitignore`, `.gitattributes`, `.gitmodules` or `.git` fails the
build (exit 1): it would change what the publish job's `git add -A` records.

Exit: 0 built and verified · 1 a reference could not be resolved · 2 could not run (or refused
an --out holding content it cannot prove a previous build wrote).
"""
import sys

# W3-01: `python3 <dir>/<script>.py` puts <dir> at sys.path[0], AHEAD of the stdlib, so a committed
# sibling named like a stdlib module (json.py, hashlib.py) would BE that module here, and no
# toolchain hash binds it. Drop that entry before any other import (`from __future__` imports too,
# which is why this file has none); `os` is read from sys.modules, loaded at start-up, never
# imported. `python3 -I` does the same from outside; this holds when a caller forgets it.
if (__name__ == "__main__" and not getattr(sys.flags, "safe_path", False) and sys.path
        and ("os" not in sys.modules or sys.modules["os"].path.realpath(sys.path[0])
             == sys.modules["os"].path.dirname(sys.modules["os"].path.realpath(__file__)))):
    del sys.path[0]

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

_spec = importlib.util.spec_from_file_location("_validate", ROOT / "scripts" / "validate.py")
validate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate)
_grammar = validate._grammar
# The hardened git (one resolution, no replace objects, no global/system config) for the
# provenance read that decides what a rebuild may delete.
_spec = importlib.util.spec_from_file_location("_bundle_gitexec", ROOT / "runtime" / "scripts" / "gitexec.py")
gitexec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gitexec)

# `](../../X.md)` and `](../../dir/X.md)` — the outbound links the rewriter knows how to vendor.
OUTBOUND_LINK_RE = re.compile(r"\]\((?:\.\./)+([A-Za-z0-9_./-]+\.md)(#[^)]*)?\)")
# Every link that leaves the directory, whatever its extension. The rewriter only vendors `.md`,
# but the CHECK has to see the rest: `](../../runtime/scripts/verify.py)` was neither rewritten nor
# flagged, so dist/ could ship a link pointing nowhere with --check green (#316).
OUTBOUND_ANY_RE = re.compile(r"\]\((?:\.\./)+([A-Za-z0-9_./-]+)(#[^)]*)?\)")
# A relative link that does NOT climb out with `../`. A vendored doc keeps the repo-root-relative
# links it was written with — `](runtime/evidence-manifest.md)` — and from `references/` those
# resolve under `references/`, where nothing was copied. They escape nothing, so OUTBOUND_ANY_RE
# never saw them, and 56 of them shipped dead while --check stayed green (PR #308 review, P1).
RELATIVE_LINK_RE = _grammar.RELATIVE_LINK_RE
REFERENCES = "references"
# A runtime path as a protocol spells it: repo-root-relative, because in the repository that is
# where it is. Beside an installed mission it is not, and the worker runs from the PROJECT
# repository, where `runtime/scripts/` is absent or belongs to someone else. The index used to ask
# for the `$OPEN_FLEET_ROOT` substitution by hand, which is a step a protocol followed literally
# never takes: the documented command looked in the project checkout while --check stayed green
# (#322 review, P1). `runtime/scripts/` with no filename is prose about the directory, not an
# invocation, so a name character after the slash is required.
_RUNTIME_REF = r"runtime/(?:scripts/[A-Za-z0-9_][A-Za-z0-9_.-]*|[A-Za-z0-9_][A-Za-z0-9_.-]*\.json)"
RUNTIME_LINK_RE = re.compile(rf"\[([^\]]*)\]\((?:\.\./)*({_RUNTIME_REF})(#[^)]*)?\)")
RUNTIME_PATH_RE = re.compile(rf"(?<![\w/$.-])({_RUNTIME_REF})")
# The installed-root variable every vendored command names. ORCA_FLEET_ROOT is its pre-rename
# spelling; a source document that still carries it is normalised in the copy, so one bundle never
# names two roots.
ROOT_VAR = "OPEN_FLEET_ROOT"
LEGACY_ROOT_VAR_RE = re.compile(r"\bORCA_FLEET_ROOT\b")
# The template states the substitution as a manual step. The bundled copy has already had it made,
# so the instruction would send a reader hunting for invocations that are no longer there.
MANUAL_SUBSTITUTION_RE = re.compile(
    r"Replace every `runtime/scripts/<file>` invocation below with\s+"
    r"`\"\$OPEN_FLEET_ROOT/runtime/scripts/<file>\"`;\s+")
MANUAL_SUBSTITUTION_NOTE = ('Runtime invocations below already name\n'
                            '`"$OPEN_FLEET_ROOT/runtime/scripts/<file>"`; ')
# The distribution's runtime interface, independent of what survived in the input tree.
# Ship additional runtime files too, but never let discovery shrink this required floor.
REQUIRED_RUNTIME = tuple(f"runtime/scripts/{name}" for name in (
    # The shared catalog grammar: proof_status.py and quarantine_check.py (preflight's quarantine
    # gate) load it beside themselves (2026-10-23 review, P1-9 / P1-10).
    "_catalog_grammar.py",
    # Process containment: first_run.py loads it beside itself, and every paid runner's marker sweep
    # and host probe live there (PR #668 review).
    "containment.py",
    "decisions.py", "deny-hook.sh", "diff_scope.py", "dispatch-sign.py", "ed25519.py",
    "egress.py", "evidence-run.py", "floor_guard.py", "guard_text.py", "hitl-loop.template.sh",
    "inventory.py", "pm.py", "preflight.py", "proof_status.py", "quarantine_check.py",
    "run_report.py", "sandbox_doctor.py", "spawn_worker.sh", "verify-gate.sh", "verify.py",
    "wtree.sh",
)) + ("runtime/one-way-doors.json", "runtime/pins.json")
# build-change's mandatory reporting input is outside the protocol directories.
SUPPORT_DOCS = ("docs/runs/TEMPLATE.md",)
# The bundle doubles as the installable lean plugin, so its manifests are build inputs too.
PLUGIN_MANIFESTS = (".claude-plugin/plugin.json", "hooks/hooks.json")
# What the directory listing reads (#235), source -> out-relative destination. The developer
# portal blocks a plugin folder with no README of at least 40 words or no license, and takes
# .claude-plugin/icon.png as the listing icon, once, at the first save. The repository README links
# into docs/, which the bundle does not ship, so the bundle carries its own; the license and the
# notices it names ship in every build, not only the published one (PR #681 review).
PLUGIN_LISTING = {".claude-plugin/bundle-README.md": "README.md", ".claude-plugin/icon.png": ".claude-plugin/icon.png",
                  "LICENSE": "LICENSE", "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md"}


def missing_inputs(protocols):
    """Check declared requirements before discovered files can define the inventory."""
    problems = [f"missing required source: {name}"
                for name in (*REQUIRED_RUNTIME, *SUPPORT_DOCS, *PLUGIN_MANIFESTS, *PLUGIN_LISTING)
                if not (ROOT / name).is_file()]
    for path in [*SKILLS_DIR.glob("*/SKILL.md"), *(ROOT / "playbooks").glob("*.md"),
                 *(ROOT / "runtime").glob("*.md")]:
        text = path.read_text(encoding="utf-8")  # never the locale's codec (2026-10-23 review)
        for name in sorted(validate.explicit_protocol_refs(text) - protocols):
            problems.append(f"{path.relative_to(ROOT)}: missing required protocol: {name}.md")
    return problems


def protocol_docs(text, protocols):
    """Resolve the protocol closure, including calls inside other protocols.

    Playbooks call each other with bare backticks outside Composes/rides clauses.
    Include conditional calls too: they may become mandatory later in a run. The closure is the
    catalog grammar's (runtime/scripts/_catalog_grammar.py), the same one the quarantine gates
    read, so what a bundle vendors and what quarantine checks are one set (2026-10-23 review,
    P2-11) — DEFERRED READS named bare ("compound-learn at VERDICT") included.
    """
    def resolve(name):
        if name not in protocols:
            return None
        for base in (ROOT / "playbooks", ROOT / "runtime"):
            doc = base / f"{name}.md"
            if doc.is_file():
                return doc
        return None

    return _grammar.protocol_closure(text, resolve, lambda doc: doc.read_text(encoding="utf-8"))


def root_docs(text):
    """{filename: source path} for every repo-root doc the SKILL.md links."""
    found = {}
    for match in OUTBOUND_LINK_RE.finditer(text):
        target = match.group(1)
        source = (ROOT / target).resolve()
        try:
            source.relative_to(ROOT)
        except ValueError:
            continue
        if source.is_file():
            found[Path(target).name] = source
    return found


def rewrite(text, mission, protocols):
    """SKILL.md with outbound links pointed at references/, plus one pointer line.

    The index itself goes in `references/README.md`, not here: the mission body is
    budget-capped (ARCHITECTURE.md "Instruction budget"), and a bundle that blew
    that cap to explain itself would be its own kind of dishonest.
    """
    def local(match):
        anchor = match.group(2) or ""
        return f"]({REFERENCES}/{Path(match.group(1)).name}{anchor})"

    out = OUTBOUND_LINK_RE.sub(local, text)
    if protocol_docs(text, protocols):
        out = out.rstrip("\n") + (
            f"\n\nBundled copy of `{mission}`: every protocol named above is vendored in "
            f"[`{REFERENCES}/`]({REFERENCES}/README.md), not two directories up.\n"
        )
    return out


def shipped_runtime(mission_dir):
    """Runtime payload paths, mission-relative, spelled as a protocol would spell them."""
    runtime = mission_dir / "runtime"
    if not runtime.is_dir():
        return set()
    return {path.relative_to(mission_dir).as_posix()
            for path in runtime.rglob("*") if path.is_file()}


def absolutize_runtime(text, shipped):
    """Point a document's runtime invocations at the installed copy.

    Rewrite only paths this bundle actually ships. An unshipped one is a reference to the
    repository, and pointing it inside the installed mission would be a claim the reader
    cannot check. A markdown link is replaced whole: `](runtime/scripts/verify.py)` resolves
    to nothing beside the copy, and a backticked absolute path is what the reader runs.
    """
    def installed(path):
        return f'"$OPEN_FLEET_ROOT/{path}"'

    def link(match):
        return f"`{installed(match.group(2))}`" if match.group(2) in shipped else match.group(0)

    def bare(match):
        return installed(match.group(1)) if match.group(1) in shipped else match.group(0)

    text = LEGACY_ROOT_VAR_RE.sub(ROOT_VAR, text)
    text = MANUAL_SUBSTITUTION_RE.sub(MANUAL_SUBSTITUTION_NOTE, text)
    return RUNTIME_PATH_RE.sub(bare, RUNTIME_LINK_RE.sub(link, text))


def unbound_runtime(mission_dir, shipped):
    """Invocations still naming a shipped runtime file by its repository path.

    The inventory check passes on a bundle whose documented commands all reach for the project
    checkout, so the paths need a check of their own or they rot back silently.
    """
    problems = []
    for path in sorted(mission_dir.rglob("*.md")):
        where = path.relative_to(mission_dir).as_posix()
        for match in RUNTIME_PATH_RE.finditer(path.read_text(encoding="utf-8")):
            if match.group(1) in shipped:
                problems.append(f"{mission_dir.name}: runtime path is not installed-relative "
                                f"({where}): {match.group(1)}")
    return problems


def reference_index(mission, names):
    """The `references/README.md` a bundled mission ships next to its copies."""
    rows = "\n".join(f"- `{name}` → [{name}.md]({name}.md)" for name in names)
    return (
        f"# `{mission}` bundled references\n\n"
        f"Generated by `scripts/bundle.py`. In the repository these live in `playbooks/` and\n"
        f"`runtime/`, two directories above the mission. An installer that copies skill\n"
        f"directories out of the tree severs that path, so the copies live here instead —\n"
        f"resolve bare protocol names throughout the mission and its protocols against this list.\n\n"
        "## Installed runtime\n\n"
        "Set `OPEN_FLEET_ROOT` to the absolute installed mission directory (the directory\n"
        "containing SKILL.md). Run commands from the PROJECT repository being worked on;\n"
        "keep manifests, contracts and other project paths relative to that repository.\n"
        "These protocols already name their runtime as\n"
        '`"$OPEN_FLEET_ROOT/runtime/scripts/<file>"`, so export that variable and run the\n'
        "commands as written; no path is left to substitute by hand. Runtime JSON lives under\n"
        '`"$OPEN_FLEET_ROOT/runtime/"`; helpers locate it relative to themselves.\n'
        "Read the mandatory `docs/runs/TEMPLATE.md` from\n"
        '`"$OPEN_FLEET_ROOT/docs/runs/TEMPLATE.md"` ([run-report template](../docs/runs/TEMPLATE.md));\n'
        "write the filled report and its evidence into the PROJECT repository.\n"
        "Follow its target-project gates and integrity inventory procedure. The separate\n"
        "catalog proof-promotion section applies only in an open-fleet catalog clone;\n"
        "recording an external run does not promote the installed mission's proof tier.\n"
        "Python 3, a POSIX shell and git are host prerequisites; live operations also\n"
        "require the external tools and permissions named by their protocols (Orca, gh, etc.).\n\n"
        "```sh\n"
        'python3 "$OPEN_FLEET_ROOT/runtime/scripts/verify.py" --help\n'
        'python3 "$OPEN_FLEET_ROOT/runtime/scripts/evidence-run.py" --help\n'
        'python3 "$OPEN_FLEET_ROOT/runtime/scripts/preflight.py" --help\n'
        "```\n\n"
        "[Payload inventory](bundle-files.json) lists every required installed file.\n\n"
        f"{rows}\n"
    )


def runtime_files():
    """Ship the runtime as one unit so lazy imports and shell helpers stay local."""
    return [path for path in sorted((ROOT / "runtime").rglob("*"))
            if path.is_file() and path.suffix in {".py", ".sh", ".json"}
            and "__pycache__" not in path.parts]


def plugin_files():
    """(source, out-relative destination) of the root files that make the bundle tree itself an
    installable lean plugin.

    The bundle doubles as the plugin distribution (announcement gate 3): pointing the
    marketplace at this tree ships skills/ + hooks + the gate runtime without the source
    repo's receipt trees. The hook commands resolve under the plugin root, so a root
    runtime/ must ride along — the same runtime_files() set the missions vendor. The
    listing's README and icon ride along too (PLUGIN_LISTING)."""
    files = [(ROOT / name, name) for name in PLUGIN_MANIFESTS]
    files += [(ROOT / source, destination) for source, destination in PLUGIN_LISTING.items()]
    files += [(path, path.relative_to(ROOT).as_posix()) for path in runtime_files()]
    return files


# --out ownership (2026-10-23 review, P2-21 / #623). build() used to rmtree <out>/.claude-plugin,
# hooks, runtime and skills whenever they were not the source's own tree, so `--out ~/.claude`
# deleted the user's own skills/ (where the README's symlink install puts missions), hooks/ and
# runtime/ with exit 0 and no prompt. A build now records every file it writes in MARKER at the
# root of --out; a rebuild deletes only files that marker lists, and never a directory tree.
# Anything else where the build would write — a file the marker does not list, a symlink, a
# symlinked parent — is a collision, and the build refuses before deleting or writing anything.
#
# The marker sits inside the tree it governs, so anything that can write there can write it
# (2026-10-27 audit, W5-10/W5-11): two forged names in its list deleted ~/.claude/settings.json
# and CLAUDE.md with exit 0, and a digest it records proves nothing either, since a forger who
# can read a file can hash it (Codex review of 82a2d00c) — not even inside a mission directory
# the build writes whole, where a forged true digest still deleted a user's note and overwrote a
# user's own skill under a mission's name (re-attack of 4b24dfde). So the marker is an index of
# CANDIDATES, never proof. A build is made in a staging directory first, so the files it writes
# are known before --out is touched, and then:
#   * a listed name no build writes (_generated), a listed file without a digest or whose bytes
#     changed since, a symlink, a symlinked parent, or an unlisted file where the build writes
#     (in a mission directory, anywhere in it) refuses the whole build, as before;
#   * a listed file is the bundle's only on authority from OUTSIDE --out: its exact bytes are
#     what this checkout's last build into the same --out recorded writing at that path (the
#     build record, RECORDS_ENV / the source checkout's git directory), or a blob the source
#     repository COMMITTED at the path the build copies it from (committed_blobs), or the bytes
#     this build writes there anyway. Such a file is overwritten, or deleted once no longer
#     written. Any other listed file refuses an overwrite, and is otherwise left in place,
#     reported, and never re-recorded; with neither a record nor git history nothing stale is
#     deleted and no file this build changes is overwritten.
# The marker is read and replaced without ever following a link.
MARKER = ".open-fleet-bundle.json"
MARKER_VERSION = 2
# The marker's pre-rename name: read when MARKER is absent and replaced by MARKER on the next
# build, so a tree an earlier build wrote keeps rebuilding (PR #633 review, P2).
LEGACY_MARKER = ".orca-fleet-bundle.json"
# Names that change what `git add -A` records from the tree they sit in: the publish job commits
# the bundle with exactly that, so one of them inside a mission silently drops files from `dist`
# while its own inventory still lists them (2026-10-27 audit, W6-04).
GIT_CONTROL = frozenset({".gitignore", ".gitattributes", ".gitmodules", ".git"})


# The build record: what this checkout's last build wrote into one --out, {path: sha256}, kept
# OUTSIDE --out so that writing there cannot vouch for anything. One JSON file per --out (named
# by the sha256 of its real path) in $OPEN_FLEET_BUNDLE_RECORDS, else in `open-fleet-bundle/`
# under the source checkout's git directory; without a checkout none is kept.
RECORDS_ENV = "OPEN_FLEET_BUNDLE_RECORDS"
RECORD_VERSION = 1
# The marker and the record are small (a few hundred KiB); a larger one is not a build's.
INDEX_LIMIT = 16 << 20


class BundleRefused(Exception):
    """--out holds content this script cannot prove a build wrote; nothing was deleted or written."""


def _generated(rel):
    """True when `rel` names a file some bundle build writes: a plugin file, a runtime file, or a
    file inside a mission directory. A marker naming anything else is not one a build wrote."""
    parts = Path(rel).parts
    if rel in set(PLUGIN_MANIFESTS) | set(PLUGIN_LISTING.values()):
        return True
    if parts[0] == "runtime" and len(parts) > 1 and Path(rel).suffix in {".py", ".sh", ".json"}:
        return True
    return parts[0] == "skills" and len(parts) > 2 and not parts[1].startswith((".", "_"))


O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)  # a FIFO opens at once, and is then refused by fstat
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
READ_FLAGS = os.O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC


def _valid_name(rel):
    """True for an out-relative file name in canonical form: relative, no empty, `.` or `..`
    component, no NUL, no trailing slash. Every listed name is held to it before anything changes."""
    if not isinstance(rel, str) or not rel or "\x00" in rel or rel.startswith("/") or rel.endswith("/"):
        return False
    try:
        rel.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return all(part not in ("", ".", "..") for part in rel.split("/"))


class _Tree:
    """--out, opened once. Every delete and write after the checks walks from this descriptor, one
    component at a time with O_DIRECTORY|O_NOFOLLOW, and acts on a name relative to its own
    directory's descriptor: nothing is re-resolved through a path, so a directory swapped for a
    symlink after the checks cannot aim an unlink or a write outside --out (2026-10-27 re-attack,
    W5-10). Such a swap refuses the rest of the build."""

    def __init__(self, out):
        self.out = out
        self.fd = os.open(out, os.O_RDONLY | O_DIRECTORY | O_CLOEXEC)

    def close(self):
        os.close(self.fd)

    def dirs(self, parts, create=False):
        """[fd of --out, fd of each directory in `parts`]; the caller closes them. None when one is
        missing and not `create`; BundleRefused when one is not a real directory."""
        fds = [os.dup(self.fd)]
        try:
            for name in parts:
                try:
                    fd = os.open(name, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=fds[-1])
                except FileNotFoundError:
                    if not create:
                        self._close(fds)
                        return None
                    os.mkdir(name, 0o777, dir_fd=fds[-1])
                    fd = os.open(name, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=fds[-1])
                fds.append(fd)
            return fds
        except OSError as err:
            self._close(fds)
            raise BundleRefused(f"--out {self.out}: {'/'.join(parts)} is no longer a plain directory ({err.strerror}); "
                                "something changed it during the build, which stopped there") from None

    @staticmethod
    def _close(fds):
        for fd in fds:
            os.close(fd)

    def read(self, rel):
        """A regular file's bytes, or None (missing, a link, a FIFO, a directory, or behind one)."""
        *parts, name = rel.split("/")
        try:
            fds = self.dirs(parts)
        except BundleRefused:
            return None
        if fds is None:
            return None
        try:
            return _read_fd(lambda: os.open(name, READ_FLAGS, dir_fd=fds[-1]))
        finally:
            self._close(fds)

    def unlink(self, rel, digest):
        """Delete `rel` only while it is still the regular file whose sha256 was checked, then the
        directories that leaves empty. True when it was deleted."""
        *parts, name = rel.split("/")
        fds = self.dirs(parts)
        if fds is None:
            return False
        try:
            data = _read_fd(lambda: os.open(name, READ_FLAGS, dir_fd=fds[-1]))
            if data is None or hashlib.sha256(data).hexdigest() != digest:
                return False
            os.unlink(name, dir_fd=fds[-1])
            for i in range(len(parts), 0, -1):  # only once empty: never a directory with content
                try:
                    os.rmdir(parts[i - 1], dir_fd=fds[i - 1])
                except OSError:
                    break
            return True
        finally:
            self._close(fds)

    def write(self, rel, data, mode, times=None):
        """Write `rel` beside itself and rename it into place: a link or a FIFO at the name is
        replaced, never followed, and a directory there refuses."""
        *parts, name = rel.split("/")
        fds = self.dirs(parts, create=True)
        tmp = f".{name}.open-fleet-{os.getpid()}-{os.urandom(4).hex()}.tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600, dir_fd=fds[-1])
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                os.fchmod(fd, mode)
                if times is not None and os.utime in os.supports_fd:
                    os.utime(fd, ns=times)
            finally:
                os.close(fd)
            try:
                os.replace(tmp, name, src_dir_fd=fds[-1], dst_dir_fd=fds[-1])
            except OSError as err:
                with contextlib.suppress(OSError):
                    os.unlink(tmp, dir_fd=fds[-1])
                raise BundleRefused(f"--out {self.out}: cannot write {rel} ({err.strerror})") from None
        finally:
            self._close(fds)


def _read_fd(opener, limit=None):
    """The bytes of the regular file `opener()` opens, or None for anything else (or nothing, or,
    with `limit`, more than `limit` bytes)."""
    try:
        fd = opener()
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        chunks, size = [], 0
        while chunk := os.read(fd, 1 << 20):
            chunks.append(chunk)
            size += len(chunk)
            if limit is not None and size > limit:
                return None
        return b"".join(chunks)
    finally:
        os.close(fd)


def _entries_under(path):
    """Every non-directory entry at or under `path`; symlinks are entries, never followed."""
    if not os.path.lexists(path):
        return []
    if path.is_symlink() or not path.is_dir():
        return [path]
    found = []
    for dirpath, dirnames, filenames in os.walk(path):
        found += [Path(dirpath) / name for name in filenames]
        found += [Path(dirpath) / name for name in dirnames if (Path(dirpath) / name).is_symlink()]
    return found


def _owned(out):
    """{out-relative file: sha256} a previous build recorded (empty when there is no marker)."""
    for marker in (out / MARKER, out / LEGACY_MARKER):
        if os.path.lexists(marker):
            break
    else:
        return {}
    try:
        # O_NONBLOCK: a FIFO at the marker opens at once and is refused below, never waited on.
        fd = os.open(marker, READ_FLAGS)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise BundleRefused(f"{marker}: the ownership marker is not a regular file")
        with os.fdopen(fd, "rb") as fh:
            raw = fh.read(INDEX_LIMIT + 1)
        if len(raw) > INDEX_LIMIT:
            raise BundleRefused(f"{marker}: the ownership marker is over {INDEX_LIMIT} bytes, larger than "
                                "any build writes — refusing to guess what a previous build wrote")
        doc = json.loads(raw.decode("utf-8"))
        files, digests = doc.get("files"), doc.get("sha256")
    except BundleRefused:
        raise
    except (OSError, UnicodeDecodeError, ValueError, AttributeError) as err:
        why = "a symlink, which is never followed" if os.path.islink(marker) else f"unreadable ({err})"
        raise BundleRefused(f"{marker}: ownership marker is {why} — refusing to guess what a previous "
                            "build wrote") from err
    # Every name is checked here, before anything is deleted or written: one a later step could not
    # even form a path from (a NUL) used to traceback after earlier unlinks (re-attack, W5-11).
    if not isinstance(files, list) or not all(_valid_name(f) for f in files):
        raise BundleRefused(f"{marker}: malformed ownership marker — refusing to guess what a "
                            "previous build wrote")
    outside = sorted(f for f in files if not _generated(f))
    if outside:
        raise BundleRefused(f"{marker}: lists {len(outside)} path(s) no bundle build writes ({', '.join(outside[:5])})"
                            " — a forged or foreign marker; bundle.py deletes nothing on its word")
    if not isinstance(digests, dict):
        digests = {}
    undigested = sorted(f for f in files if not re.fullmatch(r"[0-9a-f]{64}", str(digests.get(f, ""))))
    if undigested:
        raise BundleRefused(f"{marker}: lists {len(undigested)} file(s) with no digest of what was written "
                            f"({', '.join(undigested[:5])}) — a marker from before digests, or a forged entry; "
                            "move the previous bundle away (or choose an empty --out) and rebuild")
    return {f: digests[f] for f in files}


def _sources(rel):
    """The source paths whose committed bytes the build copies VERBATIM to out-relative `rel`
    (a mission's references may come from playbooks/, runtime/ or a root doc of that name)."""
    parts = Path(rel).parts
    listing = {destination: source for source, destination in PLUGIN_LISTING.items()}
    if rel in listing:
        return [listing[rel]]
    if rel in PLUGIN_MANIFESTS or parts[0] == "runtime":
        return [rel]
    if parts[0] != "skills" or len(parts) < 3:
        return []
    inner = parts[2:]
    if inner[0] == "runtime":
        return ["/".join(inner)]
    if inner[0] == REFERENCES and len(inner) == 2:
        return [f"playbooks/{inner[1]}", f"runtime/{inner[1]}", f":(glob)**/{inner[1]}"]
    if "/".join(inner) in SUPPORT_DOCS:
        return ["/".join(inner)]
    return [rel]  # the mission's own file, copied as committed


def _blob_ids(data):
    """`data`'s git blob id under either object format."""
    header = b"blob %d\0" % len(data)
    return {hashlib.sha1(header + data).hexdigest(), hashlib.sha256(header + data).hexdigest()}


def committed_blobs(pathspecs, repo=ROOT):
    """{blob id: {path}} for every blob the repository has committed at `pathspecs` in any
    commit of any ref, or None when that cannot be read (no git, not a checkout, git failed):
    then nothing stale is provable. One `git log --raw` for every candidate, run hardened."""
    if not pathspecs:
        return {}
    try:
        proc = subprocess.run(
            gitexec.argv("-C", str(repo), "log", "--all", "-m", "--root", "--raw", "-z", "--no-abbrev",
                         "--no-renames", "--no-ext-diff", "--no-textconv", "--format=", "--",
                         *sorted(set(pathspecs))),
            env=gitexec.env(), stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    seen, tokens = {}, proc.stdout.split(b"\0")
    for meta, path in zip(tokens, tokens[1:], strict=False):  # each `:meta` token is followed by its path
        meta = meta.strip()
        if not meta.startswith(b":"):
            continue
        name = path.decode("utf-8", "surrogateescape")
        for blob in meta.split()[2:4]:
            if blob.strip(b"0"):
                seen.setdefault(blob.decode("ascii"), set()).add(name)
    return seen


def _committed_at_source(rel, data, seen):
    """True when `data` is a blob committed at one of `rel`'s source paths."""
    sources = _sources(rel)
    globs = {s.rsplit("/", 1)[-1] for s in sources if s.startswith(":(glob)")}
    exact = {s for s in sources if not s.startswith(":(glob)")}
    for blob in _blob_ids(data):
        for path in seen.get(blob, ()):
            if path in exact or path.rsplit("/", 1)[-1] in globs:
                return True
    return False


def _read_nofollow(path):
    """A regular file's bytes, opened without following a link; None for anything else."""
    return _read_fd(lambda: os.open(path, READ_FLAGS))


def records_dir():
    """The directory holding build records, or None when there is nowhere outside --out to keep
    one: $OPEN_FLEET_BUNDLE_RECORDS, else `open-fleet-bundle/` in the source checkout's git
    (common) directory, asked of the hardened git."""
    override = os.environ.get(RECORDS_ENV)
    if override:
        return Path(override)
    try:
        proc = subprocess.run(gitexec.argv("-C", str(ROOT), "rev-parse", "--git-common-dir"), env=gitexec.env(),
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    common = proc.stdout.decode("utf-8", "surrogateescape").strip()
    if proc.returncode != 0 or not common:
        return None
    return (ROOT / common) / "open-fleet-bundle"


def _record_path(out):
    """Where the build record for --out `out` lives (None: nowhere). A records directory inside
    --out is nowhere: whatever can write --out could write the record there."""
    where = records_dir()
    if where is None:
        return None
    real = os.path.realpath(out)
    if os.path.realpath(where) == real or os.path.realpath(where).startswith(real.rstrip(os.sep) + os.sep):
        return None
    return where / f"{hashlib.sha256(os.fsencode(real)).hexdigest()}.json"


def read_record(out):
    """{out-relative file: sha256} this checkout's last build into `out` recorded writing; {} when
    there is none, or it is not a regular file, not this --out's, or malformed — then it vouches
    for nothing."""
    path = _record_path(out)
    data = None if path is None else _read_fd(lambda: os.open(path, READ_FLAGS), INDEX_LIMIT)
    if data is None:
        return {}
    try:
        doc = json.loads(data.decode("utf-8"))
        files = doc["files"]
        if doc.get("out") != os.path.realpath(out) or not isinstance(files, dict):
            return {}
    except (UnicodeDecodeError, ValueError, TypeError, KeyError, AttributeError):
        return {}
    return {rel: digest for rel, digest in files.items()
            if _valid_name(rel) and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)}


def _keep_record(out, tree, produced, stage, previous):
    """Replace `out`'s build record with every file this build wrote that holds its bytes now, plus
    any file still holding bytes the previous record vouched for (a build stopped part-way). Read
    through `tree`, written beside the record and renamed over it, never through a link. Returns
    why no record could be kept, or None."""
    path = _record_path(out)
    if path is None:
        return "no git checkout to keep it in, or its records directory is inside --out"
    files = {}
    for rel in sorted(produced | set(previous)):
        data = tree.read(rel)
        if data is None:
            continue
        digest = hashlib.sha256(data).hexdigest()
        if (rel in produced and data == (stage / rel).read_bytes()) or previous.get(rel) == digest:
            files[rel] = digest
    doc = {"generator": "scripts/bundle.py", "version": RECORD_VERSION, "out": os.path.realpath(out),
           "files": files}
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{os.urandom(4).hex()}.tmp")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        try:
            view = memoryview((json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except OSError as err:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        return f"{path}: {err.strerror}"
    return None


def _claim(out, planned, produced, stage, tree, record):
    """Decide what this build may overwrite and delete in --out, or refuse having changed
    nothing. `planned` are the out-relative paths it writes (plugin files, and mission
    directories written whole); `produced` every file it writes, already staged under `stage`;
    `tree` is --out opened; `record` the build record read from outside --out.
    Returns (stale files to delete, stale files left in place, why provenance was short)."""
    owned = _owned(out)
    foreign = []
    # A listed file is the bundle's only while its bytes are the ones the marker recorded: a file
    # changed since, or a name the marker never had a right to, is someone else's (W5-10).
    for rel, digest in owned.items():
        if os.path.lexists(out / rel):
            data = tree.read(rel)
            if data is None or hashlib.sha256(data).hexdigest() != digest:
                foreign.append(out / rel)
    # Parents are checked for every path this build DELETES as well as every path it writes: a
    # retired mission stays in the marker after leaving `planned`, and a symlink swapped in for
    # its directory would aim the unlink below at another checkout's files (PR #631 review, P1).
    for rel in sorted(set(planned) | set(owned) | produced):
        parts = Path(rel).parts
        parents = [out.joinpath(*parts[:i]) for i in range(1, len(parts))]
        foreign += [p for p in parents if p.is_symlink() or (p.exists() and not p.is_dir())]
    for rel in planned:
        foreign += [entry for entry in _entries_under(out / rel)
                    if entry.relative_to(out).as_posix() not in owned or entry.is_symlink()]
    # A directory where a file goes, even an empty one _entries_under cannot see, would take the
    # copy inside it: README.md/bundle-README.md, and no README (Codex at db5023703c).
    foreign += [out / rel for rel in produced if (out / rel).is_dir() and not (out / rel).is_symlink()]
    # The marker vouches for nothing: a listed file is the bundle's when the build record (outside
    # --out) holds its exact bytes, when this build writes those bytes there anyway, or when the
    # source repository committed them at the path the build copies from (W5-10, re-attack of
    # 4b24dfde: inside a mission directory too).
    present = {rel: tree.read(rel) for rel in owned if os.path.lexists(out / rel) and out / rel not in foreign}
    unproven = {rel: data for rel, data in present.items() if data is not None
                and record.get(rel) != hashlib.sha256(data).hexdigest()
                and not (rel in produced and data == (stage / rel).read_bytes())}
    seen = committed_blobs([s for rel in unproven for s in _sources(rel)])
    short = []
    if unproven and not record:
        short.append("no build record for this --out outside it (built before records, by another "
                     "checkout, or without one)")
    if unproven and seen is None:
        short.append("no readable git history at the source checkout")
    delete, left = [], []
    for rel in sorted(present):
        data = present[rel]
        if data is None:
            continue  # nothing regular there: nothing to delete, and the write replaces it
        if rel in unproven and not (seen and _committed_at_source(rel, data, seen)):
            if rel in produced:
                foreign.append(out / rel)  # a file the build must overwrite and cannot prove its own
            else:
                left.append(rel)
        elif rel not in produced:
            delete.append((rel, hashlib.sha256(data).hexdigest()))
    if foreign:
        shown = ", ".join(sorted({p.relative_to(out).as_posix() for p in foreign})[:5])
        hint = f" ({'; '.join(short)})" if short else ""
        raise BundleRefused(
            f"--out {out}: {len(set(foreign))} path(s) where the bundle writes or deletes are not "
            f"provably its own (not listed in {MARKER}, changed since written, not what the build "
            f"record outside --out says a build wrote there nor a committed copy of their source, or "
            f"behind a symlink){hint}: {shown} — move them away or choose an empty --out; bundle.py "
            "deletes or overwrites a file only when its exact bytes are vouched for from outside --out")
    return delete, left, short


def _install(tree, stage, produced, delete):
    """Delete the provable stale files (each only while it is still the file that was checked),
    then write the staged build into --out, all through `tree`'s directory descriptors."""
    for rel, digest in delete:
        tree.unlink(rel, digest)
    for rel in sorted(produced):
        st = os.stat(stage / rel)
        tree.write(rel, (stage / rel).read_bytes(), stat.S_IMODE(st.st_mode), (st.st_atime_ns, st.st_mtime_ns))


def _record(tree, produced):
    """Write MARKER: every file this build wrote, with the sha256 of its bytes, read back through
    `tree` (never through a link). Written beside and renamed over the old one, so a link or a
    FIFO planted at MARKER is replaced, never followed (W5-11)."""
    digests = {rel: hashlib.sha256(data).hexdigest() for rel in produced if (data := tree.read(rel)) is not None}
    doc = {"generator": "scripts/bundle.py", "version": MARKER_VERSION, "files": sorted(digests),
           "sha256": dict(sorted(digests.items()))}
    tree.write(MARKER, (json.dumps(doc, indent=2) + "\n").encode("utf-8"), 0o644)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(LEGACY_MARKER, dir_fd=tree.fd)  # migrated: MARKER now lists everything this build owns


def build(out_dir, keep_record=True):
    """Write the distribution tree. Returns (missions built, unresolved refs).

    Raises BundleRefused, having deleted and written nothing, when --out holds content the
    build cannot prove a previous build wrote (MARKER, read_record, committed_blobs). Stale
    files it cannot prove are left in place and named on stderr. `keep_record=False` (--check,
    a throwaway --out) keeps no build record.
    """
    protocols = validate.known_protocol_names()
    problems = missing_inputs(protocols)
    if problems:
        return 0, problems
    out = Path(out_dir)
    missions = [d for d in sorted(SKILLS_DIR.iterdir())
                if d.is_dir() and not d.name.startswith((".", "_")) and (d / "SKILL.md").is_file()]
    files = {destination for _source, destination in plugin_files()}
    planned = sorted(files | {f"skills/{d.name}" for d in missions})
    unkept = None
    with tempfile.TemporaryDirectory(prefix="open-fleet-bundle-") as staging:
        stage = Path(staging)
        result = _build_into(stage, missions, protocols)
        produced = {path.relative_to(stage).as_posix() for path in stage.rglob("*") if path.is_file()}
        if os.path.lexists(out) and not out.is_dir():
            raise BundleRefused(f"--out {out} is not a directory")
        out.mkdir(parents=True, exist_ok=True)
        tree = _Tree(out)   # opened before the checks: they and the writes see the same directory
        try:
            record = read_record(out)
            delete, left, short = _claim(out, planned, produced, stage, tree, record)
            try:
                _install(tree, stage, produced, delete)
            finally:
                _record(tree, produced)
                if keep_record:
                    unkept = _keep_record(out, tree, produced, stage, record)
        finally:
            tree.close()
    if left:
        why = (f"provenance short: {'; '.join(short)}" if short else
               "provenance unproven: neither what the build record outside --out says a build wrote "
               "there nor a blob the source repository committed at its source path")
        print(f"bundle: left {len(left)} stale file(s) in place ({why}): {', '.join(left[:10])}"
              f"{' …' if len(left) > 10 else ''} — remove them by hand if they are the bundle's; the "
              "marker no longer lists them", file=sys.stderr)
    if unkept:
        print(f"bundle: kept no build record ({unkept}): the next rebuild into {out} cannot prove "
              "this build's files its own, so it refuses to overwrite any it changes", file=sys.stderr)
    return result


def _build_into(out, missions, protocols):
    for source, relative in plugin_files():
        destination = out / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    skills_out = out / "skills"
    built, problems = 0, []
    for skill_dir in missions:
        skill_md = skill_dir / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        target = skills_out / skill_dir.name
        (target / REFERENCES).mkdir(parents=True, exist_ok=True)
        inventory = {"SKILL.md"}
        for extra in skill_dir.iterdir():
            if extra.name == "SKILL.md":
                continue
            inventory.update(path.relative_to(skill_dir).as_posix()
                             for path in (extra.rglob("*") if extra.is_dir() else [extra])
                             if path.is_file())
            if extra.is_dir():
                shutil.copytree(extra, target / extra.name, dirs_exist_ok=True)
            else:
                shutil.copy2(extra, target / extra.name)
        docs = protocol_docs(text, protocols)
        for name, source in docs.items():
            inventory.add(f"{REFERENCES}/{name}.md")
            shutil.copy2(source, target / REFERENCES / f"{name}.md")
        if docs:
            inventory.add(f"{REFERENCES}/README.md")
            (target / REFERENCES / "README.md").write_text(
                reference_index(skill_dir.name, sorted(docs)), encoding="utf-8"
            )
        for name, source in root_docs(text).items():
            inventory.add(f"{REFERENCES}/{name}")
            shutil.copy2(source, target / REFERENCES / name)
        for source in [*runtime_files(), *(ROOT / name for name in SUPPORT_DOCS)]:
            inventory.add(source.relative_to(ROOT).as_posix())
            destination = target / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        shipped = shipped_runtime(target)   # after the runtime copy: only what really shipped
        (target / "SKILL.md").write_text(
            absolutize_runtime(rewrite(text, skill_dir.name, protocols), shipped), encoding="utf-8")
        # Record intended copies, not what survived copying: a dropped helper must fail --check.
        (target / REFERENCES / "bundle-files.json").write_text(
            json.dumps(sorted(inventory), indent=2) + "\n", encoding="utf-8")
        relink_vendored(target)   # after every copy: it needs to know what ended up beside it
        problems.extend(dangling(target))
        problems.extend(git_controls(target))
        problems.extend(unbound_runtime(target, shipped))
        built += 1
    return built, problems


def relink_vendored(mission_dir):
    """Re-point a vendored doc's repo-root-relative links, or de-link them (PR #308 review, P1).

    The copies under `references/` are verbatim, so they still say `](runtime/evidence-manifest.md)`
    — a path that was right in the repository and resolves to nothing beside the copy. Where the
    same document was vendored too, the link becomes its bare name; where it was not, the link
    becomes plain text naming the repository path, because a dead link is worse than a sentence
    telling the reader where to look."""
    refs = mission_dir / REFERENCES
    if not refs.is_dir():
        return
    available = {path.name for path in refs.glob("*.md")}
    shipped = shipped_runtime(mission_dir)
    for path in [*sorted(refs.glob("*.md")), *(mission_dir / name for name in SUPPORT_DOCS
                                             if (mission_dir / name).is_file())]:
        text = path.read_text(encoding="utf-8")

        def fix(match, _dir=path.parent):
            label, target, anchor = match.group(1), match.group(2), match.group(3) or ""
            if (_dir / target).exists():
                return match.group(0)
            name = Path(target).name
            if _dir == refs and name in available:
                return f"[{label}]({name}{anchor})"
            if _dir != refs:
                target = (_dir / target).relative_to(mission_dir).as_posix()
            if label.strip().strip("`") in (target, name):
                return f"`{target}`"   # the label WAS the path; saying it twice helps nobody
            return f"{label} (`{target}` in the open-fleet repository)"

        # Runtime paths first: a `](runtime/scripts/verify.py)` left to `fix` would be de-linked
        # as living in the repository, when the bundle ships it right there beside the mission.
        rewritten = RELATIVE_LINK_RE.sub(fix, absolutize_runtime(text, shipped))
        if rewritten != text:
            path.write_text(rewritten, encoding="utf-8")


def git_controls(mission_dir):
    """Files in a bundled mission that would change what `git add -A` publishes from the bundle.

    The publish job commits the built tree with `git add -A`, which obeys a `.gitignore` or
    `.gitattributes` inside it and records a nested `.git` as a gitlink: one committed under
    skills/<mission>/ silently drops files from `dist` while bundle-files.json still lists them,
    and a build on disk cannot show it (2026-10-27 audit, W6-04)."""
    return [f"{mission_dir.name}: ships {path.relative_to(mission_dir).as_posix()}, which changes what "
            "`git add -A` publishes from the bundle — remove it from the mission"
            for path in sorted(mission_dir.rglob("*")) if path.name in GIT_CONTROL]


def dangling(mission_dir):
    """Links in a bundled mission that still leave its directory, or point at nothing.

    Check every markdown file, not just SKILL.md (#316), after relinking. An upward link
    within the installed mission is valid (the reporting template is outside references/);
    a missing target or escape is not. Check all extensions, including runtime scripts."""
    problems = []
    inventory = mission_dir / REFERENCES / "bundle-files.json"
    if inventory.exists():
        try:
            files = json.loads(inventory.read_text(encoding="utf-8"))
            if not isinstance(files, list) or not all(isinstance(p, str) for p in files):
                raise ValueError("expected a list of payload paths")
            for relative in files:
                path = (mission_dir / relative).resolve()
                if not path.is_relative_to(mission_dir.resolve()) or not path.is_file():
                    problems.append(f"{mission_dir.name}: missing bundle payload: {relative}")
        except (OSError, ValueError) as error:
            problems.append(f"{mission_dir.name}: invalid payload inventory: {error}")
    for path in sorted(mission_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        where = path.relative_to(mission_dir).as_posix()
        for match in OUTBOUND_ANY_RE.finditer(text):
            target = match.group(0)[2:-1].split("#", 1)[0]
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(mission_dir.resolve()) or not resolved.is_file():
                problems.append(f"{mission_dir.name}: link escapes the bundle or is missing "
                                f"({where}): {match.group(0)}")
        for match in re.finditer(rf"\]\({REFERENCES}/([A-Za-z0-9_.-]+\.md)(?:#[^)]*)?\)", text):
            if not (mission_dir / REFERENCES / match.group(1)).is_file():
                problems.append(f"{mission_dir.name}: {REFERENCES}/{match.group(1)} was not vendored")
        for match in RELATIVE_LINK_RE.finditer(text):
            if not (path.parent / match.group(2)).exists():
                problems.append(f"{mission_dir.name}: dead relative link "
                                f"({where}): {match.group(0)}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bundle.py",
        description="Vendor each mission's referenced docs so copy installers keep working.",
        epilog="exit 0 built · 1 unresolved reference · 2 could-not-run",
    )
    parser.add_argument("--out", default=str(ROOT / "dist"), help="output directory (default dist/)")
    parser.add_argument("--check", action="store_true",
                        help="build into a temp dir and verify, writing nothing durable")
    args = parser.parse_args(argv)

    if not SKILLS_DIR.is_dir():
        print(f"skills/ not found at {SKILLS_DIR}", file=sys.stderr)
        return 2

    if not args.check:
        # build() once rmtree'd <out>/skills before rebuilding; `--out .` resolved that to the
        # real catalog and deleted all 21 missions it was asked to copy (#350). It now removes only
        # what its own marker lists, but writing over the source catalog stays refused.
        if (Path(args.out) / "skills").resolve() == SKILLS_DIR.resolve():
            print(f"--out {args.out}: its skills/ IS the source catalog; refusing to delete what "
                  "this script copies from", file=sys.stderr)
            return 2

    try:
        if args.check:
            with tempfile.TemporaryDirectory() as tmp:
                built, problems = build(tmp, keep_record=False)
        else:
            built, problems = build(args.out)
    except BundleRefused as refusal:
        print(f"bundle: {refusal}", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    where = "a temp dir" if args.check else args.out
    print(f"bundle: {built} self-contained mission(s) in {where}; no reference leaves its directory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
