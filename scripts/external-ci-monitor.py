#!/usr/bin/env python3
"""Read CI health outside Actions. Exit 0=healthy, 1=unhealthy, 2=monitor failed.

Use --drill-run with an existing failed run to exercise the same classifier without
changing main. This tool only reads GitHub and emits JSON; the host routes alerts.

--transport gh (default) reads through an authenticated `gh` CLI. --transport rest
reads the public REST API with no CLI and no token (GITHUB_TOKEN is sent when set),
for a host like a scheduled cloud session where `gh` is not logged in (#528). The token is an
unredirected header (urllib re-sends an ordinary one to whatever a 3xx names), an answer from any
origin but the API's is refused, and so is a body over MAX_BODY; --repo must be OWNER/NAME
before it is put into a URL or a gh argv (2026-10-27 audit, W5-08/W5-09).
--quiet-when-current keeps a green run on main's CURRENT head healthy past 24 hours:
a quiet repository with no new commits is not an outage, while a head that CI never
finished still goes stale.
"""
import argparse
import datetime as dt
import http.client
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request

REPO = "ravidsrk/open-fleet"
API = "https://api.github.com"
MAX_BODY = 32 << 20  # far above any answer read here; an endless one is refused, never held whole
# GitHub's own shapes: an owner is letters, digits and hyphens (up to 39); a name letters, digits, ._-
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")


def assess(run, now, max_age_hours=24, main_sha=None):
    if run is None:
        return {"status": "missing", "detail": "no completed validate run on main"}
    if not isinstance(run, dict):
        raise ValueError("run must be an object")
    if not isinstance(run["updatedAt"], str):
        raise ValueError("run timestamp must be a string")
    stamp = dt.datetime.fromisoformat(run["updatedAt"].replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp > now:
        raise ValueError("run timestamp is unzoned or in the future")
    conclusion = run["conclusion"]
    if not isinstance(conclusion, str) or not conclusion:
        raise ValueError("completed run has no conclusion")
    if not isinstance(run["headSha"], str) or not re.fullmatch(r"[0-9a-f]{40}", run["headSha"]):
        raise ValueError("completed run has no valid commit SHA")
    run_id = run["databaseId"]
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("completed run has no valid run ID")
    if not isinstance(run["url"], str) or not re.fullmatch(
            rf"https://github\.com/[^/]+/[^/]+/actions/runs/{run_id}", run["url"]):
        raise ValueError("completed run has no matching GitHub run URL")
    status = "healthy"
    if conclusion != "success":
        status = "red"
    elif now - stamp >= dt.timedelta(hours=max_age_hours):
        # Old but green on the commit main still points at: nothing new went unchecked.
        status = "healthy" if main_sha == run["headSha"] else "stale"
    return {"status": status, "conclusion": conclusion, "updatedAt": run["updatedAt"],
            "sha": run["headSha"], "url": run["url"], "runId": run["databaseId"]}


def gh_json(args):
    proc = subprocess.run(["gh", *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=45, check=False)
    if proc.returncode:
        raise RuntimeError("GitHub query failed; check connectivity and gh authentication")
    return json.loads(proc.stdout)


def repo_path(repo):
    """`repo` as a URL path segment pair, once it is exactly OWNER/NAME: a `?`, `#`, `%`, `..`
    or an extra segment would change which endpoint is read, and the verdict would be about
    something else (W5-09)."""
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo) or repo.split("/")[1] in (".", ".."):
        raise ValueError("--repo must be OWNER/NAME")
    return "/".join(urllib.parse.quote(part, safe="") for part in repo.split("/"))


def _origin(url):
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or {"https": 443, "http": 80}.get(scheme)


def rest_json(path):
    """GET one public REST endpoint. Never echoes the response on failure.

    The token rides an UNREDIRECTED header: urllib copies an add_header() value onto the request a
    3xx makes, to whatever host its Location names (W5-08; upstream_probe.py does the same). An
    answer that ends anywhere but the API's origin is refused, and so is a body over MAX_BODY."""
    url = f"{API}/{path}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "open-fleet-external-ci-monitor"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            # A real response names the URL it was finally read from, redirects followed.
            if _origin(getattr(response, "url", None) or url) != _origin(API):
                raise RuntimeError("GitHub redirected the monitor to another origin; the answer is refused")
            body = response.read(MAX_BODY + 1)
    except http.client.HTTPException as err:
        # A dropped or truncated response (IncompleteRead) is not an OSError; it must
        # still reach main() as a monitor error, never a traceback with the wrong exit.
        raise RuntimeError("GitHub response was cut off") from err
    if len(body) > MAX_BODY:
        raise RuntimeError(f"GitHub response exceeds {MAX_BODY} bytes; refused")
    return json.loads(body.decode("utf-8"))


def _from_rest(run):
    return {"databaseId": run["id"], "conclusion": run["conclusion"],
            "headSha": run["head_sha"], "url": run["html_url"],
            "updatedAt": run["updated_at"]}


def main_head(repo, transport="gh"):
    """The commit main points at now."""
    path = f"repos/{repo_path(repo)}/commits/main"
    commit = rest_json(path) if transport == "rest" else gh_json(["api", path])
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("main has no valid head SHA")
    return sha


def fetch_run(repo, drill_run=None, transport="gh"):
    safe = repo_path(repo)
    if drill_run is not None:
        path = f"repos/{safe}/actions/runs/{int(drill_run)}"
        run = rest_json(path) if transport == "rest" else gh_json(["api", path])
        # A drill uses a real failed validate run, never a synthetic success/failure.
        if (run["name"] != "validate" or run["status"] != "completed"
                or run["conclusion"] == "success"):
            raise ValueError("drill target must be a completed unsuccessful validate run")
        return _from_rest(run)
    if transport == "rest":
        page = rest_json(f"repos/{safe}/actions/workflows/validate.yml/runs"
                         "?branch=main&event=push&status=completed&per_page=1")
        runs = page.get("workflow_runs") if isinstance(page, dict) else None
        if not isinstance(runs, list) or len(runs) > 1:
            raise ValueError("unexpected latest-run response")
        return _from_rest(runs[0]) if runs else None
    runs = gh_json(["run", "list", "--repo", repo, "--workflow", "validate.yml",
                    "--branch", "main", "--event", "push", "--status", "completed",
                    "--limit", "1", "--json", "databaseId,conclusion,headSha,url,updatedAt"])
    if not isinstance(runs, list) or len(runs) > 1:
        raise ValueError("unexpected latest-run response")
    return runs[0] if runs else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--drill-run", type=int, help="read a real failed validate run instead of main")
    parser.add_argument("--transport", choices=("gh", "rest"), default="gh",
                        help="gh CLI (default) or the public REST API with no CLI")
    parser.add_argument("--quiet-when-current", action="store_true",
                        help="a green run on main's current head never goes stale")
    args = parser.parse_args(argv)
    try:
        run = fetch_run(args.repo, args.drill_run, transport=args.transport)
        current = (main_head(args.repo, args.transport)
                   if args.quiet_when_current and args.drill_run is None else None)
        result = assess(run, dt.datetime.now(dt.timezone.utc), main_sha=current)
        result["drill"] = args.drill_run is not None
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        # Never turn an absent tool, malformed response or API outage into a green result.
        # Avoid echoing raw subprocess stderr or payloads into persistent alert logs.
        result = {"status": "monitor-error", "detail": "CI health could not be read; check gh/API access",
                  "drill": args.drill_run is not None}
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
