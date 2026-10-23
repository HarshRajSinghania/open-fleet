#!/usr/bin/env python3
"""Read CI health outside Actions. Exit 0=healthy, 1=unhealthy, 2=monitor failed.

Use --drill-run with an existing failed run to exercise the same classifier without
changing main. This tool only reads GitHub and emits JSON; the host routes alerts.

--transport gh (default) reads through an authenticated `gh` CLI. --transport rest
reads the public REST API with no CLI and no token (GITHUB_TOKEN is sent when set),
for a host like a scheduled cloud session where `gh` is not logged in (#528).
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
import urllib.request

REPO = "ravidsrk/open-fleet"
API = "https://api.github.com"


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


def rest_json(path):
    """GET one public REST endpoint. Never echoes the response on failure."""
    request = urllib.request.Request(f"{API}/{path}", headers={
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "open-fleet-external-ci-monitor"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = response.read()
    except http.client.HTTPException as err:
        # A dropped or truncated response (IncompleteRead) is not an OSError; it must
        # still reach main() as a monitor error, never a traceback with the wrong exit.
        raise RuntimeError("GitHub response was cut off") from err
    return json.loads(body.decode("utf-8"))


def _from_rest(run):
    return {"databaseId": run["id"], "conclusion": run["conclusion"],
            "headSha": run["head_sha"], "url": run["html_url"],
            "updatedAt": run["updated_at"]}


def main_head(repo, transport="gh"):
    """The commit main points at now."""
    path = f"repos/{repo}/commits/main"
    commit = rest_json(path) if transport == "rest" else gh_json(["api", path])
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("main has no valid head SHA")
    return sha


def fetch_run(repo, drill_run=None, transport="gh"):
    if drill_run is not None:
        path = f"repos/{repo}/actions/runs/{drill_run}"
        run = rest_json(path) if transport == "rest" else gh_json(["api", path])
        # A drill uses a real failed validate run, never a synthetic success/failure.
        if (run["name"] != "validate" or run["status"] != "completed"
                or run["conclusion"] == "success"):
            raise ValueError("drill target must be a completed unsuccessful validate run")
        return _from_rest(run)
    if transport == "rest":
        page = rest_json(f"repos/{repo}/actions/workflows/validate.yml/runs"
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
