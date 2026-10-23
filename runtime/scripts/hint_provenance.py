#!/usr/bin/env python3
"""Provenance and currency for episodic memory hints (#605).

``search_sessions.py --episodic-hint`` retrieves prior run manifests and session hits for the
paths a task is about to touch. Fencing that text (guard_text) answers "can it forge structure?";
it never answered "is it still true HERE?". A finding goes stale after a rename, a fix, a branch
change, a changed test or dependency, or a rewritten artifact, while its text stays perfectly
clean. This module answers the second question, read-only, against the LIVE source:

* **Provenance.** Every hint names its source repo/revision (or ``unknown``), the artifact it was
  drawn from with that artifact's sha256, the path/symbol scope it was checked against, the
  producing run, and why it matched (field, candidate, query, match kind).
* **Currency.** ``CURRENT`` only when every check passed: the source revision is in the live repo
  and an ancestor of the live revision; no scoped path changed, was deleted or renamed since; no
  related test changed; the recorded artifact bytes still match; no newer record and no current
  observation contradicts it. ``STALE`` and ``SUPERSEDED`` are suppressed from a worker-facing
  (current-mode) hint; ``UNKNOWN`` is shown, labelled, and never upgraded -- absent provenance and
  changed dependencies mean unknown, not fresh.
* **Labels are computed, never read.** A manifest saying ``"currency": "CURRENT"`` or ``"status":
  "fresh"`` changes nothing: the label comes from git and the artifact bytes alone.
* **CURRENT is narrow.** It means "nothing in the checked scope changed since the source
  revision". It is not "true", it is never completion evidence (evidence-manifest.md: only a new
  independent verification is), and it never outranks the frozen task or the live source.

Memory stays advisory data: nothing here writes a file, and every git call is a read-only
subcommand (``git()`` refuses anything else) with optional locks off, so building a hint cannot
edit agent instructions, permissions, the live checkout or the run archive.

Library only: no CLI, no exit codes.
"""
import ast
import datetime
import fnmatch
import functools
import hashlib
import os
import re
import subprocess
import warnings
from pathlib import Path

import diff_scope
import gitexec

CURRENT, UNKNOWN, SUPERSEDED, STALE = "CURRENT", "UNKNOWN", "SUPERSEDED", "STALE"
# Severity order: the worst reason a record carries is its label.
SEVERITY = {CURRENT: 0, UNKNOWN: 1, SUPERSEDED: 2, STALE: 3}
SUPPRESSED = frozenset({STALE, SUPERSEDED})

# The ONLY git subcommands a hint may run. diff/ls-files run with GIT_OPTIONAL_LOCKS=0 so not even
# the index stat cache is refreshed: retrieval leaves every byte of both repositories alone.
READ_ONLY_GIT = frozenset({"rev-parse", "cat-file", "merge-base", "diff", "ls-files", "log"})

REV = re.compile(r"^[0-9a-f]{7,64}$")
GLOB_CHARS = set("*?[")
# One definition of a test path: the same rule the scope gate and the verifier use (diff_scope.py).
TEST_PATH = next(rx for name, rx in diff_scope.PATH_RULES if name == "TESTS")
# Dependency manifests and lockfiles: a change to any of them leaves a historical verdict's
# currency UNKNOWN even when the scoped source is byte-identical (MemTrace's test/dependency case).
DEPENDENCY_FILES = frozenset({
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb",
    "npm-shrinkwrap.json", "requirements.txt", "requirements-dev.txt", "constraints.txt",
    "pyproject.toml", "uv.lock", "poetry.lock", "pipfile", "pipfile.lock", "setup.py", "setup.cfg",
    "go.mod", "go.sum", "cargo.toml", "cargo.lock", "gemfile", "gemfile.lock", "composer.json",
    "composer.lock", "pom.xml", "build.gradle", "build.gradle.kts", "gradle.lockfile",
    "mix.exs", "mix.lock", "package.swift", "package.resolved", ".mise.toml", "mise.toml",
    ".tool-versions", ".python-version", ".nvmrc", ".node-version",
})
PASS_STATUSES = frozenset({"verified", "merged", "pass", "passed", "green", "done", "fixed",
                           "closed", "resolved", "shipped"})
FAIL_STATUSES = frozenset({"parked", "failed", "fail", "red", "regressed", "suspect", "blocked",
                           "wedged", "flaky", "open", "refuted"})
MATCH_KINDS = ("exact", "query-glob", "dir", "basename", "record-glob")
STRUCTURED_FIELDS = ("files_touched", "scope_allow", "oracle_scope")
SYMBOL_SPLIT = re.compile(r"::|#")
# Python source is bounded by its own parser (PR #639 review: the indentation walk misread
# decorators, then tabs, then a column-zero line inside a multiline string -- each cut a definition
# short, so a changed body stayed CURRENT). The walk below remains for other languages only.
PYTHON_SUFFIXES = (".py", ".pyi", ".pyw")
DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
AMBIGUOUS = object()  # a name defined more than once at its shallowest depth: no single block
DEF_LINE = r"^(?P<indent>[ \t]*)(?:export\s+)?(?:async\s+)?(?:def|class|function|func|fn)\s+{sym}\b"


class ProvenanceError(Exception):
    """The live source cannot be read (not a repository, unknown revision, git absent, a file
    that cannot be opened)."""


def git(repo, *args, text=True):
    """Run one READ-ONLY git subcommand in ``repo``. Anything else is refused, not attempted."""
    if not args or args[0] not in READ_ONLY_GIT:
        raise ProvenanceError(f"refused git {args[0] if args else '(none)'}: hints are read-only")
    env = gitexec.env()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(gitexec.argv("-C", str(repo), *args), env=env, capture_output=True,
                          text=text, timeout=60, check=False)


def _ok(proc):
    return proc.returncode == 0


def normalize_path(value):
    text = str(value or "").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def split_symbol(token):
    """``src/a.py::refresh`` / ``src/a.py#refresh`` -> (``src/a.py``, ``refresh``)."""
    parts = SYMBOL_SPLIT.split(normalize_path(token), maxsplit=1)
    path = parts[0]
    symbol = parts[1].strip() if len(parts) > 1 and re.fullmatch(r"[A-Za-z_][\w.]*", parts[1].strip()) else None
    return path, symbol


def is_glob(path):
    return any(ch in GLOB_CHARS for ch in path)


def match_kind(candidate, query):
    """How a record's path token matches a query path, or None. Accepts exactly the pairs
    search_sessions._path_matches accepts, and names WHICH rule matched (the selection reason)."""
    c, t = normalize_path(candidate), normalize_path(query)
    if not c or not t:
        return None
    if c == t:
        return "exact"
    if fnmatch.fnmatchcase(c, t):
        return "query-glob"
    if fnmatch.fnmatchcase(t, c):
        return "record-glob"
    if c.startswith(t.rstrip("/") + "/") or t.startswith(c.rstrip("/") + "/"):
        return "dir"
    if "/" not in c or "/" not in t:
        cb, tb = os.path.basename(c), os.path.basename(t)
        if cb and tb and "*" not in tb and "?" not in tb and cb == tb:
            return "basename"
    return None


def checked_path(candidate, query, kind):
    """The concrete path whose content decides currency for one match, or None when both
    sides are patterns (the scope cannot be resolved to bytes)."""
    c, t = normalize_path(candidate), normalize_path(query)
    concrete = [p for p in (c, t) if p and not is_glob(p)]
    if kind == "exact":
        return c
    if kind == "query-glob":
        return c if not is_glob(c) else None
    if kind == "record-glob":
        return t if not is_glob(t) else None
    if kind == "basename":
        with_dir = [p for p in concrete if "/" in p]
        return with_dir[0] if with_dir else (concrete[0] if concrete else None)
    if kind == "dir":
        return max(concrete, key=len).rstrip("/") if concrete else None
    return None


def outcome(status):
    """A record's claimed outcome class: pass / fail / None (no outcome claimed)."""
    word = str(status or "").strip().lower()
    if word in PASS_STATUSES:
        return "pass"
    if word in FAIL_STATUSES:
        return "fail"
    return None


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _epoch(stamp):
    try:
        parsed = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp()


def recorded_time(manifest, unit, run_id):
    """When the record CLAIMS it was made (newest command ts, else a date in the run name).
    Untrusted: it only orders records the live repo cannot order by ancestry/commit time."""
    stamps = []
    for holder in (manifest, unit):
        if not isinstance(holder, dict):
            continue
        for cmd in holder.get("commands") or []:
            if isinstance(cmd, dict) and _epoch(cmd.get("ts")) is not None:
                stamps.append(_epoch(cmd.get("ts")))
        for key in ("recorded_at", "ts"):
            if _epoch(holder.get(key)) is not None:
                stamps.append(_epoch(holder.get(key)))
    if stamps:
        return max(stamps)
    found = re.search(r"(\d{4}-\d{2}-\d{2})", str(run_id))
    return _epoch(found.group(1) + "T00:00:00+00:00") if found else None


LEADING = re.compile(r"[ \t]*")


def _indent(line):
    """A line's leading indentation in COLUMNS, a tab advancing to the next multiple of eight as in
    Python's tokenizer. Every indentation comparison here goes through it (PR #639 review: the def
    was measured with tabs expanded and its body in raw characters, so a tab-indented method's
    body read as shallower than its def, was cut off, and a changed body stayed CURRENT)."""
    return len(LEADING.match(line).group().expandtabs())


@functools.lru_cache(maxsize=32)
def _python_tree(text):
    """The parsed module, or None when ``text`` is not source the parser accepts. Warnings (an
    invalid escape in someone's file) are the file's business, not the hint's output."""
    if text is None:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None


def _rows(text):
    """Source rows as the parser numbers them: ``\\r\\n``, ``\\r`` and ``\\n`` end a row; a form feed
    or a Unicode line separator does not (str.splitlines() would shift every lineno after it)."""
    return re.split(r"\r\n|\r|\n", text)


def _definition_levels(scope):
    """The definitions under an ast ``scope``, one list per nesting depth: those reached through
    plain statements (if/try/with/for) first, then the ones nested inside each of those."""
    frontier = [scope]
    while frontier:
        level = []
        for owner in frontier:
            pending = list(ast.iter_child_nodes(owner))
            while pending:
                node = pending.pop()
                if isinstance(node, DEFINITIONS):
                    level.append(node)
                else:
                    pending.extend(ast.iter_child_nodes(node))
        if level:
            yield level
        frontier = level


def _python_definition(tree, symbol):
    """The ast node ``symbol`` names: each dotted part is looked up inside the previous part's node
    (``Cls.meth``, ``outer.inner``) at the shallowest depth that defines it, so ``balance`` is the
    module function, not ``Account.balance``. None when nothing defines it; AMBIGUOUS when that
    depth defines it twice (a redefinition, an if/else pair, a property setter)."""
    scope = tree
    for part in str(symbol).split("."):
        found = []
        for level in _definition_levels(scope):
            found = [node for node in level if node.name == part]
            if found:
                break
        if not found:
            return None
        if len(found) > 1:
            return AMBIGUOUS
        scope = found[0]
    return scope


def _unbounded(text, symbol):
    """True when Python text gives ``symbol`` no single block: it does not parse, or the name is
    ambiguous. Such a symbol is compared as the whole file, failing toward STALE."""
    tree = _python_tree(text)
    return tree is None or _python_definition(tree, symbol) is AMBIGUOUS


def _decorator_start(lines, i, indent):
    """Index of the first decorator line of the definition on lines[i] (i itself when none). A
    decorator is part of the definition: changing or adding one changes behavior with the body
    untouched (PR #639 review). Parsed Python answers from the definition's decorator list --
    exact through comments, left-aligned arguments and multiline strings. Other text walks up from
    the def (a heuristic): continuation lines of a multi-line decorator -- deeper-indented or a
    closing bracket -- are taken only when an ``@`` line at the def's own indentation opens them."""
    tree = _python_tree("\n".join(lines))
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, DEFINITIONS) and node.lineno == i + 1:
                return min([i] + [d.lineno - 1 for d in node.decorator_list])
    start, j = i, i - 1
    while j >= 0:
        stripped = lines[j].strip()
        depth = _indent(lines[j])
        if stripped.startswith("@") and depth == indent:
            start = j
        elif not (stripped == "" or depth > indent or stripped[0] in ")]}"):
            break
        j -= 1
    return start


def symbol_block(text, symbol):
    """The definition block of ``symbol``: its decorators through its last line; None when the
    text defines no such symbol. A qualified name (``Cls.meth``) resolves each part inside the
    previous one -- the class, then the method in it (PR #639 review: it used to search a literal
    ``def Cls.meth``). Text the Python parser accepts is bounded by it: the first decorator's row
    through ``end_lineno``, and a name it defines twice at one depth returns the whole text, so a
    comparison of it can only fail toward STALE. Any other text uses the indentation heuristic in
    _definition_block() (a def/class/function line through the next line indented no deeper)."""
    if text is None:
        return None
    tree = _python_tree(text)
    if tree is not None:
        node = _python_definition(tree, symbol)
        if node is None:
            return None
        rows = _rows(text)
        if node is AMBIGUOUS:
            return "\n".join(rows)
        start = _decorator_start(rows, node.lineno - 1, _indent(rows[node.lineno - 1]))
        return "\n".join(rows[start:node.end_lineno])
    block = text
    for part in str(symbol).split("."):
        block = _definition_block(block, part)
        if block is None:
            return None
    return block


def _definition_block(text, symbol):
    """The indentation heuristic for one unqualified name in non-Python text: the SHALLOWEST
    definition of it (first in the file among equals)."""
    if text is None or not symbol:
        return None
    lines = text.splitlines()
    pattern = re.compile(DEF_LINE.format(sym=re.escape(symbol)))
    hits = [(_indent(line), i) for i, line in enumerate(lines) if pattern.match(line)]
    if not hits:
        return None
    indent, i = min(hits)
    block = lines[_decorator_start(lines, i, indent):i + 1]
    for nxt in lines[i + 1:]:
        stripped = nxt.strip()
        if stripped and _indent(nxt) <= indent and not stripped.startswith((")", "}", "]")):
            break
        block.append(nxt)
    while block and not block[-1].strip():
        block.pop()
    return "\n".join(block)


def _inside(root, rel):
    """root/rel when it resolves inside root, else None (a record cannot name /etc/passwd)."""
    try:
        target = (Path(root) / rel).resolve()
        target.relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return None
    return target


class Archive:
    """The run archive a hint was drawn from: is the artifact still the bytes that were recorded?"""

    def __init__(self, runs_dir):
        self.runs_dir = Path(runs_dir)
        self.top = None
        if self.runs_dir.is_dir():
            try:
                proc = git(self.runs_dir, "rev-parse", "--show-toplevel")
            except (OSError, ProvenanceError):
                proc = None
            if proc is not None and _ok(proc) and proc.stdout.strip():
                self.top = Path(proc.stdout.strip())
        # Manifest evidence paths are repo-relative (evidence-manifest.md); outside git the
        # archive is laid out docs/runs/<run>/, so the repo root is two levels up.
        self.root = self.top or self.runs_dir.resolve().parent.parent

    def history_reasons(self):
        """[(UNKNOWN, "artifact-unversioned")] for an archive outside git: with no committed bytes
        to compare against, a copied or edited manifest cannot be told from the recorded one, so
        its revision and scope prove nothing (PR #639 review: it came out CURRENT). The same rule
        as an untracked manifest inside git."""
        return [] if self.top is not None else [(UNKNOWN, "artifact-unversioned")]

    def artifact_reasons(self, manifest_path, records):
        """[(label, reason)] for the artifact's own integrity: a tracked manifest edited since its
        commit, or an evidence file whose bytes no longer hash to the recorded sha256 (or cannot
        be read at all: unknown, not fatal)."""
        reasons = []
        if self.top is not None:
            rel = os.path.relpath(Path(manifest_path).resolve(), self.top.resolve())
            tracked = git(self.top, "ls-files", "--error-unmatch", "--", rel)
            if not _ok(tracked):
                reasons.append((UNKNOWN, "artifact-untracked"))
            else:
                changed = git(self.top, "diff", "--no-ext-diff", "--name-only", "HEAD", "--", rel)
                if _ok(changed) and changed.stdout.strip():
                    reasons.append((STALE, "artifact-modified:manifest"))
        seen = set()
        for record in records:
            for item in (record.get("artifacts") or []) if isinstance(record, dict) else []:
                if not isinstance(item, dict) or not isinstance(item.get("sha256"), str):
                    continue
                rel = normalize_path(item.get("path"))
                if not rel or rel in seen:
                    continue
                seen.add(rel)
                target = _inside(self.root, rel)
                try:
                    present = target is not None and target.is_file()
                    digest = sha256_file(target) if present else None
                except OSError:
                    # Unknown for THIS hint only (PR #639 review: the OSError escaped every handler
                    # and one unreadable evidence file aborted the whole hint command).
                    reasons.append((UNKNOWN, f"artifact-unreadable:{os.path.basename(rel)}"))
                    continue
                if not present:
                    reasons.append((UNKNOWN, f"artifact-missing:{os.path.basename(rel)}"))
                elif digest != item["sha256"].removeprefix("sha256:").lower():
                    reasons.append((STALE, f"artifact-modified:{os.path.basename(rel)}"))
        return reasons


class LiveSource:
    """The checkout the current task runs against. ``rev=None`` reads the WORKING TREE (what the
    worker will see, uncommitted edits included) with HEAD for ancestry; a rev pins a commit."""

    def __init__(self, repo, rev=None):
        try:
            top = git(repo, "rev-parse", "--show-toplevel")
        except OSError as exc:
            raise ProvenanceError(f"live source {repo}: {exc}") from exc
        if not _ok(top) or not top.stdout.strip():
            raise ProvenanceError(f"live source {repo} is not a git checkout")
        self.root = Path(top.stdout.strip())
        self.worktree = rev is None
        head = git(self.root, "rev-parse", "--verify", f"{rev or 'HEAD'}^{{commit}}")
        if not _ok(head):
            raise ProvenanceError(f"live source {repo}: cannot resolve {rev or 'HEAD'}")
        self.rev = head.stdout.strip()
        self._cache = {}

    def label(self):
        return f"repo={self.root.name} rev={self.rev[:12]}{'+worktree' if self.worktree else ''}"

    def _memo(self, key, compute):
        if key not in self._cache:
            self._cache[key] = compute()
        return self._cache[key]

    def has_commit(self, rev):
        return self._memo(("has", rev), lambda: _ok(git(self.root, "cat-file", "-e", f"{rev}^{{commit}}")))

    def is_ancestor(self, rev):
        return self._memo(("anc", rev), lambda: _ok(git(self.root, "merge-base", "--is-ancestor", rev, self.rev)))

    def descends_from_live(self, rev):
        return self._memo(("desc", rev), lambda: _ok(git(self.root, "merge-base", "--is-ancestor", self.rev, rev)))

    def commit_time(self, rev):
        def compute():
            proc = git(self.root, "log", "-1", "--format=%ct", rev, "--")
            return float(proc.stdout.strip()) if _ok(proc) and proc.stdout.strip().isdigit() else None
        return self._memo(("time", rev), compute)

    def exists_at(self, rev, path):
        return self._memo(("exists", rev, path), lambda: _ok(git(self.root, "cat-file", "-e", f"{rev}:{path}")))

    def text_at(self, rev, path):
        proc = git(self.root, "cat-file", "-p", f"{rev}:{path}", text=False)
        return proc.stdout.decode("utf-8", "replace") if _ok(proc) else None

    def live_text(self, path):
        if not self.worktree:
            return self.text_at(self.rev, path)
        target = _inside(self.root, path)
        try:
            if target is None or not target.is_file():
                return None
            return target.read_bytes().decode("utf-8", "replace")
        except OSError as exc:
            # An unreadable live file is unknown for the hints scoped to it, not fatal to the rest.
            raise ProvenanceError(f"cannot read {path} in the live source") from exc

    def changes_since(self, rev):
        """{path: (status, new_path)} from source rev to the live tree/rev, renames detected:
        a renamed path maps to ("R", its new name). In working-tree mode an UNTRACKED file is a
        change too (git diff never lists one): a new test or dependency file is part of what the
        worker will run against (PR #639 review)."""
        def compute():
            args = ["diff", "--no-ext-diff", "--no-textconv", "--name-status", "-M", "-z", rev]
            if not self.worktree:
                args.append(self.rev)
            proc = git(self.root, *args, "--")
            if not _ok(proc):
                raise ProvenanceError(f"cannot diff {rev[:12]} against the live source")
            fields = proc.stdout.split("\0")
            out, i = {}, 0
            while i < len(fields) and fields[i]:
                status = fields[i][0]
                if status in "RC":
                    old, new = fields[i + 1], fields[i + 2]
                    if status == "R":
                        out[old] = ("R", new)
                    out.setdefault(new, ("A", None))
                    i += 3
                else:
                    out[fields[i + 1]] = (status, None)
                    i += 2
            if self.worktree:
                extra = git(self.root, "ls-files", "--others", "--exclude-standard", "-z")
                if not _ok(extra):
                    raise ProvenanceError("cannot list untracked files in the live source")
                for path in filter(None, extra.stdout.split("\0")):
                    # Removed from the index yet present on disk: changed, not deleted.
                    out[path] = ("M", None) if out.get(path, ("A",))[0] == "D" else out.get(path, ("A", None))
            return out
        return self._memo(("diff", rev), compute)


def _changed_under(changes, path):
    """The change entry for path, or for anything under it when it names a directory."""
    if path in changes:
        return changes[path]
    prefix = path.rstrip("/") + "/"
    if any(changed.startswith(prefix) for changed in changes):
        return ("M", None)
    return None


def _scope_reasons(live, rev, paths, symbols):
    reasons = []
    changes = live.changes_since(rev)
    for path in paths:
        if not live.exists_at(rev, path):
            reasons.append((UNKNOWN, f"scope-not-at-source:{path}"))
            continue
        entry = _changed_under(changes, path)
        if entry is None:
            continue
        status, new = entry
        if status == "R":
            reasons.append((STALE, f"path-renamed:{path}->{new}"))
        elif status == "D":
            reasons.append((STALE, f"path-deleted:{path}"))
        elif symbols.get(path):
            reasons.extend(_symbol_reasons(live, rev, path, symbols[path]))
        else:
            reasons.append((STALE, f"path-changed:{path}"))
    return reasons


def _symbol_reasons(live, rev, path, names):
    """A changed file keeps a symbol-scoped hint CURRENT only while every named symbol's own
    definition block is byte-identical; a vanished symbol is a rename or deletion. A Python file
    that does not parse, or that defines the name twice, on either side has no trustworthy block:
    the whole file is compared instead (PR #639 review)."""
    reasons = []
    then, now = live.text_at(rev, path), live.live_text(path)
    python = path.lower().endswith(PYTHON_SUFFIXES)
    for name in sorted(names):
        if python and (_unbounded(then, name) or _unbounded(now, name)):
            whole = (STALE, f"path-changed:{path}")
            if then != now and whole not in reasons:
                reasons.append(whole)
            continue
        before, after = symbol_block(then, name), symbol_block(now, name)
        if before is None:
            reasons.append((STALE, f"path-changed:{path}"))
        elif after is None:
            reasons.append((STALE, f"symbol-gone:{path}::{name}"))
        elif before != after:
            reasons.append((STALE, f"symbol-changed:{path}::{name}"))
    return reasons


def _related_test_reasons(changes, paths, record_tokens):
    """Tests the record named, or tests sharing a scoped file's stem, that changed since."""
    named = {normalize_path(t) for t in record_tokens if TEST_PATH.search(normalize_path(t))}
    stems = {os.path.splitext(os.path.basename(p))[0].lower() for p in paths}
    stems = {s for s in stems if len(s) >= 3}
    hits = []
    for changed in sorted(changes):
        if changed in paths or not TEST_PATH.search(changed):
            continue
        base = os.path.basename(changed).lower()
        if changed in named or any(stem in base for stem in stems):
            hits.append(changed)
    return [(STALE, f"tests-changed:{hits[0]}" + (f"+{len(hits) - 1}" if len(hits) > 1 else ""))] if hits else []


def _dependency_reasons(changes):
    hits = sorted(p for p in changes if os.path.basename(p).lower() in DEPENDENCY_FILES)
    return [(UNKNOWN, f"dependencies-changed:{hits[0]}" + (f"+{len(hits) - 1}" if len(hits) > 1 else ""))] if hits else []


def assess(hint, live, archive=None):
    """Attach provenance-derived reasons to one prior-run hint (dict built by search_sessions).

    Reads hint["rev"], ["paths"], ["symbols"], ["tokens"], ["manifest_path"], ["records"];
    returns the list of (label, reason). Supersession needs every hint: see supersede()."""
    reasons = []
    rev = hint.get("rev")
    if rev is None:
        reasons.append((UNKNOWN, "revision-malformed" if hint.get("rev_raw") else "no-revision"))
    if archive is not None and hint.get("manifest_path"):
        reasons.extend(archive.history_reasons())
        reasons.extend(archive.artifact_reasons(hint["manifest_path"], hint.get("records") or []))
    if live is None:
        reasons.append((UNKNOWN, "no-live-source"))
        return reasons
    if rev is None:
        return reasons
    if not live.has_commit(rev):
        reasons.append((UNKNOWN, "revision-not-in-live-repo"))
        return reasons
    if not live.is_ancestor(rev):
        reasons.append((STALE, "ahead-of-live" if live.descends_from_live(rev) else "divergent-branch"))
        return reasons
    paths = hint.get("paths") or []
    if not paths:
        reasons.append((UNKNOWN, "scope-unresolved"))
    else:
        reasons.extend(_scope_reasons(live, rev, paths, hint.get("symbols") or {}))
    changes = live.changes_since(rev)
    reasons.extend(_related_test_reasons(changes, set(paths), hint.get("tokens") or []))
    reasons.extend(_dependency_reasons(changes))
    return reasons


# A record whose OWN provenance failed -- no or a foreign revision, a revision off the live line of
# history, an artifact that is not what was recorded -- proves nothing about what came after a
# valid record, so it never supersedes one (PR #639 review: an ahead-of-live record used to hide
# the checkout's valid record, and current mode then showed neither).
DISQUALIFYING = ("no-revision", "revision-malformed", "revision-not-in-live-repo", "divergent-branch",
                 "ahead-of-live", "artifact-", "provenance-unreadable")


def provenance_failed(hint):
    return any(reason.startswith(DISQUALIFYING) for _label, reason in hint.get("reasons") or [])


def _newer(a, b, live):
    """True when record b is strictly newer than record a: by ancestry when the live repo knows
    both revisions, else by commit time, else by the records' own claimed time. Two runs at ONE
    revision share a commit time, so the claimed time breaks that tie (PR #639 review: a later
    run reversing an earlier verdict on unchanged code left both CURRENT)."""
    ra, rb = a.get("rev"), b.get("rev")
    if live is not None and ra and rb and ra != rb and live.has_commit(ra) and live.has_commit(rb):
        if _ok(git(live.root, "merge-base", "--is-ancestor", ra, rb)):
            return True
        if _ok(git(live.root, "merge-base", "--is-ancestor", rb, ra)):
            return False
    ta, tb = a.get("time"), b.get("time")
    if ta is not None and tb is not None and ta != tb:
        return tb > ta
    ca, cb = a.get("claimed", ta), b.get("claimed", tb)
    return ca is not None and cb is not None and cb > ca


def supersede(hints, live, observations=()):
    """Contradictory evidence (#605): a hint is SUPERSEDED when a strictly newer record of the
    same unit claims the opposite outcome, when a newer record lists it in ``supersedes``, or when
    a CURRENT observation of its scope (the frozen task's own evidence) says the opposite. Only a
    record whose own provenance held can supersede (provenance_failed). A contradicting record
    that nothing orders either way -- same revision, same or no claimed time -- leaves both
    UNKNOWN: neither verdict is known to hold. Mutates each hint's ``reasons``; a contradiction
    only ever demotes, never promotes."""
    for old in hints:
        unordered = None
        for new in hints:
            if new is old or provenance_failed(new):
                continue
            names = {str(s).strip().lower() for s in new.get("supersedes") or []}
            explicit = old["unit_key"] in names or f"{old['run_key']}/{old['unit_key']}" in names
            contradicts = (old["unit_key"] == new["unit_key"] and old.get("outcome") and new.get("outcome")
                           and old["outcome"] != new["outcome"])
            if (explicit or contradicts) and _newer(old, new, live):
                old["reasons"].append((SUPERSEDED, f"superseded-by:{new['run']}/{new['unit']}"))
                unordered = None
                break
            if contradicts and unordered is None and not _newer(new, old, live):
                unordered = new
        if unordered is not None:
            old["reasons"].append((UNKNOWN, f"contradicted-by:{unordered['run']}/{unordered['unit']}"))
        for obs in observations:
            if not old.get("outcome") or obs["outcome"] == old["outcome"]:
                continue
            if any(match_kind(p, obs["path"]) for p in old.get("paths") or []):
                old["reasons"].append((SUPERSEDED, f"current-evidence:{obs['path']}={obs['outcome']}"))
                break


def verdict(reasons):
    """(label, ordered reasons): the worst reason wins; no reason at all is CURRENT."""
    if not reasons:
        return CURRENT, []
    ordered = sorted(reasons, key=lambda r: -SEVERITY[r[0]])
    return ordered[0][0], [r for _label, r in ordered]


def load_observations(raw):
    """Validate the frozen task's current evidence: [{path, outcome: pass|fail, source?}]."""
    items = raw.get("observations") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ProvenanceError("current evidence must be a list or {observations: [...]}")
    out = []
    for i, item in enumerate(items):
        if (not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"].strip()
                or item.get("outcome") not in ("pass", "fail")):
            raise ProvenanceError(f"current evidence [{i}] needs a path and outcome pass|fail")
        out.append({"path": normalize_path(item["path"]), "outcome": item["outcome"],
                    "source": str(item.get("source") or "")})
    return out
