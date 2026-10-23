#!/usr/bin/env python3
"""merge_queue.py — the persisted, fenced single-conductor merge queue (#599).

merge-serialization.md says one conductor owns every merge to an integration BASE, in arrival
order, behind an expected-head guard. Until #599 that was discipline only: nothing stopped two
coordinators merging onto one BASE, and a conductor that crashed mid-train left no record of
what it had already sent. This script is the serialized merge-effect boundary that cooperating
fleet writers route their merges through. It is provider-neutral: a `merge_ready` from Orca's
mailbox or the posix provider's boards the same way.

What holds, and for whom
  * ONE conductor per (repository, BASE). `acquire` issues a lease with a fencing token and a
    monotonic epoch. Every queue mutation checks that token inside its own SQLite write
    transaction (`_fence`), so a superseded conductor is refused `fenced`: it cannot board,
    plan, dequeue, merge, acknowledge, resolve or release.
  * The remote merge happens inside the EFFECT LOCK, an exclusive flock per (repository, BASE),
    after a token-checked compare-and-set that records the merge intent (`merging`). A handoff
    must hold the same lock to bump the epoch. A conductor paused after its lease check
    therefore resumes into a refused compare-and-set and never sends. One paused INSIDE the
    boundary blocks the handoff (`merge_in_flight`) instead of being raced. The merge child
    inherits the lock, so a conductor killed mid-call holds the boundary until the call ends.
  * A handoff first reconciles every in-flight merge against authoritative state
    (`gh pr view`, or `git ls-remote` plus ancestry). One it cannot decide, because the remote
    is unreachable, blocks the handoff (`in_flight_unknown`). Nothing is guessed.
  * Before every merge it revalidates the expected heads and the tested merge tree. A head that
    moved to different content is returned to review. A content-identical move
    (reviewed-sha-freshness.md) keeps the review and pins the new head. A moved BASE, or a merge
    tree that is no longer the tested one, returns the entry to `plan` (`retest_required`).
  * Every remote read and write is bound to the queue's repository: the remote's fetch and push
    URLs must name the repository the lease names, and every `gh` call passes it as `--repo`
    (never GH_REPO or gh's own default), so no call can act on a fork or another repository.
  * Scope: cooperating fleet writers that share this store on one host. A local lease cannot
    fence an arbitrary GitHub user, or a writer that bypasses this script. Their writes surface
    as a moved BASE or a moved head, which the guards refuse; they never land untested content
    silently. In gh mode GitHub alone decides which BASE commit it merges onto, so a merge whose
    first parent is not the expected BASE head is recorded `treeMatchesTested: false`, and `ack`
    then requires an explicit `--accept-untested-tree`.
  * Default-branch promotion is human-only. `init` refuses a BASE equal to the default branch,
    boarding refuses a payload aimed at it, and no command ever writes to it.

Entry states
    queued -> merging -> merged -> landed      (the train)
    queued -> bounced                          (head moved to new content: back to review)
    queued -> failed                           (conflict, failed gate, refused merge: the train
                                                FREEZES behind it until `resolve`)
    queued -> superseded                       (the unit re-boarded at a newer reviewed SHA)
    failed -> queued | bounced | dropped       (`resolve`, the conductor's recorded decision)

Modes
    gh   `gh pr merge <n> --merge --match-head-commit <head>`, verified by `gh pr view` and
         ancestry. This is the default path.
    git  the no-gh lane (merge-serialization.md "No-gh fallback"): the merge commit is
         `commit-tree` of the TESTED tree, pushed with `--force-with-lease=<BASE>:<expected>`
         (a true compare-and-swap on the remote ref). Its receipts say `no-gh: local-merge`.

Every remote merge is preceded by an egress receipt (egress.py, fail-closed: no receipt, no
send). Receipts for every transition land in the queue's own table (`receipts`).

Usage: merge_queue.py [--db PATH] [--repo-dir DIR] [--repo ID] <command> ...
Commands: init, acquire, release, enqueue, plan, merge, ack, resolve, reconcile, status,
receipts, drain. Every command prints one JSON object.

Exit: 0 ok · 1 blocked (frozen, ack owed, retest, returned to review, offline, in flight) ·
2 usage or refused input · 3 not the owner (fenced, lease held, unknown token).
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Callable

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_USAGE = 2
EXIT_FENCED = 3

QUEUED, MERGING, MERGED, LANDED = "queued", "merging", "merged", "landed"
BOUNCED, FAILED, SUPERSEDED, DROPPED = "bounced", "failed", "superseded", "dropped"
# The states that occupy the train. Its head, the lowest arrival seq among them, is the only
# entry that may merge (arrival order only; merge-serialization.md "Rules").
LINE_STATES = (QUEUED, MERGING, MERGED, FAILED)
# One merge's committed boundaries, in order. `on_boundary` observes each one (the drills).
MERGE_BOUNDARIES = ("lease_checked", "intent_recorded", "remote_merged", "merged_recorded")
MODES = ("gh", "git")
RESOLVE_ACTIONS = {"requeue": QUEUED, "bounce": BOUNCED, "drop": DROPPED}
DEFAULT_TTL = 900.0
OBJECT_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
# A repository GitHub can name: exactly host/owner/name (the shape `gh --repo HOST/OWNER/REPO` takes).
GH_REPO_RE = re.compile(r"[A-Za-z0-9.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
# A branch name that is safe inside a refspec: no `:`, whitespace, `..`, glob or revision syntax.
BRANCH_RE = re.compile(r"(?!-)(?!refs/)(?!.*\.\.)(?!.*\.lock$)[A-Za-z0-9._/-]+")
PRIVATE_REFS = "refs/open-fleet/merge-queue"
# Prefix commits exist only to give a gate a checkout. A fixed identity and date make them
# reproducible, and they are never pushed.
PREFIX_IDENTITY = {
    "GIT_AUTHOR_NAME": "open-fleet merge-queue", "GIT_AUTHOR_EMAIL": "merge-queue@open-fleet.invalid",
    "GIT_COMMITTER_NAME": "open-fleet merge-queue", "GIT_COMMITTER_EMAIL": "merge-queue@open-fleet.invalid",
    "GIT_AUTHOR_DATE": "@0 +0000", "GIT_COMMITTER_DATE": "@0 +0000",
}
HERE = Path(__file__).resolve().parent


def _sibling(name: str, filename: str) -> Any:
    """Load a sibling runtime script by path (the bundle ships them side by side)."""
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


egress = _sibling("_mq_egress", "egress.py")
diff_scope = _sibling("_mq_diff_scope", "diff_scope.py")  # #590's in-memory merge prediction


class QueueError(Exception):
    """A refusal with a stable code; `exit_code` is what the CLI exits with."""

    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None, exit_code: int = EXIT_BLOCKED):
        super().__init__(message)
        self.code, self.message, self.data, self.exit_code = code, message, dict(data or {}), exit_code

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": False, "code": self.code, "message": self.message}
        if self.data:
            out["data"] = self.data
        return out


class Offline(QueueError):
    """The authoritative remote (GitHub or the git remote) could not be read or written."""

    def __init__(self, what: str, detail: str = ""):
        tail = f": {detail.strip()[-300:]}" if detail and detail.strip() else ""
        super().__init__("offline", f"{what} is unreachable{tail}", {"what": what})


def default_db_path(env: dict[str, str]) -> Path:
    if env.get("OPEN_FLEET_MERGE_QUEUE_DB"):
        return Path(env["OPEN_FLEET_MERGE_QUEUE_DB"]).expanduser().resolve()
    root = env.get("OPEN_FLEET_STATE_DIR") or env.get("ORCA_FLEET_STATE_DIR")
    if root:
        return Path(root).expanduser().resolve() / "merge-queue.db"
    # ONE store per host, not per clone: two conductors in two clones of one repository must
    # contend for the same lease row, or "one conductor per BASE" holds per checkout only.
    return Path.home() / ".open-fleet" / "state" / "merge-queue.db"


def repo_identity(url: str) -> str:
    """A remote URL as `host/owner/name`; a local path as its resolved absolute path."""
    u = url.strip()
    scp = re.match(r"^[\w.-]+@([^:/]+):(.+)$", u)
    if scp:
        host, path = scp.group(1), scp.group(2)
    elif "://" in u and not u.startswith("file://"):
        parts = urllib.parse.urlsplit(u)
        host, path = parts.hostname or "", parts.path
    else:
        return str(Path(u.removeprefix("file://")).expanduser().resolve())
    path = path.strip("/")
    path = path[:-4] if path.endswith(".git") else path
    return f"{host.lower()}/{path}"


def remote_host(url: str) -> str:
    ident = repo_identity(url)
    return ident.split("/", 1)[0] if not ident.startswith("/") else "localhost"


def _digest(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class _ClosingConnection(sqlite3.Connection):
    """A connection whose `with` block also closes it (local_state.py's rule)."""

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


class Store:
    """SQLite WAL store. Every write is ONE `BEGIN IMMEDIATE` transaction (`tx`)."""

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS mq_queues (
            repo TEXT NOT NULL, base TEXT NOT NULL, default_branch TEXT NOT NULL,
            mode TEXT NOT NULL, remote TEXT NOT NULL, host TEXT NOT NULL, consent TEXT NOT NULL,
            next_seq INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL,
            PRIMARY KEY (repo, base)
        );
        CREATE TABLE IF NOT EXISTS mq_leases (
            repo TEXT NOT NULL, base TEXT NOT NULL, holder TEXT NOT NULL, token TEXT NOT NULL,
            epoch INTEGER NOT NULL, pid INTEGER, host TEXT, ttl REAL NOT NULL,
            acquired_at REAL NOT NULL, expires_at REAL NOT NULL, released_at REAL,
            PRIMARY KEY (repo, base)
        );
        CREATE TABLE IF NOT EXISTS mq_tokens (
            token TEXT PRIMARY KEY, repo TEXT NOT NULL, base TEXT NOT NULL,
            epoch INTEGER NOT NULL, holder TEXT NOT NULL, issued_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mq_entries (
            entry_id TEXT PRIMARY KEY, repo TEXT NOT NULL, base TEXT NOT NULL,
            seq INTEGER NOT NULL, run_id TEXT NOT NULL, unit TEXT NOT NULL, pr INTEGER,
            branch TEXT NOT NULL, reviewed_sha TEXT NOT NULL, reviewed_tree TEXT,
            delivery_key TEXT NOT NULL, payload_fp TEXT NOT NULL, deliveries_json TEXT NOT NULL,
            state TEXT NOT NULL, reason TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            UNIQUE (repo, base, delivery_key), UNIQUE (repo, base, seq)
        );
        CREATE TABLE IF NOT EXISTS mq_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, repo TEXT NOT NULL, base TEXT NOT NULL,
            entry_id TEXT, kind TEXT NOT NULL, epoch INTEGER, holder TEXT,
            body_json TEXT NOT NULL, created_at REAL NOT NULL
        );
    """
    # Additive columns, migrated in place (local_state.py's `_migrate` rule): a store written by
    # an older schema gains them on open. Schema and migration run in ONE `BEGIN IMMEDIATE`
    # transaction, so concurrent openers take turns and each re-reads the columns under the lock.
    COLUMNS = {
        "mq_entries": {
            "accepted_head": "TEXT", "expected_base": "TEXT", "tested_base_tree": "TEXT",
            "tested_tree": "TEXT", "prefix_commit": "TEXT", "gate_json": "TEXT",
            "merging_epoch": "INTEGER", "merging_pid": "INTEGER", "merge_sha": "TEXT",
            "merged_tree": "TEXT", "tree_matches_tested": "INTEGER", "reviewed_tree_source": "TEXT",
        },
    }

    BUSY_SECONDS = 30.0

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as conn:
            # Not executescript: it COMMITs first and runs each statement in autocommit, which
            # would let another opener interleave between the CREATEs and the migration.
            for statement in self.SCHEMA.split(";"):
                if statement.strip():
                    conn.execute(statement)
            self._migrate(conn)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=self.BUSY_SECONDS, isolation_level=None,
                               factory=_ClosingConnection)
        conn.row_factory = sqlite3.Row
        # The busy timeout first, so every statement below (and after) waits out a lock.
        conn.execute(f"PRAGMA busy_timeout={int(self.BUSY_SECONDS * 1000)};")
        self._wal(conn)
        return conn

    def _wal(self, conn: sqlite3.Connection) -> None:
        """Put the store in WAL mode, once per database file, surviving concurrent openers.

        Switching the journal mode needs an exclusive lock, and SQLite answers a contender
        `database is locked` at once rather than through the busy handler. Several conductors
        opening a fresh store together hit exactly that (#599 CI: openers exiting 1 at random).
        WAL is persistent, so the first opener's switch is every later connection's no-op;
        a contender backs off and re-reads the mode until it sees WAL.
        """
        deadline = time.monotonic() + self.BUSY_SECONDS
        delay = 0.005
        while True:
            try:
                if str(conn.execute("PRAGMA journal_mode;").fetchone()[0]).lower() == "wal":
                    return
                conn.execute("PRAGMA journal_mode=WAL;")
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                if time.monotonic() >= deadline:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 0.2)

    @classmethod
    def _migrate(cls, conn: sqlite3.Connection) -> None:
        for table, cols in cls.COLUMNS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for col, decl in cols.items():
                if col in have:
                    continue
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                except sqlite3.OperationalError as exc:  # added already: the outcome we wanted
                    if "duplicate column" not in str(exc).lower():
                        raise

    @contextlib.contextmanager
    def tx(self):
        """One write transaction; an exception (a refusal included) rolls it back whole."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def read(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]


class EffectLock:
    """The serialized merge-effect boundary for one (repository, BASE): an exclusive flock (#599).

    Held from the fenced intent compare-and-set through the remote merge and its record, and by
    every handoff. The kernel drops it when its last holder dies, however it dies. The merge child
    inherits the descriptor (`pass_fds`), so a conductor killed mid-call keeps the boundary held
    until the remote call itself ends. A handoff can never reconcile a merge that is still being
    sent. Never take two of these for one queue in one process: flock locks are per open file.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.fd: int | None = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)

    def acquire(self, wait: float = 0.0) -> bool:
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)

    def release(self) -> None:
        # Close, never LOCK_UN: an unlock would drop the lock a still-running merge child shares.
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class Git:
    """git in the conductor's clone, under the caller's identity and credentials, never prompting."""

    def __init__(self, repo_dir: Path, env: dict[str, str]):
        self.repo_dir = str(repo_dir)
        found = shutil.which("git", path=env.get("PATH"))
        self.bin = os.path.abspath(found) if found else "git"
        self.env = {**env, "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1"}

    def run(self, *args: str, check: bool = True, env: dict[str, str] | None = None,
            pass_fds: tuple[int, ...] = (), timeout: float = 300.0) -> subprocess.CompletedProcess:
        try:
            proc = subprocess.run([self.bin, "-C", self.repo_dir, *args], capture_output=True, text=True,
                                  env={**self.env, **(env or {})}, pass_fds=pass_fds, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise QueueError("git_failed", f"git {' '.join(args[:2])} could not run: {exc}") from exc
        if check and proc.returncode != 0:
            raise QueueError("git_failed", f"git {' '.join(args[:3])} failed: {(proc.stderr or proc.stdout).strip()[-300:]}")
        return proc

    def out(self, *args: str) -> str:
        return self.run(*args).stdout.strip()

    def fetch(self, remote: str, src: str, private: str) -> str | None:
        """Fetch `src` from `remote` into a private ref; its sha, or None when the remote lacks it."""
        dst = f"{PRIVATE_REFS}/{private}"
        proc = self.run("fetch", "--no-tags", "--quiet", remote, f"+{src}:{dst}", check=False)
        if proc.returncode != 0:
            err = (proc.stderr or "").lower()
            if "couldn't find remote ref" in err or "not our ref" in err or "invalid refspec" in err:
                return None
            raise Offline(f"git remote {remote!r}", proc.stderr)
        return self.out("rev-parse", "--verify", f"{dst}^{{commit}}")

    def remote_urls(self, remote: str) -> tuple[list[str], list[str]]:
        """The remote's configured fetch URLs and push URLs, as written (before `insteadOf`)."""
        def values(key: str) -> list[str]:
            proc = self.run("config", "--get-all", key, check=False)
            return [v.strip() for v in proc.stdout.splitlines() if v.strip()]
        return values(f"remote.{remote}.url"), values(f"remote.{remote}.pushurl")

    def has_commit(self, sha: str | None) -> bool:
        return bool(sha) and self.run("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0

    def tree(self, rev: str) -> str:
        return self.out("rev-parse", "--verify", f"{rev}^{{tree}}")

    def is_ancestor(self, a: str, b: str) -> bool:
        proc = self.run("merge-base", "--is-ancestor", a, b, check=False)
        if proc.returncode not in (0, 1):
            raise QueueError("git_failed", f"merge-base --is-ancestor failed: {proc.stderr.strip()[-200:]}")
        return proc.returncode == 0

    def parents(self, sha: str) -> list[str]:
        return self.out("rev-list", "--parents", "-n", "1", sha).split()[1:]

    def commit_tree(self, tree: str, parents: list[str], message: str, env: dict[str, str] | None = None,
                    sign: bool = True) -> str:
        args = ["commit-tree", tree] if sign else ["commit-tree", "--no-gpg-sign", tree]
        for parent in parents:
            args += ["-p", parent]
        return self.run(*args, "-m", message, env=env).stdout.strip()

    def keep(self, name: str, sha: str) -> None:
        """Pin an object under the private namespace so gc never prunes what a receipt names."""
        self.run("update-ref", f"{PRIVATE_REFS}/{name}", sha)


class Gh:
    """The GitHub seam: the `gh` CLI, resolved once to an absolute path from the caller's PATH."""

    FIELDS = "number,state,headRefOid,headRefName,baseRefName,mergeCommit,url"

    def __init__(self, repo_dir: Path, env: dict[str, str]):
        found = shutil.which("gh", path=env.get("PATH"))
        self.bin = os.path.abspath(found) if found else None
        self.repo_dir, self.env = str(repo_dir), env

    def _run(self, args: list[str], pass_fds: tuple[int, ...] = ()) -> subprocess.CompletedProcess:
        if self.bin is None:
            raise Offline("GitHub (no gh on PATH)")
        try:
            # GH_REPO dropped: every call names its repository with --repo, so nothing in the
            # environment can redirect a read or a merge to another repository (PR #647).
            env = {k: v for k, v in self.env.items() if k != "GH_REPO"}
            return subprocess.run([self.bin, *args], capture_output=True, text=True, cwd=self.repo_dir,
                                  env={**env, "GH_PROMPT_DISABLED": "1"}, pass_fds=pass_fds, timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Offline("GitHub", str(exc)) from exc

    def pr_view(self, repo: str, pr: int) -> dict[str, Any]:
        proc = self._run(["pr", "view", str(pr), "--repo", repo, "--json", self.FIELDS])
        if proc.returncode != 0:
            raise Offline("GitHub", proc.stderr)
        try:
            data = json.loads(proc.stdout)
        except ValueError as exc:
            raise Offline("GitHub", f"unparseable pr view: {exc}") from exc
        if not isinstance(data, dict) or not OBJECT_RE.fullmatch(str(data.get("headRefOid", ""))):
            raise Offline("GitHub", "pr view returned no headRefOid")
        return data

    def pr_merge(self, repo: str, pr: int, head: str, delete_branch: bool,
                 pass_fds: tuple[int, ...]) -> subprocess.CompletedProcess:
        args = ["pr", "merge", str(pr), "--repo", repo, "--merge", "--match-head-commit", head]
        if delete_branch:
            args.append("--delete-branch")
        return self._run(args, pass_fds=pass_fds)


class MergeQueue:
    """The queue for every (repository, BASE) in one store, driven from one conductor clone."""

    def __init__(self, db_path: str | Path | None = None, repo_dir: str | Path = ".", env: dict[str, str] | None = None):
        self.env = dict(os.environ if env is None else env)
        self.db_path = Path(db_path) if db_path else default_db_path(self.env)
        self.store = Store(self.db_path)
        self.repo_dir = Path(repo_dir).resolve()
        self.git = Git(self.repo_dir, self.env)
        self.gh = Gh(self.repo_dir, self.env)
        self.clock: Callable[[], float] = time.time
        # Observer for the committed merge boundaries (MERGE_BOUNDARIES); the drills park here.
        self.on_boundary: Callable[[str, dict[str, Any]], None] | None = None

    # --- identity, config, receipts -------------------------------------------------------
    def default_repo(self, remote: str = "origin") -> str:
        urls, _push = self.git.remote_urls(remote)
        if not urls:
            raise QueueError("usage", f"no --repo given and remote {remote!r} has no URL in {self.repo_dir}",
                             exit_code=EXIT_USAGE)
        return repo_identity(urls[0])

    def _bound_remote(self, cfg: dict[str, Any]) -> str:
        """The queue's remote, after proving it still names the queue's repository (PR #647).

        The lease, the entries and every receipt name `cfg["repo"]`. A remote re-pointed after
        `init`, or a push URL aimed elsewhere, would read one repository and write another, so
        every URL the remote is configured with (fetch and push, as written) must name it.
        Called before every remote read and write; a mismatch refuses before anything is sent.
        """
        remote = cfg["remote"]
        urls, push = self.git.remote_urls(remote)
        named = {f"url {u}": repo_identity(u) for u in urls}
        named.update({f"pushurl {u}": repo_identity(u) for u in push})
        wrong = {k: v for k, v in named.items() if v != cfg["repo"]}
        if not urls or wrong:
            raise QueueError(
                "repo_mismatch",
                f"remote {remote!r} does not name the queue's repository {cfg['repo']} "
                f"({', '.join(f'{k} -> {v}' for k, v in wrong.items()) or 'no URL'}); nothing was read or sent",
                {"remote": remote, "queue": cfg["repo"], "named": named},
            )
        return remote

    def _config(self, conn: sqlite3.Connection, repo: str, base: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM mq_queues WHERE repo = ? AND base = ?", (repo, base)).fetchone()
        if row is None:
            raise QueueError("queue_not_found", f"no merge queue for {repo} BASE {base!r}: run init first",
                             exit_code=EXIT_USAGE)
        return dict(row)

    def _receipt(self, conn: sqlite3.Connection, repo: str, base: str, kind: str, body: dict[str, Any],
                 entry_id: str | None = None, lease: dict[str, Any] | None = None) -> None:
        conn.execute(
            "INSERT INTO mq_receipts(repo, base, entry_id, kind, epoch, holder, body_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (repo, base, entry_id, kind, lease["epoch"] if lease else None, lease["holder"] if lease else None,
             json.dumps(body, sort_keys=True, default=str), self.clock()),
        )

    def _lock(self, repo: str, base: str) -> EffectLock:
        name = hashlib.sha256(f"{repo}\0{base}".encode("utf-8")).hexdigest()[:24]
        return EffectLock(self.db_path.parent / "merge-queue-locks" / f"{name}.lock")

    def _boundary(self, stage: str, info: dict[str, Any]) -> None:
        if self.on_boundary is not None:
            self.on_boundary(stage, dict(info))

    @staticmethod
    def _check_branch(name: str, flag: str) -> str:
        if not isinstance(name, str) or not BRANCH_RE.fullmatch(name):
            raise QueueError("usage", f"{flag} {name!r} is not a plain branch name", exit_code=EXIT_USAGE)
        return name

    def init(self, *, repo: str, base: str, default: str, consent: str, mode: str = "gh",
             remote: str = "origin", host: str | None = None) -> dict[str, Any]:
        self._check_branch(base, "--base")
        self._check_branch(default, "--default")
        if base == default:
            raise QueueError("promotion_is_human", f"BASE {base!r} is the default branch: promotion to it is a "
                             "one-way human gate, and this queue never merges to it", exit_code=EXIT_USAGE)
        if mode not in MODES:
            raise QueueError("usage", f"--mode must be one of {MODES}", exit_code=EXIT_USAGE)
        if not consent or not consent.strip():
            raise QueueError("usage", "--consent names the standing grant every merge's egress receipt cites",
                             exit_code=EXIT_USAGE)
        urls, _push = self.git.remote_urls(remote)
        named = repo_identity(urls[0]) if urls else None
        if named != repo:
            raise QueueError("repo_mismatch", f"--repo {repo} is not the repository remote {remote!r} names "
                             f"({named or 'no URL'}): the lease and every merge must name one repository",
                             {"repo": repo, "remote": remote, "named": named}, exit_code=EXIT_USAGE)
        if mode == "gh" and not GH_REPO_RE.fullmatch(repo):
            raise QueueError("repo_mismatch", f"the gh lane merges through GitHub, but remote {remote!r} names "
                             f"{repo}, not a host/owner/name repository (use --mode git for a local remote)",
                             {"repo": repo, "remote": remote}, exit_code=EXIT_USAGE)
        try:
            self._bound_remote({"remote": remote, "repo": repo})
        except QueueError as exc:
            raise QueueError(exc.code, exc.message, exc.data, exit_code=EXIT_USAGE) from exc
        if host is None:
            host = repo.split("/", 1)[0] if mode == "gh" else remote_host(urls[0])
        want = {"default_branch": default, "mode": mode, "remote": remote, "host": host, "consent": consent}
        with self.store.tx() as conn:
            row = conn.execute("SELECT * FROM mq_queues WHERE repo = ? AND base = ?", (repo, base)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO mq_queues(repo, base, default_branch, mode, remote, host, consent, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (repo, base, default, mode, remote, host, consent, self.clock()),
                )
                self._receipt(conn, repo, base, "queue_opened",
                              {**want, "promotion": f"{base}->{default} is human-only; never merged here"})
                created = True
            else:
                have = {k: row[k] for k in want}
                if have != want:
                    raise QueueError("queue_config_mismatch", f"queue {repo} {base!r} exists with other settings",
                                     {"have": have, "want": want}, exit_code=EXIT_USAGE)
                created = False
        return {"ok": True, "repo": repo, "base": base, "created": created, **want}

    # --- the lease and its fencing token ---------------------------------------------------
    def _fence(self, conn: sqlite3.Connection, token: str) -> dict[str, Any]:
        """Inside an open write transaction: refuse a token that is not the current owner's.

        This is the fencing check every queue mutation runs. A conductor whose lease was taken
        over or re-acquired (a new epoch), or released, is refused here, and the whole
        transaction rolls back with it. A live owner's lease is renewed by the same write.
        """
        tok = conn.execute("SELECT * FROM mq_tokens WHERE token = ?", (token,)).fetchone()
        if tok is None:
            raise QueueError("unknown_token", "this token was never issued by this store", exit_code=EXIT_FENCED)
        lease = conn.execute("SELECT * FROM mq_leases WHERE repo = ? AND base = ?", (tok["repo"], tok["base"])).fetchone()
        if lease is None or lease["token"] != token or lease["released_at"] is not None:
            raise QueueError(
                "fenced",
                f"epoch {tok['epoch']} ({tok['holder']}) no longer owns {tok['base']!r}: "
                f"{'released' if lease is not None and lease['token'] == token else 'superseded'}; this conductor "
                "stops and leaves the queue to the current owner",
                {"epoch": tok["epoch"], "currentEpoch": lease["epoch"] if lease else None,
                 "currentHolder": lease["holder"] if lease else None},
                exit_code=EXIT_FENCED,
            )
        conn.execute("UPDATE mq_leases SET expires_at = ? WHERE repo = ? AND base = ?",
                     (self.clock() + lease["ttl"], lease["repo"], lease["base"]))
        return dict(lease)

    def _owner(self, token: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """(queue config, lease) for a token that is still the owner's; a fenced read."""
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            return self._config(conn, lease["repo"], lease["base"]), lease

    def acquire(self, *, repo: str, base: str, holder: str, ttl: float = DEFAULT_TTL,
                takeover: bool = False, wait: float = 0.0) -> dict[str, Any]:
        """Become the conductor: reconcile every in-flight merge, THEN bump the epoch.

        A live lease held by another holder is refused unless `takeover`. The same holder
        re-acquiring is a restart and also bumps the epoch, which fences any older process
        still using the old token. The handoff holds the effect lock throughout, so no merge
        can be sent while it decides, and one still being sent blocks it.
        """
        if not holder or not holder.strip():
            raise QueueError("usage", "--holder names the conductor (its terminal handle)", exit_code=EXIT_USAGE)
        if ttl <= 0:
            raise QueueError("usage", "--ttl must be positive", exit_code=EXIT_USAGE)
        with self.store.connect() as conn:
            cfg = self._config(conn, repo, base)
        lock = self._lock(repo, base)
        try:
            if not lock.acquire(wait):
                flying = self.store.read("SELECT entry_id, unit, merging_pid, merging_epoch FROM mq_entries "
                                         "WHERE repo = ? AND base = ? AND state = ?", (repo, base, MERGING))
                raise QueueError(
                    "merge_in_flight",
                    "a conductor is inside the merge boundary; ownership is handed off only after its remote "
                    "merge settles (retry with --wait, or inspect the process holding it)",
                    {"inFlight": flying, "lock": str(lock.path)},
                )
            now = self.clock()
            with self.store.connect() as conn:
                prev = conn.execute("SELECT * FROM mq_leases WHERE repo = ? AND base = ?", (repo, base)).fetchone()
            prev = dict(prev) if prev else None
            live = bool(prev and prev["released_at"] is None and prev["expires_at"] > now)
            if live and prev["holder"] != holder and not takeover:
                raise QueueError(
                    "lease_held",
                    f"{prev['holder']} holds the lease on {base!r} (epoch {prev['epoch']}) until it expires; "
                    "--takeover fences that conductor",
                    {"holder": prev["holder"], "epoch": prev["epoch"], "expiresAt": prev["expires_at"]},
                    exit_code=EXIT_FENCED,
                )
            # Reconcile BEFORE handing off (#599): an in-flight merge is settled from authoritative
            # state, never inherited as a guess. Undecidable means no handoff.
            decisions = [self._reconcile_decision(cfg, e) for e in self._entries(repo, base, (MERGING,))]
            unknown = [d for d in decisions if d["resolution"] == "unknown"]
            if unknown:
                raise QueueError(
                    "in_flight_unknown",
                    "an in-flight merge cannot be reconciled (the remote is unreachable); ownership is not "
                    "handed off until it can be",
                    {"unknown": unknown},
                )
            token = uuid.uuid4().hex
            with self.store.tx() as conn:
                again = conn.execute("SELECT epoch FROM mq_leases WHERE repo = ? AND base = ?", (repo, base)).fetchone()
                if (again["epoch"] if again else 0) != (prev["epoch"] if prev else 0):
                    raise QueueError("lease_raced", "the lease changed during the handoff; retry", exit_code=EXIT_FENCED)
                epoch = (prev["epoch"] if prev else 0) + 1
                lease = {"repo": repo, "base": base, "holder": holder, "token": token, "epoch": epoch}
                for d in decisions:
                    self._apply_reconcile(conn, cfg, d, lease)
                conn.execute(
                    "INSERT INTO mq_leases(repo, base, holder, token, epoch, pid, host, ttl, acquired_at, expires_at, "
                    "released_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL) ON CONFLICT(repo, base) DO UPDATE SET "
                    "holder = excluded.holder, token = excluded.token, epoch = excluded.epoch, pid = excluded.pid, "
                    "host = excluded.host, ttl = excluded.ttl, acquired_at = excluded.acquired_at, "
                    "expires_at = excluded.expires_at, released_at = NULL",
                    (repo, base, holder, token, epoch, os.getpid(), socket.gethostname(), ttl, now, now + ttl),
                )
                conn.execute("INSERT INTO mq_tokens(token, repo, base, epoch, holder, issued_at) VALUES (?, ?, ?, ?, ?, ?)",
                             (token, repo, base, epoch, holder, now))
                previous = ({"holder": prev["holder"], "epoch": prev["epoch"], "live": live} if prev else None)
                self._receipt(conn, repo, base, "lease_acquired",
                              {"previous": previous, "takeover": bool(takeover and live), "reconciled": decisions},
                              lease=lease)
        finally:
            lock.release()
        return {"ok": True, "token": token, "epoch": epoch, "holder": holder, "repo": repo, "base": base,
                "previous": previous, "reconciled": decisions}

    def release(self, token: str) -> dict[str, Any]:
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            flying = conn.execute("SELECT entry_id FROM mq_entries WHERE repo = ? AND base = ? AND state = ?",
                                  (lease["repo"], lease["base"], MERGING)).fetchall()
            if flying:
                raise QueueError("merge_in_flight", "an in-flight merge must settle before the lease is released",
                                 {"inFlight": [r["entry_id"] for r in flying]})
            conn.execute("UPDATE mq_leases SET released_at = ? WHERE repo = ? AND base = ?",
                         (self.clock(), lease["repo"], lease["base"]))
            self._receipt(conn, lease["repo"], lease["base"], "lease_released", {}, lease=lease)
        return {"ok": True, "released": True, "epoch": lease["epoch"]}

    # --- boarding ---------------------------------------------------------------------------
    @staticmethod
    def parse_payload(raw: str | dict[str, Any]) -> dict[str, Any]:
        """A `merge_ready` payload (merge-serialization.md "Signal"), validated before any write."""
        try:
            p = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except ValueError as exc:
            raise QueueError("invalid_payload", f"--payload is not JSON: {exc}", exit_code=EXIT_USAGE) from exc
        if not isinstance(p, dict):
            raise QueueError("invalid_payload", "--payload must be a JSON object", exit_code=EXIT_USAGE)
        bad = []
        unit, branch, base = p.get("unit"), p.get("branch"), p.get("base")
        sha, tree, pr = p.get("reviewed_sha"), p.get("reviewed_wtree"), p.get("pr")
        if not isinstance(unit, str) or not unit.strip():
            bad.append("unit")
        if not isinstance(branch, str) or not BRANCH_RE.fullmatch(branch):
            bad.append("branch (a plain branch name)")
        if not isinstance(base, str) or not BRANCH_RE.fullmatch(base):
            bad.append("base (a plain branch name)")
        if not isinstance(sha, str) or not OBJECT_RE.fullmatch(sha):
            bad.append("reviewed_sha (a full commit id)")
        if tree is not None and not (isinstance(tree, str) and OBJECT_RE.fullmatch(tree)):
            bad.append("reviewed_wtree (a full tree id, or absent)")
        if pr is not None and not (type(pr) is int and pr > 0):
            bad.append("pr (a positive integer, or null on the no-gh lane)")
        if p.get("repo") is not None and not (isinstance(p["repo"], str) and p["repo"].strip()):
            bad.append("repo (the repository identity, or absent)")
        if bad:
            raise QueueError("invalid_payload", f"merge_ready payload: bad {', '.join(bad)}", exit_code=EXIT_USAGE)
        return {"unit": unit, "branch": branch, "base": base, "reviewed_sha": sha, "reviewed_tree": tree,
                "pr": pr, "run": p.get("run"), "repo": p.get("repo")}

    def enqueue(self, token: str, payload: str | dict[str, Any], *, run: str | None = None,
                delivery: str | None = None) -> dict[str, Any]:
        """Board one `merge_ready` at the back of the train; a duplicate delivery is a no-op."""
        p = self.parse_payload(payload)
        run_id = run or p["run"] or "default"
        if self.git.has_commit(p["reviewed_sha"]) and p["reviewed_tree"]:
            # The payload's tree is checked whenever the reviewed commit is at hand (verify.py's rule:
            # both trees are recomputed, so a forged reviewed_wtree cannot buy equivalence).
            if self.git.tree(p["reviewed_sha"]) != p["reviewed_tree"]:
                raise QueueError("reviewed_tree_mismatch", "reviewed_wtree is not the tree of reviewed_sha",
                                 exit_code=EXIT_USAGE)
        key = _digest("merge_ready", run_id, p["unit"], p["reviewed_sha"])
        fingerprint = _digest(p["pr"], p["branch"], p["reviewed_tree"], p["base"])
        now = self.clock()
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            repo, base = lease["repo"], lease["base"]
            cfg = self._config(conn, repo, base)
            if p["base"] == cfg["default_branch"]:
                raise QueueError("promotion_is_human", f"payload targets the default branch {p['base']!r}: "
                                 "promotion is a one-way human gate", exit_code=EXIT_USAGE)
            if p["base"] != base:
                raise QueueError("wrong_base", f"payload targets {p['base']!r}, this queue is {base!r}",
                                 exit_code=EXIT_USAGE)
            if p["repo"] is not None and p["repo"] != repo:
                # An optional field, checked when a sender states it (PR #647): a PR number means
                # nothing outside its repository.
                raise QueueError("repo_mismatch", f"payload names repository {p['repo']}, this queue is {repo}",
                                 exit_code=EXIT_USAGE)
            if cfg["mode"] == "gh" and p["pr"] is None:
                raise QueueError("invalid_payload", "the gh lane needs a PR number (null is the no-gh lane)",
                                 exit_code=EXIT_USAGE)
            row = conn.execute("SELECT * FROM mq_entries WHERE repo = ? AND base = ? AND delivery_key = ?",
                               (repo, base, key)).fetchone()
            if row is not None:
                if row["payload_fp"] != fingerprint:
                    raise QueueError("payload_mismatch", f"unit {p['unit']!r} at {p['reviewed_sha'][:12]} is already "
                                     "boarded with a different PR, branch or tree", {"entry": row["entry_id"]},
                                     exit_code=EXIT_USAGE)
                seen = json.loads(row["deliveries_json"])
                if delivery and delivery not in seen:
                    seen.append(delivery)
                    conn.execute("UPDATE mq_entries SET deliveries_json = ? WHERE entry_id = ?",
                                 (json.dumps(seen), row["entry_id"]))
                self._receipt(conn, repo, base, "duplicate_delivery", {"delivery": delivery}, row["entry_id"], lease)
                return {"ok": True, "duplicate": True, "entry": self._entry_view(dict(row))}
            superseded = []
            for other in conn.execute("SELECT * FROM mq_entries WHERE repo = ? AND base = ? AND run_id = ? AND unit = ? "
                                      "AND state IN (?, ?, ?, ?, ?)",
                                      (repo, base, run_id, p["unit"], *LINE_STATES, LANDED)).fetchall():
                if other["state"] == QUEUED:
                    conn.execute("UPDATE mq_entries SET state = ?, reason = ?, updated_at = ? WHERE entry_id = ?",
                                 (SUPERSEDED, f"re-boarded at {p['reviewed_sha']}", now, other["entry_id"]))
                    superseded.append(other["entry_id"])
                    continue
                code = {MERGING: "unit_in_flight", MERGED: "ack_owed", FAILED: "unit_frozen",
                        LANDED: "unit_already_landed"}[other["state"]]
                raise QueueError(code, f"unit {p['unit']!r} already has entry {other['entry_id']} in state "
                                 f"{other['state']!r}; settle it before boarding a new reviewed SHA",
                                 {"entry": other["entry_id"]}, exit_code=EXIT_USAGE if other["state"] == LANDED else EXIT_BLOCKED)
            seq = cfg["next_seq"]
            conn.execute("UPDATE mq_queues SET next_seq = next_seq + 1 WHERE repo = ? AND base = ?", (repo, base))
            entry_id = f"mq_{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO mq_entries(entry_id, repo, base, seq, run_id, unit, pr, branch, reviewed_sha, reviewed_tree, "
                "delivery_key, payload_fp, deliveries_json, state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry_id, repo, base, seq, run_id, p["unit"], p["pr"], p["branch"], p["reviewed_sha"], p["reviewed_tree"],
                 key, fingerprint, json.dumps([delivery] if delivery else []), QUEUED, now, now),
            )
            for old in superseded:
                self._receipt(conn, repo, base, "superseded", {"by": entry_id}, old, lease)
            self._receipt(conn, repo, base, "boarded", {"seq": seq, "run": run_id, "unit": p["unit"], "pr": p["pr"],
                                                        "branch": p["branch"], "reviewedSha": p["reviewed_sha"],
                                                        "reviewedTree": p["reviewed_tree"], "base": base,
                                                        "delivery": delivery}, entry_id, lease)
            row = conn.execute("SELECT * FROM mq_entries WHERE entry_id = ?", (entry_id,)).fetchone()
        return {"ok": True, "duplicate": False, "superseded": superseded, "entry": self._entry_view(dict(row))}

    # --- authoritative remote state ----------------------------------------------------------
    def _base_head(self, cfg: dict[str, Any]) -> str:
        head = self.git.fetch(self._bound_remote(cfg), f"refs/heads/{cfg['base']}", f"base/{cfg['base']}")
        if head is None:
            raise QueueError("base_missing", f"BASE {cfg['base']!r} does not exist on {cfg['remote']!r}")
        return head

    def _unit_state(self, cfg: dict[str, Any], e: dict[str, Any]) -> dict[str, Any]:
        """The unit's head and PR facts, read from GitHub (gh) or the remote branch (git)."""
        remote = self._bound_remote(cfg)
        if cfg["mode"] == "gh":
            view = self.gh.pr_view(cfg["repo"], e["pr"])
            reported = repo_identity(str(view.get("url") or "").split("/pull/", 1)[0]) if view.get("url") else None
            if reported != cfg["repo"]:
                raise QueueError("repo_mismatch", f"GitHub reported PR #{e['pr']} in {reported or 'no repository'}, "
                                 f"not the queue's {cfg['repo']}; nothing was sent",
                                 {"queue": cfg["repo"], "reported": reported, "pr": e["pr"]})
            head = view["headRefOid"]
            if not self.git.has_commit(head):
                got = self.git.fetch(remote, f"refs/pull/{e['pr']}/head", f"pr/{e['pr']}")
                if got != head and view.get("headRefName"):
                    self.git.fetch(remote, f"refs/heads/{view['headRefName']}", f"pr/{e['pr']}")
            merge = view.get("mergeCommit") or {}
            return {"head": head if self.git.has_commit(head) else None, "reported": head,
                    "state": str(view.get("state", "")).upper(), "baseRefName": view.get("baseRefName"),
                    "headRefName": view.get("headRefName"),
                    "mergeCommit": merge.get("oid") if isinstance(merge, dict) else None}
        head = self.git.fetch(remote, f"refs/heads/{e['branch']}", f"branch/{e['branch']}")
        return {"head": head, "reported": head, "state": "OPEN" if head else "MISSING",
                "baseRefName": cfg["base"], "mergeCommit": None}

    def _reviewed_tree(self, e: dict[str, Any]) -> tuple[str | None, str]:
        """The reviewed content's tree: recomputed when the reviewed commit is at hand, else the payload's."""
        if not self.git.has_commit(e["reviewed_sha"]):
            remote = self._cfg_remote(e)  # a repository mismatch refuses; only the fetch is best-effort
            with contextlib.suppress(QueueError):
                self.git.fetch(remote, e["reviewed_sha"], f"entry/{e['entry_id']}/reviewed")
        if self.git.has_commit(e["reviewed_sha"]):
            return self.git.tree(e["reviewed_sha"]), "recomputed"
        return e["reviewed_tree"], "payload"

    def _cfg_remote(self, e: dict[str, Any]) -> str:
        rows = self.store.read("SELECT * FROM mq_queues WHERE repo = ? AND base = ?", (e["repo"], e["base"]))
        if not rows:
            raise QueueError("queue_not_found", f"no merge queue for {e['repo']} BASE {e['base']!r}")
        return self._bound_remote(rows[0])

    def _fresh_head(self, e: dict[str, Any], head: str) -> tuple[str | None, str | None]:
        """reviewed-sha-freshness.md: (accepted head, how) or (None, why it returns to review).

        The review binds `reviewed_sha`. Exactly one equivalence class keeps it: a head whose tree
        IS the reviewed tree (a content-identical rebase or amend). Any content change voids it.
        """
        if head == e["reviewed_sha"]:
            return head, "reviewed_sha"
        reviewed_tree, _source = self._reviewed_tree(e)
        if reviewed_tree and self.git.tree(head) == reviewed_tree:
            return head, "content_equivalent"
        return None, "content_changed"

    def _bounce_reason(self, cfg: dict[str, Any], e: dict[str, Any], st: dict[str, Any]) -> str | None:
        """Why this unit cannot ride the train as reviewed (None when it can)."""
        if st["state"] == "MISSING":
            return "branch_missing"
        if st["state"] == "CLOSED":
            return "closed_unmerged"
        if st["baseRefName"] != cfg["base"] or st["baseRefName"] == cfg["default_branch"]:
            return "wrong_base"
        if st.get("headRefName") is not None and st["headRefName"] != e["branch"]:
            return "pr_branch_mismatch"  # the PR number names another unit's PR
        if st["head"] is None:
            return "head_unavailable"
        return None

    # --- the train: plan, merge, reconcile, ack, resolve ---------------------------------------
    def _entries(self, repo: str, base: str, states: tuple[str, ...]) -> list[dict[str, Any]]:
        marks = ",".join("?" for _ in states)
        return self.store.read(f"SELECT * FROM mq_entries WHERE repo = ? AND base = ? AND state IN ({marks}) "
                               "ORDER BY seq ASC", (repo, base, *states))

    def _line(self, repo: str, base: str) -> list[dict[str, Any]]:
        return self._entries(repo, base, LINE_STATES)

    @staticmethod
    def _clear_tested(conn: sqlite3.Connection, repo: str, base: str, after_seq: int = 0) -> None:
        """A prefix changed: every queued entry behind it must be planned (tested) again."""
        conn.execute("UPDATE mq_entries SET tested_base_tree = NULL, tested_tree = NULL, prefix_commit = NULL, "
                     "gate_json = NULL WHERE repo = ? AND base = ? AND state = ? AND seq > ?",
                     (repo, base, QUEUED, after_seq))

    def _guard_head(self, line: list[dict[str, Any]], entry_id: str | None = None) -> dict[str, Any] | None:
        if not line:
            return None
        head = line[0]
        if head["state"] == FAILED:
            raise QueueError("queue_frozen", f"the train is frozen behind failed entry {head['entry_id']} "
                             f"({head['reason']}): resolve it (requeue, bounce or drop) first",
                             {"entry": head["entry_id"], "unit": head["unit"], "reason": head["reason"]})
        if head["state"] == MERGED:
            raise QueueError("ack_owed", f"entry {head['entry_id']} merged at {head['merge_sha']} and is not "
                             "acknowledged yet: ack it before the next merge", {"entry": head["entry_id"]})
        if entry_id and entry_id != head["entry_id"]:
            raise QueueError("not_head", f"{entry_id} is not the head of the train ({head['entry_id']} is): "
                             "arrival order only", {"head": head["entry_id"]}, exit_code=EXIT_USAGE)
        return head

    def settle_in_flight(self, token: str) -> list[dict[str, Any]]:
        """The owner's own reconcile: settle a `merging` entry an earlier attempt left behind."""
        cfg, _lease = self._owner(token)
        if not self._entries(cfg["repo"], cfg["base"], (MERGING,)):
            return []
        lock = self._lock(cfg["repo"], cfg["base"])
        try:
            if not lock.acquire(30.0):
                raise QueueError("merge_in_flight", "another process holds the merge boundary")
            return self._settle_locked(token, cfg)
        finally:
            lock.release()

    def _settle_locked(self, token: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        decisions = [self._reconcile_decision(cfg, e) for e in self._entries(cfg["repo"], cfg["base"], (MERGING,))]
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            for d in decisions:
                self._apply_reconcile(conn, cfg, d, lease)
        unknown = [d for d in decisions if d["resolution"] == "unknown"]
        if unknown:
            raise QueueError("merge_outcome_unknown", "an in-flight merge cannot be reconciled yet (remote "
                             "unreachable); nothing merges until it can", {"unknown": unknown})
        return decisions

    def _reconcile_decision(self, cfg: dict[str, Any], e: dict[str, Any]) -> dict[str, Any]:
        """Decide an in-flight merge from authoritative state alone. Writes nothing."""
        out: dict[str, Any] = {"entry": e["entry_id"], "unit": e["unit"], "acceptedHead": e["accepted_head"],
                               "expectedBase": e["expected_base"]}
        try:
            base_head = self._base_head(cfg)
            if cfg["mode"] == "gh":
                st = self._unit_state(cfg, e)
                if st["state"] == "MERGED" and st["mergeCommit"]:
                    if self.git.has_commit(st["mergeCommit"]) and self.git.is_ancestor(st["mergeCommit"], base_head):
                        return {**out, **self._merged_facts(e, st["mergeCommit"]), "resolution": "merged"}
                    return {**out, "resolution": "failed", "reason": "merged_not_on_base", "mergeSha": st["mergeCommit"]}
                if st["state"] == "OPEN":
                    return {**out, "resolution": "requeued", "reason": "remote merge never landed"}
                return {**out, "resolution": "failed", "reason": "closed_unmerged"}
            head = e["accepted_head"]
            if head and self.git.has_commit(head) and self.git.is_ancestor(head, base_head):
                merge_sha = self._find_merge(e, base_head)
                return {**out, **self._merged_facts(e, merge_sha), "resolution": "merged"}
            return {**out, "resolution": "requeued", "reason": "remote merge never landed"}
        except Offline as exc:
            return {**out, "resolution": "unknown", "reason": exc.message}

    def _find_merge(self, e: dict[str, Any], base_head: str) -> str:
        """The first-parent commit on BASE whose other parent is the merged head (git lane)."""
        span = f"{e['expected_base']}..{base_head}" if e["expected_base"] else base_head
        for line in self.git.out("rev-list", "--first-parent", "--parents", span).splitlines():
            shas = line.split()
            if e["accepted_head"] in shas[2:]:
                return shas[0]
        return base_head

    def _merged_facts(self, e: dict[str, Any], merge_sha: str) -> dict[str, Any]:
        parents = self.git.parents(merge_sha)
        tree = self.git.tree(merge_sha)
        exact = bool(parents[:1] == [e["expected_base"]] and tree == e["tested_tree"])
        return {"mergeSha": merge_sha, "mergedTree": tree, "parents": parents, "treeMatchesTested": exact}

    def _apply_reconcile(self, conn: sqlite3.Connection, cfg: dict[str, Any], d: dict[str, Any],
                         lease: dict[str, Any]) -> None:
        now = self.clock()
        if d["resolution"] == "merged":
            conn.execute("UPDATE mq_entries SET state = ?, merge_sha = ?, merged_tree = ?, tree_matches_tested = ?, "
                         "updated_at = ? WHERE entry_id = ? AND state = ?",
                         (MERGED, d["mergeSha"], d["mergedTree"], int(d["treeMatchesTested"]), now, d["entry"], MERGING))
        elif d["resolution"] == "requeued":
            conn.execute("UPDATE mq_entries SET state = ?, updated_at = ? WHERE entry_id = ? AND state = ?",
                         (QUEUED, now, d["entry"], MERGING))
        elif d["resolution"] == "failed":
            conn.execute("UPDATE mq_entries SET state = ?, reason = ?, updated_at = ? WHERE entry_id = ? AND state = ?",
                         (FAILED, d["reason"], now, d["entry"], MERGING))
        self._receipt(conn, cfg["repo"], cfg["base"], "reconciled", d, d["entry"], lease)

    def plan(self, token: str, *, gate_cmd: str | None = None, gate_timeout: float = 1800.0) -> dict[str, Any]:
        """Test the prefix: BASE + each queued entry in arrival order, as in-memory merges (#590).

        Each entry records the BASE tree it expects to merge onto, the merge tree it was tested
        as, and the head it accepted. With `--gate-cmd`, the command runs in a detached checkout
        of each prefix commit, and a failure FAILS that entry, which freezes the train behind it.
        """
        self.settle_in_flight(token)
        cfg, _lease = self._owner(token)
        repo, base = cfg["repo"], cfg["base"]
        line = self._line(repo, base)
        self._guard_head(line)
        base_head = self._base_head(cfg)
        prev = base_head
        decisions: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        for e in line:
            if e["state"] != QUEUED:
                break
            st = self._unit_state(cfg, e)
            if st["state"] == "MERGED":
                decisions.append(("fail", e, {"reason": "merged_outside_queue", "mergeCommit": st["mergeCommit"]}))
                break
            why = self._bounce_reason(cfg, e, st)
            accepted, how = (None, why) if why else self._fresh_head(e, st["head"])
            if accepted is None:
                decisions.append(("bounce", e, {"reason": how, "head": st["reported"], "reviewedSha": e["reviewed_sha"]}))
                continue
            pred = self._predict(e, prev, accepted)
            if not pred["clean"]:
                decisions.append(("fail", e, {"reason": "conflict", "conflicts": pred["conflicts"]}))
                break
            commit = self.git.commit_tree(pred["tree_oid"], [prev, accepted],
                                          f"merge-queue prefix: {e['unit']} onto {base}", env=PREFIX_IDENTITY,
                                          sign=False)
            self.git.keep(f"entry/{e['entry_id']}/prefix", commit)
            tested = {"acceptedHead": accepted, "how": how, "testedBaseTree": self.git.tree(prev),
                      "testedTree": pred["tree_oid"], "prefixCommit": commit, "gate": None}
            if gate_cmd:
                gate = self._run_gate(gate_cmd, commit, e, gate_timeout)
                tested["gate"] = gate
                if gate["exit"] != 0:
                    decisions.append(("fail", e, {"reason": "gate_failed", **tested}))
                    break
            decisions.append(("tested", e, tested))
            prev = commit
        now = self.clock()
        out = []
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            self._clear_tested(conn, repo, base)
            for kind, e, body in decisions:
                cur = conn.execute("SELECT state FROM mq_entries WHERE entry_id = ?", (e["entry_id"],)).fetchone()
                if cur["state"] != QUEUED:
                    raise QueueError("queue_changed", f"{e['entry_id']} changed state while planning; plan again")
                if kind == "tested":
                    conn.execute("UPDATE mq_entries SET accepted_head = ?, tested_base_tree = ?, tested_tree = ?, "
                                 "prefix_commit = ?, gate_json = ?, updated_at = ? WHERE entry_id = ?",
                                 (body["acceptedHead"], body["testedBaseTree"], body["testedTree"], body["prefixCommit"],
                                  json.dumps(body["gate"]), now, e["entry_id"]))
                    self._receipt(conn, repo, base, "tested", {"baseHead": base_head, **body}, e["entry_id"], lease)
                elif kind == "bounce":
                    conn.execute("UPDATE mq_entries SET state = ?, reason = ?, updated_at = ? WHERE entry_id = ?",
                                 (BOUNCED, body["reason"], now, e["entry_id"]))
                    self._receipt(conn, repo, base, "returned_to_review", body, e["entry_id"], lease)
                else:
                    conn.execute("UPDATE mq_entries SET state = ?, reason = ?, updated_at = ? WHERE entry_id = ?",
                                 (FAILED, body["reason"], now, e["entry_id"]))
                    self._receipt(conn, repo, base, "failed", {**body, "frozen": True}, e["entry_id"], lease)
                out.append({"entry": e["entry_id"], "unit": e["unit"], "result": kind, **body})
        return {"ok": True, "baseHead": base_head, "planned": out}

    def _predict(self, e: dict[str, Any], base: str, head: str) -> dict[str, Any]:
        """#590's in-memory merge (`git merge-tree --write-tree`): HEAD, index and worktree untouched."""
        try:
            return diff_scope.predict_merge(str(self.repo_dir), base, head)
        except diff_scope.ScopeError as exc:
            raise QueueError("predict_failed", f"could not predict the merge of {e['entry_id']}: {exc}") from exc

    def _run_gate(self, gate_cmd: str, commit: str, e: dict[str, Any], timeout: float) -> dict[str, Any]:
        tmp = tempfile.mkdtemp(prefix="mq-gate-")
        checkout = Path(tmp) / "prefix"
        try:
            self.git.run("worktree", "add", "--detach", str(checkout), commit)
            env = {**self.env, "MQ_ENTRY": e["entry_id"], "MQ_UNIT": e["unit"], "MQ_PREFIX_COMMIT": commit}
            # Its own session, so a timeout kills everything the gate started: a grandchild left
            # holding the output pipe would otherwise stretch the timeout to its own lifetime.
            proc = subprocess.Popen(["/bin/sh", "-c", gate_cmd], cwd=checkout, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, start_new_session=True)
            try:
                out, _ = proc.communicate(timeout=timeout)
                code, tail = proc.returncode, (out or "")[-500:]
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                code, tail = 124, f"gate timed out after {timeout}s"
            return {"cmd": gate_cmd, "exit": code, "tail": tail, "commit": commit}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self.git.run("worktree", "prune", check=False)

    @staticmethod
    def plan_passed(e: dict[str, Any], gate_cmd: str | None) -> bool:
        """Whether the entry's saved plan covers this request: a tested merge tree and, when a gate
        is asked for, THAT gate passed on THAT prefix commit (PR #647: a saved plan that ran no
        gate, or another one, let a requested gate be skipped)."""
        if not e.get("tested_tree"):
            return False
        if gate_cmd is None:
            return True
        try:
            gate = json.loads(e.get("gate_json") or "null")
        except ValueError:
            return False
        return (isinstance(gate, dict) and gate.get("cmd") == gate_cmd and gate.get("exit") == 0
                and bool(e.get("prefix_commit")) and gate.get("commit") == e.get("prefix_commit"))

    def merge(self, token: str, *, entry_id: str | None = None, delete_branch: bool = True,
              require_gate: str | None = None) -> dict[str, Any]:
        """Merge the head of the train, once, behind every guard (merge-serialization.md steps 2-4).

        `require_gate` refuses a head whose saved plan did not pass exactly that gate command.
        """
        self.settle_in_flight(token)
        cfg, lease = self._owner(token)
        repo, base = cfg["repo"], cfg["base"]
        head = self._guard_head(self._line(repo, base), entry_id)
        if head is None:
            return {"ok": True, "result": "empty"}
        if not head["tested_tree"]:
            raise QueueError("untested", f"{head['entry_id']} has no tested merge tree: run plan first",
                             {"entry": head["entry_id"]})
        if not self.plan_passed(head, require_gate):
            raise QueueError("gate_not_run", f"{head['entry_id']}'s saved plan did not pass the required gate "
                             f"{require_gate!r}: run plan --gate-cmd with it first",
                             {"entry": head["entry_id"], "required": require_gate,
                              "saved": json.loads(head["gate_json"] or "null")})
        info = {"entry": head["entry_id"], "unit": head["unit"], "pr": head["pr"], "epoch": lease["epoch"],
                "pid": os.getpid()}
        self._boundary("lease_checked", info)
        lock = self._lock(repo, base)
        try:
            if not lock.acquire(30.0):
                raise QueueError("merge_in_flight", "another process holds the merge boundary")
            return self._merge_locked(token, cfg, head, lock, info, delete_branch)
        finally:
            lock.release()

    def _merge_locked(self, token: str, cfg: dict[str, Any], e: dict[str, Any], lock: EffectLock,
                      info: dict[str, Any], delete_branch: bool) -> dict[str, Any]:
        repo, base = cfg["repo"], cfg["base"]
        # Revalidate against authoritative state (#599): the tested prefix and both expected heads.
        try:
            base_head = self._base_head(cfg)
            st = self._unit_state(cfg, e)
        except Offline as exc:
            self._record(token, cfg, e, "offline", {"step": "revalidate", "message": exc.message})
            raise
        if self.git.tree(base_head) != e["tested_base_tree"]:
            return self._retest(token, cfg, e, "base_moved", {"baseHead": base_head})
        if st["state"] == "MERGED":
            return self._fail(token, cfg, e, "merged_outside_queue", {"mergeCommit": st["mergeCommit"]})
        why = self._bounce_reason(cfg, e, st)
        accepted, how = (None, why) if why else self._fresh_head(e, st["head"])
        if accepted is None:
            return self._bounce(token, cfg, e, how, {"head": st["reported"], "reviewedSha": e["reviewed_sha"]})
        pred = self._predict(e, base_head, accepted)
        if not pred["clean"] or pred["tree_oid"] != e["tested_tree"]:
            return self._retest(token, cfg, e, "merge_tree_changed",
                                {"baseHead": base_head, "acceptedHead": accepted, "tree": pred["tree_oid"]})
        local_merge = None
        if cfg["mode"] == "git":
            # Built before the intent is recorded: a failure here leaves nothing in flight. Its
            # tree is the TESTED tree by construction, so the git lane merges exactly what was tested.
            local_merge = self.git.commit_tree(
                e["tested_tree"], [base_head, accepted],
                f"Merge {e['branch']} into {base} (merge queue {e['entry_id']}, unit {e['unit']})")
            self.git.keep(f"entry/{e['entry_id']}/merge", local_merge)
        # The fenced compare-and-set: the merge intent is recorded under THIS conductor's token,
        # inside the effect lock. A conductor taken over since its lease check stops here.
        now = self.clock()
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            # The compare-and-set binds the plan validated above: the tested tree and the gate record
            # (a concurrent re-plan by this owner changes one of them, and the write is refused).
            cur = conn.execute("UPDATE mq_entries SET state = ?, accepted_head = ?, expected_base = ?, merging_epoch = ?, "
                               "merging_pid = ?, updated_at = ? WHERE entry_id = ? AND state = ? AND tested_tree = ? "
                               "AND COALESCE(gate_json, '') = ?",
                               (MERGING, accepted, base_head, lease["epoch"], os.getpid(), now, e["entry_id"], QUEUED,
                                e["tested_tree"], e["gate_json"] or ""))
            if cur.rowcount != 1:
                raise QueueError("queue_changed", f"{e['entry_id']} is no longer queued as it was validated")
            self._receipt(conn, repo, base, "merge_intent", {"acceptedHead": accepted, "how": how, "expectedBase": base_head,
                                                             "testedTree": e["tested_tree"], "mode": cfg["mode"],
                                                             "localMerge": local_merge, "repository": cfg["repo"]},
                          e["entry_id"], lease)
        e = {**e, "state": MERGING, "accepted_head": accepted, "expected_base": base_head}
        try:
            self._egress(cfg, e)
        except egress.EgressError as exc:
            with self.store.tx() as conn:
                lease = self._fence(conn, token)
                conn.execute("UPDATE mq_entries SET state = ?, updated_at = ? WHERE entry_id = ? AND state = ?",
                             (QUEUED, self.clock(), e["entry_id"], MERGING))
                self._receipt(conn, repo, base, "egress_refused", {"message": str(exc)}, e["entry_id"], lease)
            raise QueueError("egress_failed", f"the egress receipt could not be written, so nothing was sent: {exc}") from exc
        self._boundary("intent_recorded", info)
        sent, detail = self._send(cfg, e, lock, delete_branch, local_merge)
        if sent:
            self._boundary("remote_merged", info)
        decision = self._reconcile_decision(cfg, e)
        if decision["resolution"] == "requeued":
            # The remote refused or never applied it. Re-read why before deciding the train's fate.
            try:
                decision = self._refusal(cfg, e, detail)
            except Offline as exc:
                decision = {**decision, "resolution": "unknown", "reason": exc.message}
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            self._apply_reconcile(conn, cfg, {**decision, "send": detail}, lease)
            if decision["resolution"] in ("requeued", "failed"):
                self._clear_tested(conn, repo, base, 0 if decision["resolution"] == "requeued" else e["seq"])
        if decision["resolution"] == "merged":
            self._boundary("merged_recorded", info)
            return {"ok": True, "result": "merged", "entry": e["entry_id"], "unit": e["unit"], **decision,
                    "noGh": cfg["mode"] == "git"}
        if decision["resolution"] == "unknown":
            raise QueueError("merge_outcome_unknown", "the merge was sent but its outcome cannot be read yet; it is "
                             "reconciled before anything else merges", decision)
        raise QueueError("merge_refused" if decision["resolution"] == "failed" else "retest_required",
                         f"{e['entry_id']} did not merge: {decision.get('reason')}", decision)

    def _refusal(self, cfg: dict[str, Any], e: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
        """A send that did not land: a moved head or BASE returns to plan; anything else freezes."""
        base_head = self._base_head(cfg)
        moved_base = base_head != e["expected_base"]
        moved_head = False
        if cfg["mode"] == "gh":
            moved_head = self._unit_state(cfg, e)["reported"] != e["accepted_head"]
        out = {"entry": e["entry_id"], "unit": e["unit"], "acceptedHead": e["accepted_head"], "expectedBase": e["expected_base"]}
        if moved_base or moved_head:
            return {**out, "resolution": "requeued", "reason": "base_moved" if moved_base else "head_moved"}
        return {**out, "resolution": "failed", "reason": "merge_refused", "stderr": detail.get("stderr", "")[-300:]}

    def _send(self, cfg: dict[str, Any], e: dict[str, Any], lock: EffectLock, delete_branch: bool,
              local_merge: str | None) -> tuple[bool, dict[str, Any]]:
        """The remote merge, with the effect lock inherited by the child that performs it."""
        fds = (lock.fd,) if lock.fd is not None else ()
        remote = self._bound_remote(cfg)  # re-proved at the send: the push URL is read here
        if cfg["mode"] == "gh":
            try:
                proc = self.gh.pr_merge(cfg["repo"], e["pr"], e["accepted_head"], delete_branch, fds)
            except Offline as exc:  # never sent, or sent with no answer: reconcile decides which
                return False, {"exit": None, "stderr": exc.message}
        else:
            proc = self.git.run("push", "--porcelain", f"--force-with-lease=refs/heads/{cfg['base']}:{e['expected_base']}",
                                remote, f"{local_merge}:refs/heads/{cfg['base']}", check=False, pass_fds=fds)
        return proc.returncode == 0, {"exit": proc.returncode, "stderr": (proc.stderr or "")[-300:]}

    def _egress(self, cfg: dict[str, Any], e: dict[str, Any]) -> None:
        """egress.py's fail-closed receipt, appended BEFORE the send (#368)."""
        explicit = self.env.get(egress.PRIMARY_LEDGER_ENV) or self.env.get(egress.LEDGER_ENV)
        path = Path(explicit) if explicit else self.repo_dir / egress.DEFAULT_LEDGER
        body = json.dumps({"repo": cfg["repo"], "base": cfg["base"], "entry": e["entry_id"], "pr": e["pr"],
                           "head": e["accepted_head"], "expectedBase": e["expected_base"]}, sort_keys=True).encode()
        egress.write_receipt(path, "merge-queue", cfg["host"], "pr-merge" if cfg["mode"] == "gh" else "base-push",
                             cfg["consent"], nbytes=len(body), payload_sha256=hashlib.sha256(body).hexdigest())

    def _record(self, token: str, cfg: dict[str, Any], e: dict[str, Any], kind: str, body: dict[str, Any]) -> None:
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            self._receipt(conn, cfg["repo"], cfg["base"], kind, body, e["entry_id"], lease)

    def _retest(self, token: str, cfg: dict[str, Any], e: dict[str, Any], reason: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            self._clear_tested(conn, cfg["repo"], cfg["base"])
            self._receipt(conn, cfg["repo"], cfg["base"], "retest_required", {"reason": reason, **body}, e["entry_id"], lease)
        raise QueueError("retest_required", f"{e['entry_id']}: {reason}; the tested prefix is stale, plan again",
                         {"entry": e["entry_id"], "reason": reason, **body})

    def _bounce(self, token: str, cfg: dict[str, Any], e: dict[str, Any], reason: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            conn.execute("UPDATE mq_entries SET state = ?, reason = ?, updated_at = ? WHERE entry_id = ? AND state = ?",
                         (BOUNCED, reason, self.clock(), e["entry_id"], QUEUED))
            self._clear_tested(conn, cfg["repo"], cfg["base"])
            self._receipt(conn, cfg["repo"], cfg["base"], "returned_to_review", {"reason": reason, **body}, e["entry_id"], lease)
        return {"ok": False, "result": "returned_to_review", "entry": e["entry_id"], "unit": e["unit"], "reason": reason, **body}

    def _fail(self, token: str, cfg: dict[str, Any], e: dict[str, Any], reason: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            conn.execute("UPDATE mq_entries SET state = ?, reason = ?, updated_at = ? WHERE entry_id = ? AND state = ?",
                         (FAILED, reason, self.clock(), e["entry_id"], QUEUED))
            self._clear_tested(conn, cfg["repo"], cfg["base"], e["seq"])
            self._receipt(conn, cfg["repo"], cfg["base"], "failed", {"reason": reason, "frozen": True, **body},
                          e["entry_id"], lease)
        raise QueueError("merge_refused", f"{e['entry_id']}: {reason}; the train is frozen behind it",
                         {"entry": e["entry_id"], "reason": reason, **body})

    def ack(self, token: str, entry_id: str, *, note: str | None = None, accept_untested_tree: bool = False) -> dict[str, Any]:
        """Acknowledge a verified merge (the conductor has ledgered it): merged -> landed."""
        cfg, _lease = self._owner(token)
        rows = self.store.read("SELECT * FROM mq_entries WHERE entry_id = ? AND repo = ? AND base = ?",
                               (entry_id, cfg["repo"], cfg["base"]))
        if not rows:
            raise QueueError("entry_not_found", f"no entry {entry_id!r} in this queue", exit_code=EXIT_USAGE)
        e = rows[0]
        if e["state"] == LANDED:
            return {"ok": True, "duplicate": True, "entry": entry_id, "mergeSha": e["merge_sha"]}
        if e["state"] != MERGED:
            raise QueueError("not_merged", f"{entry_id} is {e['state']!r}, not merged", exit_code=EXIT_USAGE)
        if not e["tree_matches_tested"] and not accept_untested_tree:
            raise QueueError("untested_tree_merged", f"{entry_id} merged a tree other than the tested one (BASE moved "
                             "under the remote merge); ack with --accept-untested-tree once that content is checked",
                             {"entry": entry_id, "mergeSha": e["merge_sha"], "mergedTree": e["merged_tree"],
                              "testedTree": e["tested_tree"]})
        base_head = self._base_head(cfg)
        if not self.git.is_ancestor(e["merge_sha"], base_head):
            raise QueueError("merge_not_on_base", f"{e['merge_sha']} is not an ancestor of {cfg['base']} "
                             f"({base_head}); BASE was rewritten", {"entry": entry_id})
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            cur = conn.execute("UPDATE mq_entries SET state = ?, updated_at = ? WHERE entry_id = ? AND state = ?",
                               (LANDED, self.clock(), entry_id, MERGED))
            if cur.rowcount != 1:
                raise QueueError("queue_changed", f"{entry_id} changed state while acknowledging")
            body = {"mergeSha": e["merge_sha"], "baseHead": base_head, "note": note,
                    "acceptedUntestedTree": bool(accept_untested_tree and not e["tree_matches_tested"]),
                    "promotion": f"{cfg['base']}->{cfg['default_branch']} is a human gate, not performed here"}
            if cfg["mode"] == "git":
                body["ledger"] = "no-gh: local-merge"
            self._receipt(conn, cfg["repo"], cfg["base"], "acknowledged", body, entry_id, lease)
        return {"ok": True, "entry": entry_id, "landed": True, **body}

    def resolve(self, token: str, entry_id: str, *, action: str, reason: str) -> dict[str, Any]:
        """The conductor's recorded decision on the failed entry the train is frozen behind."""
        if action not in RESOLVE_ACTIONS:
            raise QueueError("usage", f"--action must be one of {sorted(RESOLVE_ACTIONS)}", exit_code=EXIT_USAGE)
        if not reason or not reason.strip():
            raise QueueError("usage", "--reason is recorded with the decision", exit_code=EXIT_USAGE)
        with self.store.tx() as conn:
            lease = self._fence(conn, token)
            row = conn.execute("SELECT * FROM mq_entries WHERE entry_id = ? AND repo = ? AND base = ?",
                               (entry_id, lease["repo"], lease["base"])).fetchone()
            if row is None or row["state"] != FAILED:
                raise QueueError("not_failed", f"{entry_id} is not a failed entry", exit_code=EXIT_USAGE)
            conn.execute("UPDATE mq_entries SET state = ?, reason = ?, updated_at = ? WHERE entry_id = ?",
                         (RESOLVE_ACTIONS[action], f"{row['reason']} -> {action}: {reason}", self.clock(), entry_id))
            self._clear_tested(conn, lease["repo"], lease["base"])
            if action == "requeue":
                conn.execute("UPDATE mq_entries SET tested_base_tree = NULL, tested_tree = NULL, prefix_commit = NULL "
                             "WHERE entry_id = ?", (entry_id,))
            self._receipt(conn, lease["repo"], lease["base"], "resolved",
                          {"action": action, "reason": reason, "was": row["reason"]}, entry_id, lease)
        return {"ok": True, "entry": entry_id, "state": RESOLVE_ACTIONS[action]}

    # --- read-only views ---------------------------------------------------------------------
    @staticmethod
    def _entry_view(e: dict[str, Any]) -> dict[str, Any]:
        keys = ("entry_id", "seq", "state", "run_id", "unit", "pr", "branch", "reviewed_sha", "reviewed_tree",
                "accepted_head", "expected_base", "tested_base_tree", "tested_tree", "prefix_commit", "merge_sha",
                "merged_tree", "tree_matches_tested", "reason")
        return {k: e.get(k) for k in keys}

    def status(self, repo: str, base: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            cfg = self._config(conn, repo, base)
            lease = conn.execute("SELECT holder, epoch, expires_at, released_at FROM mq_leases WHERE repo = ? AND base = ?",
                                 (repo, base)).fetchone()
        line = self._line(repo, base)
        frozen = next((e for e in line if e["state"] == FAILED), None)
        now = self.clock()
        return {
            "ok": True, "repo": repo, "base": base, "mode": cfg["mode"],
            "lease": ({**dict(lease), "live": lease["released_at"] is None and lease["expires_at"] > now} if lease else None),
            "line": [self._entry_view(e) for e in line],
            "frozen": {"entry": frozen["entry_id"], "reason": frozen["reason"]} if frozen else None,
            "ackOwed": [e["entry_id"] for e in line if e["state"] == MERGED],
            "inFlight": [e["entry_id"] for e in line if e["state"] == MERGING],
            "promotion": {"from": base, "to": cfg["default_branch"], "by": "human", "automated": False},
            "all": [self._entry_view(e) for e in self.store.read(
                "SELECT * FROM mq_entries WHERE repo = ? AND base = ? ORDER BY seq ASC", (repo, base))],
        }

    def receipts(self, repo: str, base: str, entry_id: str | None = None) -> dict[str, Any]:
        q, params = "SELECT * FROM mq_receipts WHERE repo = ? AND base = ?", [repo, base]
        if entry_id:
            q += " AND entry_id = ?"
            params.append(entry_id)
        rows = self.store.read(q + " ORDER BY id ASC", tuple(params))
        return {"ok": True, "receipts": [{**{k: r[k] for k in ("id", "entry_id", "kind", "epoch", "holder", "created_at")},
                                          "body": json.loads(r["body_json"])} for r in rows]}

    def drain(self, *, repo: str, base: str, holder: str, ttl: float = DEFAULT_TTL, takeover: bool = False,
              wait: float = 10.0, gate_cmd: str | None = None, ack: bool = False, max_steps: int = 100,
              delete_branch: bool = True, gate_timeout: float = 1800.0) -> dict[str, Any]:
        """acquire -> (plan -> merge -> ack)* -> release: one conductor turn over the whole train."""
        acq = self.acquire(repo=repo, base=base, holder=holder, ttl=ttl, takeover=takeover, wait=wait)
        token, steps = acq["token"], []
        stop: QueueError | None = None
        try:
            for _ in range(max_steps):
                line = self._line(repo, base)
                if not line:
                    break
                head = line[0]
                try:
                    if head["state"] == MERGED and ack:
                        steps.append({"ack": self.ack(token, head["entry_id"], note=f"drain by {holder}")})
                    elif head["state"] == QUEUED and not self.plan_passed(head, gate_cmd):
                        # Re-plan unless the saved plan passed THIS gate on this prefix (PR #647).
                        steps.append({"plan": self.plan(token, gate_cmd=gate_cmd, gate_timeout=gate_timeout)})
                    else:
                        steps.append({"merge": self.merge(token, entry_id=head["entry_id"], delete_branch=delete_branch,
                                                          require_gate=gate_cmd)})
                except QueueError as exc:
                    if exc.code == "retest_required":
                        steps.append({"retest": exc.as_json()})
                        continue
                    raise
            else:
                stop = QueueError("max_steps", f"stopped after {max_steps} steps with the train not empty")
        except QueueError as exc:
            stop = exc
        if stop is None or stop.exit_code != EXIT_FENCED:
            with contextlib.suppress(QueueError):
                self.release(token)
        result = {"ok": stop is None, "epoch": acq["epoch"], "reconciled": acq["reconciled"], "steps": steps,
                  "promotion": {"from": base, "by": "human", "automated": False}}
        if stop is not None:
            raise QueueError(stop.code, stop.message, {**stop.data, "drain": result}, exit_code=stop.exit_code)
        return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="merge_queue.py",
        description="The persisted, fenced single-conductor merge queue (#599; merge-serialization.md).",
        epilog="exit 0 ok / 1 blocked / 2 usage or refused input / 3 not the owner (fenced, lease held)",
    )
    p.add_argument("--db", default=None, help="queue store (default $OPEN_FLEET_MERGE_QUEUE_DB, "
                   "$OPEN_FLEET_STATE_DIR/merge-queue.db, or ~/.open-fleet/state/merge-queue.db)")
    p.add_argument("--repo-dir", default=".", help="the conductor's clone (default: cwd)")
    p.add_argument("--repo", default=None, help="repository identity (default: the origin URL as host/owner/name)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="open the queue for one BASE (idempotent)")
    s.add_argument("--base", required=True)
    s.add_argument("--default", required=True, help="the default branch: never a merge target here")
    s.add_argument("--consent", required=True, help="the standing grant each merge's egress receipt cites")
    s.add_argument("--mode", choices=MODES, default="gh", help="gh (default) or git, the no-gh lane")
    s.add_argument("--remote", default="origin")
    s.add_argument("--host", default=None, help="egress host (default github.com, or the remote's host)")

    for name, helptext in (("acquire", "become the conductor: reconcile in-flight merges, then take the lease"),
                           ("drain", "acquire, then plan/merge/ack the whole train, then release")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--base", required=True)
        s.add_argument("--holder", required=True, help="the conductor's handle")
        s.add_argument("--ttl", type=float, default=DEFAULT_TTL, help="lease seconds, renewed by every write")
        s.add_argument("--takeover", action="store_true", help="fence a live holder")
        s.add_argument("--wait", type=float, default=0.0 if name == "acquire" else 10.0,
                       help="seconds to wait for the merge boundary")
        if name == "drain":
            s.add_argument("--gate-cmd", default=None, help="shell command run in each prefix checkout; a saved "
                           "plan is reused only when it passed exactly this command")
            s.add_argument("--gate-timeout", type=float, default=1800.0)
            s.add_argument("--ack", action="store_true", help="acknowledge each verified merge")
            s.add_argument("--max-steps", type=int, default=100)
            s.add_argument("--keep-branch", action="store_true", help="gh lane: do not pass --delete-branch")

    s = sub.add_parser("release", help="give the lease up")
    s.add_argument("--token", required=True)
    s = sub.add_parser("enqueue", help="board one merge_ready payload (duplicates are no-ops)")
    s.add_argument("--token", required=True)
    s.add_argument("--payload", required=True, help="the merge_ready payload JSON")
    s.add_argument("--run", default=None)
    s.add_argument("--delivery", default=None, help="the delivery or message id, recorded")
    s = sub.add_parser("plan", help="test the prefix: BASE + each queued entry in arrival order")
    s.add_argument("--token", required=True)
    s.add_argument("--gate-cmd", default=None)
    s.add_argument("--gate-timeout", type=float, default=1800.0)
    s = sub.add_parser("merge", help="merge the head of the train behind every guard")
    s.add_argument("--token", required=True)
    s.add_argument("--entry", default=None)
    s.add_argument("--keep-branch", action="store_true")
    s.add_argument("--require-gate", default=None, help="refuse unless the saved plan passed exactly this gate")
    s = sub.add_parser("ack", help="acknowledge a verified merge (merged -> landed)")
    s.add_argument("--token", required=True)
    s.add_argument("--entry", required=True)
    s.add_argument("--note", default=None)
    s.add_argument("--accept-untested-tree", action="store_true")
    s = sub.add_parser("resolve", help="decide the failed entry the train is frozen behind")
    s.add_argument("--token", required=True)
    s.add_argument("--entry", required=True)
    s.add_argument("--action", required=True, choices=sorted(RESOLVE_ACTIONS))
    s.add_argument("--reason", required=True)
    s = sub.add_parser("reconcile", help="settle an in-flight merge an earlier attempt left behind")
    s.add_argument("--token", required=True)
    for name in ("status", "receipts"):
        s = sub.add_parser(name, help="read-only")
        s.add_argument("--base", required=True)
        if name == "receipts":
            s.add_argument("--entry", default=None)
    return p


def run(args: argparse.Namespace, mq: MergeQueue) -> dict[str, Any]:
    cmd = args.command
    if cmd in ("init", "acquire", "drain", "status", "receipts"):
        repo = args.repo or mq.default_repo(getattr(args, "remote", "origin"))
    if cmd == "init":
        return mq.init(repo=repo, base=args.base, default=args.default, consent=args.consent, mode=args.mode,
                       remote=args.remote, host=args.host)
    if cmd == "acquire":
        return mq.acquire(repo=repo, base=args.base, holder=args.holder, ttl=args.ttl, takeover=args.takeover,
                          wait=args.wait)
    if cmd == "drain":
        return mq.drain(repo=repo, base=args.base, holder=args.holder, ttl=args.ttl, takeover=args.takeover,
                        wait=args.wait, gate_cmd=args.gate_cmd, ack=args.ack, max_steps=args.max_steps,
                        delete_branch=not args.keep_branch, gate_timeout=args.gate_timeout)
    if cmd == "status":
        return mq.status(repo, args.base)
    if cmd == "receipts":
        return mq.receipts(repo, args.base, args.entry)
    if cmd == "release":
        return mq.release(args.token)
    if cmd == "enqueue":
        return mq.enqueue(args.token, args.payload, run=args.run, delivery=args.delivery)
    if cmd == "plan":
        return mq.plan(args.token, gate_cmd=args.gate_cmd, gate_timeout=args.gate_timeout)
    if cmd == "merge":
        return mq.merge(args.token, entry_id=args.entry, delete_branch=not args.keep_branch,
                        require_gate=args.require_gate)
    if cmd == "ack":
        return mq.ack(args.token, args.entry, note=args.note, accept_untested_tree=args.accept_untested_tree)
    if cmd == "resolve":
        return mq.resolve(args.token, args.entry, action=args.action, reason=args.reason)
    return {"ok": True, "reconciled": mq.settle_in_flight(args.token)}


def main(argv: list[str] | None = None, mq: MergeQueue | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        mq = mq or MergeQueue(args.db, args.repo_dir)
        out = run(args, mq)
    except QueueError as exc:
        print(json.dumps(exc.as_json(), indent=2, sort_keys=True, default=str))
        return exc.exit_code
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return EXIT_OK if out.get("ok", True) else EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
