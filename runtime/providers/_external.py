#!/usr/bin/env python3
"""_external.py — shared plumbing for the 12 external orchestrator adapters (#582-#584, #588, #589).

Private helpers used by every non-Orca, non-POSIX adapter so they all fail the same way (#591 audit):

  - upstream transport errors (missing binary, timeout, HTTP status, unreachable socket,
    unparseable output) become `ProviderError` (`ok:false`), never a fabricated success;
  - dispatch rows are read back through one place that raises `dispatch_not_found`;
  - fence verbs go through `fence_state` and land on the POSIX state names;
  - worker-show / worker-list receipts use `normalize_show`.
"""
from __future__ import annotations

import contextvars
import functools
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import re
from typing import Callable

from .base import ProviderError, fence_state, normalize_show, parse_json_strict
from .local_state import LocalStateStore
from .posix import HOOK_ARTIFACTS, git_location, gitexec

def _git_launch(argv: list[str], env: dict[str, str] | None, cwd: str | None = None) -> tuple[list[str], dict[str, str] | None, dict[str, Any]]:
    """`(argv, env, stdin kwargs)` to launch one upstream command. A `git` an adapter runs is
    COORDINATOR-side git over a worker's worktree — the shared `.git/config`, its `.gitattributes`,
    the same-uid `~/.gitconfig` — so it launches the way posix.py launches one (W4-01 sweep):
    gitexec.py's absolute git and floor, stdin closed, and EVERY launch carries the blanks for every
    driver the config declares where it runs (`-C`, `--git-dir`, or the launch cwd): no subcommand
    allowlist a future `commit`/`restore`/`rebase` could fall outside (re-attack P3). Anything that
    is not git passes as is. GitAbsent (git missing at import) and DriverQueryFailed (an unreadable
    config) are OSErrors."""
    if not argv or argv[0] != "git":
        return argv, env, {}
    repo, git_dir = git_location(argv[1:], cwd)
    blanks = gitexec.driver_blanks(repo, git_dir=git_dir)
    return gitexec.argv(*argv[1:]), gitexec.env(env, blanks=blanks), {"stdin": subprocess.DEVNULL}

# Files `posix.install_worktree_hooks` writes into a worktree: dirt limited to these paths is
# ours, not the worker's, and never blocks a cleanup that has already preserved HEAD.
HOOK_ARTIFACT_PREFIXES = HOOK_ARTIFACTS

_SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

PLACEHOLDER_WORKTREES = frozenset({"", "new-child", "new-top-level", "current", "active"})


def real_worktree(path: Any) -> str | None:
    """Absolute path of an existing worktree directory, or None for placeholders/missing dirs."""
    if not isinstance(path, str) or path.strip() in PLACEHOLDER_WORKTREES:
        return None
    p = Path(path).expanduser()
    return str(p.resolve()) if p.is_dir() else None


def run_cli(argv: list[str], *, provider: str, timeout: float = 60, cwd: str | None = None) -> dict[str, Any]:
    """Run an upstream CLI; every failure mode is a ProviderError (never a silent success)."""
    try:
        launch, env, stdin = _git_launch(argv, None, cwd)
        proc = subprocess.run(
            launch, capture_output=True, text=True, check=False, timeout=timeout, cwd=cwd, env=env, **stdin
        )
    except FileNotFoundError as exc:
        raise ProviderError(f"{provider}_cli_missing", f"{argv[0]!r} not found on PATH", {"argv": argv}) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"{provider}_timeout", f"{argv[0]} timed out after {timeout}s", {"argv": argv}) from exc
    except OSError as exc:
        raise ProviderError(f"{provider}_cli_error", f"{argv[0]} could not be launched: {exc}", {"argv": argv}) from exc
    if proc.returncode != 0:
        raise ProviderError(
            f"{provider}_cli_error",
            (proc.stderr or "").strip() or f"{argv[0]} exited with {proc.returncode}",
            {"argv": argv, "returncode": proc.returncode},
        )
    out = proc.stdout or ""
    return {"stdout": out, "stderr": proc.stderr or "", "returncode": proc.returncode, "raw": out.strip()}


def http_json(
    base_url: str,
    method: str,
    path: str,
    body: Any = None,
    *,
    provider: str,
    timeout: float = 60,
    headers: dict[str, str] | None = None,
    raw_body: bytes | None = None,
    allow_empty: bool = False,
) -> Any:
    """One JSON HTTP exchange; HTTP errors keep their status, bad JSON is an error."""
    url = f"{base_url.rstrip('/')}{path}"
    data = raw_body if raw_body is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        parsed: Any = None
        try:
            parsed = json.loads(detail) if detail.strip() else None
        except json.JSONDecodeError:
            parsed = detail[:500]
        raise ProviderError(
            f"{provider}_http_error",
            f"{method} {path} -> HTTP {exc.code}",
            {"status": exc.code, "response": parsed, "path": path},
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ProviderError(f"{provider}_unreachable", f"{method} {url}: {exc}", {"path": path}) from exc
    return parse_json_strict(text, provider, allow_empty=allow_empty)


# Set once a `worker_start` call has handed anything to its runtime (#707 review): from then on a
# worker may exist, so a failure keeps the request's claim. A ContextVar, so concurrent calls on
# one adapter each read their own.
_REACHED_RUNTIME: contextvars.ContextVar[bool] = contextvars.ContextVar("reached_runtime", default=False)


def _marking_runtime_contact(runner):
    """`runner` that records the runtime was reached. A binary that was never found ran nothing."""

    @functools.wraps(runner)
    def marked(*args, **kwargs):
        before = _REACHED_RUNTIME.get()
        _REACHED_RUNTIME.set(True)
        try:
            return runner(*args, **kwargs)
        except FileNotFoundError:
            _REACHED_RUNTIME.set(before)
            raise

    marked._marks_runtime_contact = True
    return marked


def release_claim_on_failure(worker_start):
    """Decorator for an adapter's `worker_start`: a `--retry-request` claim this call took is
    released when the call fails BEFORE it reached the runtime, so a retry acts instead of reading
    the pending marker for PENDING_STALE_S (PR #707 review: a refusal before any launch left a
    long-running coordinator locked out of the id for ten minutes). Every adapter reaches its
    runtime through `self._runner`; once that is called a worker may have started (`ov sling` ran
    and its reply was lost or malformed), so the claim stays until the launch is checked or
    stopped, and a retry gets the pending marker, never a second worker (#707 review). Only this
    process's own pending claim is released; a completed row, or another caller's claim, never is."""

    @functools.wraps(worker_start)
    def wrapper(self, *args, **kwargs):
        retry_request = kwargs.get("retry_request")
        runner = getattr(self, "_runner", None)
        if callable(runner) and getattr(runner, "_marks_runtime_contact", False) is not True:
            self._runner = _marking_runtime_contact(runner)
        # An adapter with no `_runner` cannot say whether it launched: its claim is kept.
        token = _REACHED_RUNTIME.set(not callable(runner))
        try:
            return worker_start(self, *args, **kwargs)
        except BaseException:
            if retry_request and not _REACHED_RUNTIME.get():
                row = self.state.request_row(retry_request)
                if (row and row.get("state") == "pending" and not row.get("response_json")
                        and int(row.get("claim_pid") or 0) == os.getpid()):
                    self.state.release_request(retry_request)
            raise
        finally:
            _REACHED_RUNTIME.reset(token)

    return wrapper


class ExternalDispatchMixin:
    """Local dispatch bookkeeping shared by the external adapters (expects `self.state`, `self.name`)."""

    name: str
    state: Any

    def _dispatch_row(self, dispatch_id: str) -> Any:
        if not dispatch_id:
            raise ProviderError("dispatch_not_found", "no --dispatch id given")
        with self.state._connect() as conn:
            row = conn.execute(
                "SELECT * FROM dispatches WHERE dispatch_id = ? AND backend = ?",
                (dispatch_id, self.name),
            ).fetchone()
        if not row:
            raise ProviderError("dispatch_not_found", f"{self.name}: dispatch {dispatch_id!r} not found")
        return row

    @staticmethod
    def _effective(row: Any) -> dict[str, Any]:
        try:
            eff = json.loads(row["launch_effective"] or "{}")
        except (json.JSONDecodeError, TypeError):
            eff = {}
        return eff if isinstance(eff, dict) else {}

    def _record_dispatch(
        self,
        *,
        dispatch_id: str,
        task_id: str,
        run: str | None,
        worktree: str,
        agent: str,
        profile: str,
        handle: str,
        effective: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        now = time.time()
        with self.state._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dispatches(
                    dispatch_id, task_id, run_id, worktree, agent, profile,
                    terminal_handle, state, terminal_state, backend, launch_effective, session_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 'active', ?, ?, ?, ?, ?)
                """,
                (
                    dispatch_id, task_id, run or "default", worktree, agent, profile, handle,
                    self.name, json.dumps(effective), session_id or dispatch_id, now, now,
                ),
            )

    def _patch_dispatch(self, dispatch_id: str, *, worktree: str | None = None, effective: dict[str, Any] | None = None) -> None:
        row = self._dispatch_row(dispatch_id)
        eff = self._effective(row)
        if effective:
            eff.update(effective)
        with self.state._connect() as conn:
            conn.execute(
                "UPDATE dispatches SET worktree = ?, launch_effective = ?, updated_at = ? WHERE dispatch_id = ?",
                (worktree if worktree is not None else row["worktree"], json.dumps(eff), time.time(), dispatch_id),
            )

    def _fence_local(self, dispatch_id: str, verb: str) -> tuple[str, str]:
        new_state, term_state = fence_state(verb)
        with self.state._connect() as conn:
            conn.execute(
                "UPDATE dispatches SET state = ?, terminal_state = ?, updated_at = ? WHERE dispatch_id = ?",
                (new_state, term_state, time.time(), dispatch_id),
            )
        return new_state, term_state

    def _show_row(self, row: Any, *, state: str | None = None, raw: Any = None, worktree: str | None = None) -> dict[str, Any]:
        return normalize_show(
            row["dispatch_id"],
            state or row["state"],
            task_id=row["task_id"],
            terminal_state=row["terminal_state"],
            handle=row["terminal_handle"],
            worktree=worktree if worktree is not None else row["worktree"],
            raw=raw,
        )

    def _list_local(self, *, run: str | None = None, task: str | None = None, limit: int | None = None) -> dict[str, Any]:
        q = "SELECT * FROM dispatches WHERE backend = ?"
        params: list[Any] = [self.name]
        if run:
            q += " AND run_id = ?"
            params.append(run)
        if task:
            q += " AND task_id = ?"
            params.append(task)
        q += " ORDER BY created_at ASC"
        if limit:
            q += " LIMIT ?"
            params.append(int(limit))
        with self.state._connect() as conn:
            rows = conn.execute(q, params).fetchall()
        workers = [self._show_row(r)["worker"] for r in rows]
        return {"workers": workers, "scope": {"source": self.name}, "page": {"nextCursor": None}}


def env_flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def env_lookup(env: dict[str, str] | None, *names: str, default: str = "") -> str:
    source = os.environ if env is None else env
    for n in names:
        v = (source.get(n) or "").strip()
        if v:
            return v
    return default


# --------------------------------------------------------------------------------------
# CLI-text adapters (gastown / overstory / superset / t3code / worktrunk)
# --------------------------------------------------------------------------------------
def run_cli_text(
    argv: list[str],
    provider: str,
    *,
    timeout: int = 60,
    env: dict[str, str] | None = None,
    input: str | None = None,  # same name as subprocess.run's keyword
) -> str:
    """Run an upstream CLI; any launch failure, timeout, or non-zero exit is a ProviderError."""
    try:
        launch, env, stdin = _git_launch(argv, env)
        proc = subprocess.run(
            launch,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
            **({"input": input} if input is not None else stdin),
        )
    except FileNotFoundError as exc:
        raise ProviderError(f"{provider}_cli_missing", f"{argv[0]!r} is not installed or not on PATH", {"argv": argv}) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"{provider}_cli_timeout", f"{argv[0]} did not finish within {timeout}s", {"argv": argv}) from exc
    except OSError as exc:
        raise ProviderError(f"{provider}_cli_error", f"{argv[0]} could not be launched: {exc}", {"argv": argv}) from exc
    if proc.returncode != 0:
        raise ProviderError(
            f"{provider}_cli_error",
            (proc.stderr or "").strip() or (proc.stdout or "").strip()[:500] or f"{argv[0]} exited with {proc.returncode}",
            {"argv": argv, "returncode": proc.returncode},
        )
    return proc.stdout or ""


def coerce_output(res: Any) -> str:
    """Injected runners may return text, or a dict/list standing in for JSON stdout."""
    if res is None:
        return ""
    if isinstance(res, (dict, list)):
        return json.dumps(res)
    return str(res)


def call_runner(runner: Callable[..., Any], argv: list[str], provider: str, **kwargs: Any) -> str:
    """Invoke `runner` and wrap raw launch errors (FileNotFoundError/TimeoutExpired) as ProviderError."""
    try:
        return coerce_output(runner(list(argv), **kwargs))
    except ProviderError:
        raise
    except FileNotFoundError as exc:
        raise ProviderError(f"{provider}_cli_missing", f"{argv[0]!r} is not installed or not on PATH", {"argv": argv}) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"{provider}_cli_timeout", f"{argv[0]} timed out", {"argv": argv}) from exc
    except OSError as exc:
        raise ProviderError(f"{provider}_cli_error", f"{argv[0]} could not be launched: {exc}", {"argv": argv}) from exc


def ref_safe(text: str) -> str:
    """Reduce `text` to characters that are always legal inside one git ref component."""
    cleaned = re.sub(r"[^A-Za-z0-9._/-]", "-", text).strip("/.")
    cleaned = re.sub(r"\.\.+", ".", cleaned)
    cleaned = re.sub(r"/+", "/", cleaned)
    return cleaned or "dispatch"


def preserve_worker_head(run: Callable[[list[str]], str], worktree: str, dispatch_id: str) -> dict[str, str]:
    """Pin the worker's ACTUAL HEAD (read in its own worktree) under refs/open-fleet/preserved/.

    Raises `preserve_failed` unless the ref verifiably equals that HEAD and lives in a git
    directory that survives removal of the worktree (a linked worktree's common dir).
    """
    if not worktree or not os.path.isabs(worktree):
        raise ProviderError("preserve_failed", f"worker worktree {worktree!r} is unknown; refusing destructive cleanup")
    head = run(["git", "-C", worktree, "rev-parse", "--verify", "HEAD"]).strip()
    if not _SHA_RE.match(head):
        raise ProviderError("preserve_failed", f"could not resolve HEAD in {worktree!r}: {head[:80]!r}")
    ref = f"refs/open-fleet/preserved/{ref_safe(dispatch_id)}"
    run(["git", "-C", worktree, "update-ref", ref, head])
    pinned = run(["git", "-C", worktree, "rev-parse", "--verify", ref]).strip()
    if pinned != head:
        raise ProviderError("preserve_failed", f"{ref} resolves to {pinned!r}, not the worker HEAD {head}")
    common = run(["git", "-C", worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"]).strip()
    wt_real = os.path.realpath(worktree)
    common_real = os.path.realpath(common) if common else ""
    if not common_real or common_real == wt_real or common_real.startswith(wt_real.rstrip("/") + "/"):
        raise ProviderError(
            "preserve_failed",
            f"git dir {common!r} lives inside the worktree being removed; {ref} would not survive cleanup",
        )
    return {"ref": ref, "sha": head, "commonDir": common}


def _artifact_match(path: str, entry: str) -> bool:
    """`entry` ending in "/" covers that directory's contents; otherwise an EXACT file match.

    A prefix test let `AGENTS.md` hide `AGENTS.md.backup` and `.claude/` hide a user's own
    commands, so an unforced removal discarded them (#592 review).
    """
    if entry.endswith("/"):
        return path == entry.rstrip("/") or path.startswith(entry)
    return path == entry


def foreign_dirty_paths(
    run: Callable[[list[str]], str],
    worktree: str,
    extra_ignored: tuple[str, ...] = (),
) -> list[str]:
    """Uncommitted paths in `worktree` that are NOT open-fleet hook artifacts (work a removal would lose)."""
    out = run(["git", "-C", worktree, "status", "--porcelain", "--untracked-files=all"])
    ignored = HOOK_ARTIFACT_PREFIXES + tuple(extra_ignored)
    dirty: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not any(_artifact_match(path, p) for p in ignored):
            dirty.append(path)
    return dirty


def insert_dispatch(
    state: LocalStateStore,
    *,
    dispatch_id: str,
    task_id: str,
    run: str | None,
    worktree: str | None,
    agent: str,
    profile: str,
    handle: str,
    backend: str,
    effective: dict[str, Any],
    session_id: str | None = None,
) -> None:
    now = time.time()
    with state._connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO dispatches(
                dispatch_id, task_id, run_id, worktree, agent, profile, terminal_handle, state,
                terminal_state, backend, launch_effective, session_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 'active', ?, ?, ?, ?, ?)
            """,
            (
                dispatch_id,
                task_id or "",
                run or "default",
                worktree or "",
                agent,
                profile,
                handle,
                backend,
                json.dumps(effective),
                session_id,
                now,
                now,
            ),
        )


def load_dispatch(state: LocalStateStore, dispatch_id: str, backend: str) -> dict[str, Any]:
    """The locally recorded dispatch for `backend`, with `launch_effective` decoded."""
    if not dispatch_id:
        raise ProviderError("dispatch_not_found", "no dispatch id given")
    with state._connect() as conn:
        row = conn.execute(
            "SELECT * FROM dispatches WHERE dispatch_id = ? AND backend = ?",
            (dispatch_id, backend),
        ).fetchone()
    if not row:
        raise ProviderError("dispatch_not_found", f"{backend}: dispatch {dispatch_id!r} not found")
    rec = dict(row)
    try:
        rec["effective"] = json.loads(rec.get("launch_effective") or "{}")
    except json.JSONDecodeError:
        rec["effective"] = {}
    return rec


def record_fence(state: LocalStateStore, dispatch_id: str, verb: str) -> tuple[str, str]:
    """Store the posix fence state names (`stopped|abandoned|released|retained`)."""
    new_state, term_state = fence_state(verb)
    with state._connect() as conn:
        conn.execute(
            "UPDATE dispatches SET state = ?, terminal_state = ?, updated_at = ? WHERE dispatch_id = ?",
            (new_state, term_state, time.time(), dispatch_id),
        )
    return new_state, term_state


def show_from_row(row: dict[str, Any], *, stage: str | None = None, raw: Any = None, worktree: str | None = None) -> dict[str, Any]:
    return normalize_show(
        row["dispatch_id"],
        row["state"],
        task_id=row.get("task_id") or None,
        terminal_state=row.get("terminal_state"),
        handle=row.get("terminal_handle"),
        worktree=worktree if worktree is not None else (row.get("worktree") or None),
        stage=stage,
        raw=raw,
    )


def local_worker_list(
    state: LocalStateStore,
    backend: str,
    *,
    run: str | None = None,
    task: str | None = None,
    limit: int | None = None,
    stages: dict[str, str] | None = None,
    upstream: Any = None,
) -> dict[str, Any]:
    """A worker-list receipt built from OUR dispatch rows (the shape `worker_ops.format_list` reads).

    Upstream listings name workers open-fleet never dispatched (and reused slots); they may only
    annotate a row's `stage` (keyed by dispatch id), never become rows themselves.
    """
    q = "SELECT * FROM dispatches WHERE backend = ?"
    params: list[Any] = [backend]
    if run:
        q += " AND run_id = ?"
        params.append(run)
    if task:
        q += " AND task_id = ?"
        params.append(task)
    q += " ORDER BY created_at ASC"
    if limit:
        q += " LIMIT ?"
        params.append(int(limit))
    with state._connect() as conn:
        rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    stages = stages or {}
    workers = [show_from_row(r, stage=stages.get(str(r["dispatch_id"])))["worker"] for r in rows]
    out: dict[str, Any] = {"workers": workers, "scope": {"source": backend}, "page": {"nextCursor": None}}
    if upstream is not None:
        out["upstream"] = upstream
    return out
