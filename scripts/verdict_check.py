"""Verdict-derived merge check (#452): block merge until a GO verdict is posted at the tip.

Branch protection cannot express ``reviewed_sha == head_sha`` natively, so this
script implements the custom check: it passes iff the pull request carries a
GO verdict review whose ``reviewed_sha`` equals the PR's current head SHA. Any
push moves the head and fails the check until a fresh GO is posted.

Verdict convention (posted as the body of an APPROVING review, or a COMMENTED
review by a trusted account)::

    VERDICT: GO
    reviewed_sha: <full 40-hex head sha>

A GO counts from an APPROVED or a COMMENTED review whose author_association is
OWNER / MEMBER / COLLABORATOR — which covers the owner binding a verdict on
their own PR with a COMMENTED review, the normal fleet flow, since GitHub
forbids approving your own PR. The review state proves nothing about its
author: on a public repository any account can submit an APPROVED review (it
only fails to count toward native required reviews), so an APPROVED GO from
anyone else never counts (PR #718 review, P1), nor does a drive-by COMMENTED
GO (PR #460 review, P1), nor a fork author's GO on their own PR: being the
PR's author is no trust tier (2026-10-27 security audit, W6-06).

A GO is a SHA binding, NOT evidence that anyone read the diff: it proves that a
trusted account claimed to have checked this exact head, nothing more. With one
human maintainer the owner's self-GO is the normal case, so the gate cannot
prove independent review; requiring a second person is branch protection's job
(required approvals), and this check never substitutes for it.

The grader (W6-01): a ``pull_request`` run loads its workflow from the PR's
merge ref, so the PR supplies the YAML that decides what the required `gates`,
`guard` and `pinned-demo` contexts run — a fork PR could empty those jobs and
get three green contexts that checked nothing. This check, run from the default
branch, therefore also refuses any PR that changes a GRADER path (added,
modified, removed or renamed from or to one) unless the repository owner wrote
it: the files GitHub or the runner read to choose which commands a required job
executes, before any repository code runs — ``.github/workflows/`` and
``.github/actions/`` (job and step definitions), and ``.github/ci-tools.lock``
(which build of each CI tool those jobs install and execute). A files list
GitHub may have cut short (3000 files at most) or a head that moves while it is
read fails closed. The trusted status workflow runs the checker from the default branch
(verdict-gate.yml); its activation remains pending in #594 (docs/ops.md). Approval policy beyond that (how many, from whom, conversations
resolved) stays enforced by branch protection itself; this check adds SHA
binding, not a second approval rule. Dismissed and change-requested reviews
never count. Short SHAs are rejected: ambiguity in what was reviewed is
exactly the failure mode. The marker is case-SENSITIVE (exact `VERDICT: GO`):
machine-read verdicts must not have case variants, and the CI job gate matches
the same literal (PR #465 review, P1).

CI trigger contract (see verdict-check.yml): the workflow evaluates GO-marker
reviews and dismissals only — never pushes, so a transient no-GO state cannot
fail-poison the head (a FAILED conclusion on the head SHA sticks past a newer
SUCCESS; only a re-run clears it). Post a new review per verdict.

The intended authoritative gate is ``--post-status`` (verdict-gate.yml), once
its dedicated app identity and required status are configured (docs/ops.md). A
``pull_request_review`` run loads the workflow file from the PR, so its job can
be rewritten by the PR it gates; verdict-gate.yml is a ``workflow_run`` workflow,
always loaded from the default branch, and runs THIS file from the default
branch too. It re-derives the verdict from the GitHub API and posts it as the
``verdict-gate`` commit status on the PR's current head. A status is
latest-wins per context, so a later GO clears an earlier failure without a
re-run; a push leaves the new head with no status, which blocks once required until a fresh
GO. With ``--post-status`` the exit code reports whether the status was posted
(0), not the verdict: the status is the verdict, and a red run on the default
branch for every unverdicted review would only be noise. Fork PRs carry no PR
number on the ``workflow_run`` event; ``--head-sha`` finds the one open PR at
that head.
"""

import argparse
import json
import os
import re
import subprocess
import sys

VERDICT_RE = re.compile(r"^VERDICT:\s*GO\s*$", re.MULTILINE)
# Every VERDICT line, whatever it says: a review counts only when all of them read exactly GO.
ANY_VERDICT_RE = re.compile(r"^\s*VERDICT\s*:(.*)$", re.MULTILINE)
SHA_RE = re.compile(r"^reviewed_sha:\s*([0-9a-fA-F]{40})\s*$", re.MULTILINE)

GH_API = "gh api"


# GitHub-computed review author trust tiers that may carry a COMMENTED GO.
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# Intended required status context; activation is tracked in #594 (docs/ops.md).
STATUS_CONTEXT = "verdict-gate"
FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")

# The CI grader (W6-01, module docstring): what GitHub or the runner reads to choose which
# commands a required job executes, before any repository code runs. Only the owner's PR may
# change it; docs/ops.md#merge-gate says why the line is drawn here.
GRADER_DIRS = (".github/workflows/", ".github/actions/")
GRADER_FILES = (".github/ci-tools.lock",)
# GitHub's PR files list stops at 3000 entries; a list that long may be missing the one that
# matters.
FILES_LIST_CAP = 3000


def _author_trusted(review, pr_author):
    """Whether a review's author is a trusted tier, whatever the review's state. ``pr_author`` grants nothing: a
    fork author's GO on their own PR is self-assertion, not a binding (W6-06). The owner's
    own-PR GO still counts, through the OWNER tier."""
    del pr_author
    return review.get("author_association") in TRUSTED_ASSOCIATIONS


def go_reviews_at_tip(reviews, head_sha, pr_author=None):
    """Return the trusted GO reviews bound to ``head_sha``.

    ``reviews`` is a list of GitHub review objects (``state``, ``body``,
    ``user.login``, ``author_association``, ``submitted_at`` keys).
    The VERDICT line matches the exact uppercase literal; the SHA comparison
    is case-insensitive hex but must be a full 40 hex digits — short SHAs
    never match.
    """
    head = head_sha.lower()
    hits = []
    for review in reviews:
        state = review.get("state")
        if state not in ("APPROVED", "COMMENTED") or not _author_trusted(review, pr_author):
            # DISMISSED never counts; CHANGES_REQUESTED with a GO marker is
            # self-contradictory; an APPROVED or COMMENTED review from an untrusted
            # author is a drive-by: any account can submit either on a public
            # repository (PR #460 review, P1; PR #718 review, P1).
            continue
        body = review.get("body") or ""
        if not VERDICT_RE.search(body):
            continue
        if any(v.strip() != "GO" for v in ANY_VERDICT_RE.findall(body)):
            # `VERDICT: GO` then `VERDICT: NO-GO` read as GO: the first GO line won. Any other
            # verdict line in the same review voids it — fail closed (2026-10-23 review, §5).
            continue
        match = SHA_RE.search(body)
        if match and match.group(1).lower() == head:
            hits.append(review)
    return hits


def verdict_at_tip(reviews, head_sha, pr_author=None):
    """True iff at least one trusted GO verdict review binds the head SHA."""
    return bool(go_reviews_at_tip(reviews, head_sha, pr_author))


def _json_values(text):
    """Every top-level JSON value in ``text``, in order.

    Robust to however the pages arrive: one document, documents on separate
    lines, or arrays concatenated with no separator at all (``][``) — which
    is what plain ``--paginate`` emits, and which a line splitter misreads.
    """
    decoder = json.JSONDecoder()
    values, i, n = [], 0, len(text)
    while True:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            return values
        value, i = decoder.raw_decode(text, i)
        values.append(value)


def _gh_api(path, repo, paginate=False):
    """GET ``repos/<repo>/<path>``. ``paginate=True`` is for LIST endpoints: every page is
    fetched (``--paginate --slurp`` wraps them in one outer array) and merged into one list.
    A single-object endpoint is fetched unpaginated and returned as the object."""
    cmd = ["gh", "api"]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    cmd += ["-H", "Accept: application/vnd.github+json", f"repos/{repo}/{path.lstrip('/')}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{GH_API} {path} failed: {proc.stderr.strip()}")
    try:
        values = _json_values(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{GH_API} {path} returned unparseable JSON: {exc}") from exc
    if not paginate:
        if len(values) > 1:
            raise RuntimeError(f"{GH_API} {path} returned {len(values)} JSON documents, want 1")
        return values[0] if values else {}
    merged = []
    for value in values:
        if not isinstance(value, list):
            raise RuntimeError(f"{GH_API} {path}: expected a list of pages, got "
                               f"{type(value).__name__}")
        # --slurp: [[page1…], [page2…]]; a gh without --slurp: [page1…][page2…].
        for item in value:
            if isinstance(item, list):
                merged.extend(item)
            else:
                merged.append(item)
    return merged


def check_pr(pr_number, repo):
    """Fetch the PR head SHA + reviews and evaluate the verdict rule."""
    pr = _gh_api(f"pulls/{pr_number}", repo)
    if isinstance(pr, list):  # tolerate a wrapped single-object response
        pr = pr[0] if pr else {}
    if not isinstance(pr, dict):
        pr = {}
    head_sha = (pr.get("head") or {}).get("sha", "")
    pr_author = (pr.get("user") or {}).get("login", "")
    reviews = _gh_api(f"pulls/{pr_number}/reviews", repo, paginate=True)
    if not isinstance(reviews, list):
        reviews = []
    hits = go_reviews_at_tip(reviews, head_sha, pr_author)
    return head_sha, reviews, hits, pr_author


def grader_paths(files):
    """Every changed path in a GitHub PR files list that belongs to the CI grader, sorted.

    A rename counts on either side (``previous_filename`` too): moving a workflow out of
    ``.github/workflows/`` deletes a gate as surely as emptying it.
    """
    hits = set()
    for entry in files if isinstance(files, list) else []:
        if not isinstance(entry, dict):
            continue
        for key in ("filename", "previous_filename"):
            path = entry.get(key)
            if isinstance(path, str) and (path in GRADER_FILES or path.startswith(GRADER_DIRS)):
                hits.add(path)
    return sorted(hits)


def _is_owner(pr, repo):
    """The PR's author is the repository owner: GitHub says OWNER, or the login is the owner's
    (logins compare case-insensitively, as GitHub resolves them)."""
    login = (pr.get("user") or {}).get("login", "")
    owner = repo.split("/", 1)[0]
    return pr.get("author_association") == "OWNER" or bool(login) and login.lower() == owner.lower()


def grader_refusal(pr_number, repo, head_sha):
    """(grader paths, refusal reason or None) for the PR at ``head_sha`` (W6-01).

    Reads the PR's files list, then the PR again: the second read names the head the list
    described, so a push between the two reads fails closed rather than pairing one head's
    verdict with another head's files. A list GitHub may have cut short fails closed too.
    """
    files = _gh_api(f"pulls/{pr_number}/files?per_page=100", repo, paginate=True)
    if not isinstance(files, list):
        files = []
    pr = _gh_api(f"pulls/{pr_number}", repo)
    if isinstance(pr, list):
        pr = pr[0] if pr else {}
    if not isinstance(pr, dict):
        pr = {}
    paths = grader_paths(files)
    now = (pr.get("head") or {}).get("sha", "")
    if not head_sha or now.lower() != head_sha.lower():
        return paths, (f"head moved to {now[:12] or 'nothing'} while it was read; "
                       "re-run the gate on the new head")
    changed = pr.get("changed_files")
    if len(files) >= FILES_LIST_CAP or (isinstance(changed, int) and len(files) < changed):
        return paths, (f"the files list may be cut short ({len(files)} listed of "
                       f"{changed if isinstance(changed, int) else '?'} changed), so a grader "
                       "change could hide")
    if paths and not _is_owner(pr, repo):
        more = f" +{len(paths) - 1} more" if len(paths) > 1 else ""
        return paths, (f"changes the CI grader ({paths[0]}{more}); only the owner's PR may — "
                       "this PR's checks ran its own copy")
    return paths, None


def pr_for_head(head_sha, repo):
    """The number of the one OPEN pull request whose head is ``head_sha``.

    A ``workflow_run`` event lists no pull request for a fork's branch, so the gate
    finds it by head. None or several is an error, never a guess: a status posted
    for the wrong PR would gate the right one with someone else's verdict.
    """
    if not FULL_SHA_RE.match(head_sha or ""):
        raise RuntimeError(f"--head-sha must be a full 40-hex SHA, got {head_sha!r}")
    pulls = _gh_api("pulls?state=open&per_page=100", repo, paginate=True)
    matches = [p for p in pulls if isinstance(p, dict)
               and ((p.get("head") or {}).get("sha") or "").lower() == head_sha.lower()]
    if len(matches) != 1:
        raise RuntimeError(f"{len(matches)} open pull requests have head {head_sha}; "
                           "the gate needs exactly one")
    number = matches[0].get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise RuntimeError(f"open pull request at {head_sha} has no usable number: {number!r}")
    return str(number)


def post_status(repo, sha, state, description, context=STATUS_CONTEXT):
    """POST one commit status. GitHub keeps the latest status per context."""
    if not FULL_SHA_RE.match(sha or ""):
        raise RuntimeError(f"cannot post a status on {sha!r}: not a full head SHA")
    cmd = ["gh", "api", "-X", "POST", "-H", "Accept: application/vnd.github+json",
           f"repos/{repo}/statuses/{sha}", "-f", f"state={state}",
           "-f", f"context={context}", "-f", f"description={description[:140]}"]
    server, run_id = os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_RUN_ID")
    if server and run_id:
        cmd += ["-f", f"target_url={server}/{repo}/actions/runs/{run_id}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{GH_API} statuses/{sha} failed: {proc.stderr.strip()}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--pr", help="pull request number")
    which.add_argument("--head-sha",
                       help="evaluate the one open PR whose head is this SHA (fork PRs)")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""),
                        help="owner/repo (default: $GITHUB_REPOSITORY)")
    parser.add_argument("--resolve-pr", action="store_true",
                        help="with --head-sha: print the PR number and exit (no verdict)")
    parser.add_argument("--post-status", metavar="CONTEXT", nargs="?", const=STATUS_CONTEXT,
                        help="post the verdict as a commit status on the PR head "
                             f"(context default: {STATUS_CONTEXT}); exit 0 once posted")
    args = parser.parse_args(argv)
    if not args.repo or "/" not in args.repo:
        print("verdict_check: need --repo owner/repo (or $GITHUB_REPOSITORY)", file=sys.stderr)
        return 2
    if args.resolve_pr and not args.head_sha:
        print("verdict_check: --resolve-pr needs --head-sha", file=sys.stderr)
        return 2
    try:
        pr_number = args.pr or pr_for_head(args.head_sha, args.repo)
        if args.resolve_pr:
            print(pr_number)
            return 0
        head_sha, reviews, hits, pr_author = check_pr(pr_number, args.repo)
        graded, refusal = grader_refusal(pr_number, args.repo, head_sha)
    except RuntimeError as exc:
        print(f"verdict_check: {exc}", file=sys.stderr)
        return 2
    gos = [r for r in reviews if VERDICT_RE.search(r.get("body") or "")]
    print(f"PR #{pr_number} head: {head_sha} (PR author: @{pr_author})")
    print(f"GO verdict reviews: {len(gos)} submitted, {len(hits)} trusted at tip")
    for hit in hits:
        author = (hit.get("user") or {}).get("login", "?")
        print(f"  GO at tip by @{author} [{hit.get('state')}] "
              f"submitted_at={hit.get('submitted_at')}")
    if hits:
        passed, reason = True, "GO verdict binds the merge tip"
    else:
        passed = False
        trusted = [r for r in gos if r.get("state") in ("APPROVED", "COMMENTED")
                   and _author_trusted(r, pr_author)]
        if trusted:
            reason = ("GO verdicts exist but none binds the current head "
                      "(post a fresh VERDICT: GO with reviewed_sha == head)")
        elif gos:
            reason = ("GO markers exist only from untrusted authors "
                      "(drive-by APPROVED or COMMENTED reviews never count)")
        else:
            reason = "no GO verdict review on this PR"
    for path in graded:
        print(f"  grader path changed: {path}")
    if refusal:
        # Before any GO: a verdict on a PR that rewrote its own checks is a verdict on nothing.
        passed, reason = False, refusal
    if passed:
        print(f"verdict_check: PASS — {reason}")
    else:
        print(f"verdict_check: FAIL — {reason}", file=sys.stderr)
    if args.post_status:
        try:
            post_status(args.repo, head_sha, "success" if passed else "failure", reason,
                        args.post_status)
        except RuntimeError as exc:
            print(f"verdict_check: {exc}", file=sys.stderr)
            return 2
        print(f"verdict_check: posted {args.post_status}="
              f"{'success' if passed else 'failure'} on {head_sha}")
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
