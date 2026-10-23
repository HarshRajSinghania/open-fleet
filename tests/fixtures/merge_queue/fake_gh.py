#!/usr/bin/env python3
"""A fake `gh` for the merge-queue tests (#599). No network: GitHub is a JSON file plus a bare repo.

State lives in $FAKE_GH_STATE: {"bare": <bare repo>, "offline": bool, "prs": {"<n>": {...}}}. A PR
names its `headRefName` and `baseRefName`; its head is read live from the bare repo, and every
`pr view` mirrors it to `refs/pull/<n>/head` as GitHub does. `pr merge` merges the way GitHub's
merge button does: an in-memory merge onto the CURRENT base head, refused when
`--match-head-commit` does not name the PR head. Every merge call is appended to $FAKE_GH_LOG
with the pid of the conductor that ran it, so a test can prove which conductor sent and how often.
$FAKE_GH_MERGE_DELAY holds a merge open for that many seconds (the killed-mid-call drill), and a
state `race_base_write` makes a non-cooperating writer move the base just before one merge lands.
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


def present(state, num, pr):
    bare = state["bare"]
    head = ref(bare, f"refs/heads/{pr['headRefName']}") or pr.get("mergedHead") or pr.get("head")
    if head and pr["state"] == "OPEN":
        git(bare, "update-ref", f"refs/pull/{num}/head", head)
    return {"number": int(num), "state": pr["state"], "headRefOid": head, "headRefName": pr["headRefName"],
            "baseRefName": pr["baseRefName"],
            "mergeCommit": {"oid": pr["mergeCommit"]} if pr.get("mergeCommit") else None}


def merge(state, num, argv):
    pr, bare = state["prs"][num], state["bare"]
    match = argv[argv.index("--match-head-commit") + 1] if "--match-head-commit" in argv else None
    head = present(state, num, pr)["headRefOid"]
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
        if argv[:2] == ["pr", "view"]:
            num = argv[2]
            if num not in state["prs"]:
                print(f"no pull requests found for {num}", file=sys.stderr)
                return 1
            fields = argv[argv.index("--json") + 1].split(",")
            view = present(state, num, state["prs"][num])
            print(json.dumps({k: view.get(k) for k in fields}))
            return 0
        if argv[:2] == ["pr", "merge"]:
            num = argv[2]
            with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
                log.write(json.dumps({"event": "start", "pr": int(num), "caller": os.getppid(), "argv": argv}) + "\n")
            time.sleep(float(os.environ.get("FAKE_GH_MERGE_DELAY", "0") or 0))
            code, message = merge(state, num, argv)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
                log.write(json.dumps({"event": "merged" if code == 0 else "refused", "pr": int(num),
                                      "caller": os.getppid(), "message": message}) + "\n")
            print(message, file=sys.stdout if code == 0 else sys.stderr)
            return code
        print(f"fake gh: unsupported {argv}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
