#!/usr/bin/env python3
"""A fake `gh` for the merge-queue tests (#599). No network: GitHub is a JSON file plus a bare repo.

State lives in $FAKE_GH_STATE: {"repo": "<host/owner/name>", "bare": <bare repo>, "offline": bool,
"prs": {"<n>": {...}}, "forks": {"<host/owner/name>": {"bare": ..., "prs": {...}}}}. The repository
a call acts on is resolved as the real CLI resolves it: `--repo`/`-R`, else $GH_REPO, else the
default ("repo"); a fork shares the upstream's objects and may carry a PR with the same head. A PR
names its `headRefName` and `baseRefName`; its head is read live from the bare repo, and every
`pr view` mirrors it to `refs/pull/<n>/head` as GitHub does. `pr merge` merges the way GitHub's
merge button does: an in-memory merge onto the CURRENT base head of whatever the PR targets now,
refused when `--match-head-commit` does not name the PR head. `api --method POST
repos/<owner>/<name>/merges -f base=<branch> -f head=<sha>` is GitHub's merges endpoint: it merges
that commit into THAT branch, and every open PR whose head the branch now contains, and which
targets it, is marked merged (as GitHub marks a PR whose head reaches its base). Every merge call is appended to $FAKE_GH_LOG
with the pid of the conductor that ran it, so a test can prove which conductor sent and how often.
$FAKE_GH_MERGE_DELAY holds a merge open for that many seconds (the killed-mid-call drill), and a
state `race_base_write` makes a non-cooperating writer move the base just before one merge lands, and
`retarget_before_merge` ({"pr": n, "to": branch}) retargets a PR as a merge request arrives: after
every check a conductor could make, before GitHub acts (the PR #647 retarget race).
"""
import fcntl
import json
import os
import subprocess
import sys
import time

IDENTITY = {"GIT_AUTHOR_NAME": "GitHub", "GIT_AUTHOR_EMAIL": "noreply@github.invalid",
            "GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": "noreply@github.invalid"}


def git(bare, *args, check=True, stdin=None):
    env = {**os.environ, **IDENTITY, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-C", bare, *args], capture_output=True, text=True, check=check, env=env,
                          input=stdin)


def race_base_write(bare, base):
    """Someone outside the fleet pushes to the base between the queue's checks and the merge."""
    head = ref(bare, f"refs/heads/{base}")
    blob = git(bare, "hash-object", "-w", "--stdin", stdin="raced\n").stdout.strip()
    listing = git(bare, "ls-tree", head).stdout + f"100644 blob {blob}\traced.txt\n"
    tree = git(bare, "mktree", stdin=listing).stdout.strip()
    commit = git(bare, "commit-tree", tree, "-p", head, "-m", "external race").stdout.strip()
    git(bare, "update-ref", f"refs/heads/{base}", commit, head)


def ref(bare, name):
    proc = git(bare, "rev-parse", "--verify", "-q", name, check=False)
    return proc.stdout.strip() or None


def present(scope, num, pr, target):
    bare = scope["bare"]
    head = ref(bare, f"refs/heads/{pr['headRefName']}") or pr.get("mergedHead") or pr.get("head")
    if head and pr["state"] == "OPEN":
        git(bare, "update-ref", f"refs/pull/{num}/head", head)
    return {"number": int(num), "state": pr["state"], "headRefOid": head, "headRefName": pr["headRefName"],
            "baseRefName": pr["baseRefName"], "url": f"https://{pr.get('urlRepo') or target}/pull/{num}",
            "mergeCommit": {"oid": pr["mergeCommit"]} if pr.get("mergeCommit") else None}


def retarget(state, scope):
    """Someone retargets a PR between the conductor's last read and GitHub's merge."""
    move = state.pop("retarget_before_merge", None)
    if move:
        scope["prs"][str(move["pr"])]["baseRefName"] = move["to"]


def merge(state, scope, num, argv, target):
    retarget(state, scope)
    pr, bare = scope["prs"][num], scope["bare"]
    match = argv[argv.index("--match-head-commit") + 1] if "--match-head-commit" in argv else None
    head = present(scope, num, pr, target)["headRefOid"]
    if pr["state"] != "OPEN":
        return 1, f"Pull request #{num} is not open"
    if match and head != match:
        return 1, "Head branch was modified. Review and try the merge again."
    if pr.get("refuse"):
        return 1, pr["refuse"]
    if state.pop("race_base_write", False):
        race_base_write(bare, pr["baseRefName"])
    base_head = ref(bare, f"refs/heads/{pr['baseRefName']}")
    proc = git(bare, "merge-tree", "--write-tree", base_head, head, check=False)
    if proc.returncode != 0:
        return 1, f"Pull request #{num} is not mergeable: the merge commit cannot be cleanly created."
    tree = proc.stdout.splitlines()[0].strip()
    commit = git(bare, "commit-tree", tree, "-p", base_head, "-p", head,
                 "-m", f"Merge pull request #{num} from {pr['headRefName']}").stdout.strip()
    git(bare, "update-ref", f"refs/heads/{pr['baseRefName']}", commit, base_head)
    pr.update({"state": "MERGED", "mergeCommit": commit, "mergedHead": head})
    if "--delete-branch" in argv:
        git(bare, "update-ref", "-d", f"refs/heads/{pr['headRefName']}", check=False)
    return 0, f"Merged pull request #{num}"


def api_merge(state, scope, argv, target):
    """POST repos/<owner>/<name>/merges: merge `head` (a commit) into the NAMED `base` branch."""
    retarget(state, scope)
    fields = dict(argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "-f")
    base, head, bare = fields["base"], fields["head"], scope["bare"]
    by_head = [(n, pr) for n, pr in scope["prs"].items() if present(scope, n, pr, target)["headRefOid"] == head]
    if any(pr.get("refuse") for _n, pr in by_head):
        return 1, next(pr["refuse"] for _n, pr in by_head if pr.get("refuse")), by_head
    if state.pop("race_base_write", False):
        race_base_write(bare, base)
    base_head = ref(bare, f"refs/heads/{base}")
    if base_head is None:
        return 1, "gh: Base does not exist (HTTP 404)", by_head
    if git(bare, "merge-base", "--is-ancestor", head, base_head, check=False).returncode == 0:
        return 0, "", by_head  # 204: nothing to merge
    proc = git(bare, "merge-tree", "--write-tree", base_head, head, check=False)
    if proc.returncode != 0:
        return 1, "gh: Merge conflict (HTTP 409)", by_head
    tree = proc.stdout.splitlines()[0].strip()
    commit = git(bare, "commit-tree", tree, "-p", base_head, "-p", head,
                 "-m", fields.get("commit_message") or f"Merge {head} into {base}").stdout.strip()
    git(bare, "update-ref", f"refs/heads/{base}", commit, base_head)
    for _n, pr in by_head:
        if pr["state"] == "OPEN" and pr["baseRefName"] == base:
            pr.update({"state": "MERGED", "mergeCommit": commit, "mergedHead": head})
    return 0, json.dumps({"sha": commit}), by_head


def main(argv):
    path = os.environ["FAKE_GH_STATE"]
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
        if state.get("offline"):
            print("error connecting to api.github.com", file=sys.stderr)
            return 1
        if argv[:2] == ["auth", "status"]:
            return 0
        full, target = list(argv), os.environ.get("GH_REPO") or state["repo"]
        if argv[:1] == ["api"]:  # an API path names its repository; GH_REPO does not apply
            host = argv[argv.index("--hostname") + 1] if "--hostname" in argv else "github.com"
            api_path = next(a for a in argv[1:] if a.startswith("repos/"))
            target = f"{host}/{'/'.join(api_path.split('/')[1:3])}"
        for flag in ("--repo", "-R"):
            if flag in argv:
                i = argv.index(flag)
                target, argv = argv[i + 1], argv[:i] + argv[i + 2:]
        scope = state if target == state["repo"] else state.get("forks", {}).get(target)
        if scope is None:
            print(f"GraphQL: Could not resolve to a Repository with the name '{target}'.", file=sys.stderr)
            return 1
        if argv[:1] == ["api"] and "POST" in argv and next(a for a in argv if a.startswith("repos/")).endswith("/merges"):
            head = dict(argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "-f")["head"]
            prs = [int(n) for n, pr in scope["prs"].items() if present(scope, n, pr, target)["headRefOid"] == head]
            with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
                log.write(json.dumps({"event": "start", "pr": prs[0] if prs else None, "repo": target,
                                      "caller": os.getppid(), "argv": full}) + "\n")
            time.sleep(float(os.environ.get("FAKE_GH_MERGE_DELAY", "0") or 0))
            code, message, _by_head = api_merge(state, scope, argv, target)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
                log.write(json.dumps({"event": "merged" if code == 0 else "refused", "pr": prs[0] if prs else None,
                                      "repo": target, "caller": os.getppid(), "message": message}) + "\n")
            print(message, file=sys.stdout if code == 0 else sys.stderr)
            return code
        if argv[:2] == ["pr", "view"]:
            num = argv[2]
            if num not in scope["prs"]:
                print(f"no pull requests found for {num}", file=sys.stderr)
                return 1
            fields = argv[argv.index("--json") + 1].split(",")
            view = present(scope, num, scope["prs"][num], target)
            print(json.dumps({k: view.get(k) for k in fields}))
            return 0
        if argv[:2] == ["pr", "merge"]:
            num = argv[2]
            with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
                log.write(json.dumps({"event": "start", "pr": int(num), "repo": target, "caller": os.getppid(),
                                      "argv": full}) + "\n")
            time.sleep(float(os.environ.get("FAKE_GH_MERGE_DELAY", "0") or 0))
            code, message = merge(state, scope, num, argv, target)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
                log.write(json.dumps({"event": "merged" if code == 0 else "refused", "pr": int(num), "repo": target,
                                      "caller": os.getppid(), "message": message}) + "\n")
            print(message, file=sys.stdout if code == 0 else sys.stderr)
            return code
        print(f"fake gh: unsupported {argv}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
