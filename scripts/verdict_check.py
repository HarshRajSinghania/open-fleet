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

The LATEST trusted verdict bound to the head decides: a CHANGES_REQUESTED
review, or any non-GO VERDICT line, from a trusted author at the head vetoes an
earlier GO there, and a later GO clears it (PR #718 re-attack).

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
modified, removed or renamed from or to one) unless the repository owner opened
it from a branch of this repository: ``.github/workflows/``,
``.github/actions/`` and ``.github/ci-tools.lock``; the scripts a required job
runs by path (GATE_SCRIPTS); and a root module file or a new top-level
directory, which a job running ``-m coverage`` from the root would import. The
changed paths are read for the exact head (compare API); a list the API may
have cut short (300 files) or a head that moves while it is read fails closed.
CI still runs the PR's own code everywhere else (its tests, what the gate
scripts import), so for a PR the owner did not open the merge control is the
trusted GO at the exact head: the reviewer's attestation that they read the
diff, which no check here can verify. The trusted status workflow runs the checker from the default branch
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
# Seconds one `gh api` read may take. Unbounded, a read that never answered held the gate job
# to its 10-minute limit with no status posted, the owner's own PR included; bounded, it is a
# failed read like any other (an owner's own-branch PR survives one, any other PR fails closed).
GH_API_TIMEOUT = 90


# GitHub-computed review author trust tiers that may carry a COMMENTED GO.
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# Intended required status context; activation is tracked in #594 (docs/ops.md).
STATUS_CONTEXT = "verdict-gate"
FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")

# The CI grader (W6-01, module docstring). Only the owner's PR from a branch of this repository
# may change it; docs/ops.md#merge-gate says why the line is drawn here.
# 1. What GitHub or the runner reads to choose which commands a required job executes, before
#    any repository code runs: the workflows, local actions, and the hashed tool lock.
GRADER_DIRS = (".github/workflows/", ".github/actions/")
GRADER_FILES = (".github/ci-tools.lock",)
# 2. The scripts a required job names on a run: line (gates and its needs, pinned-demo; guard runs
#    the base branch's floor_guard.py): each IS a gate, and a one-file rewrite of it greens that
#    gate (PR #718 re-attack). tests/test_verdict_check.py holds this list to the workflows.
GATE_SCRIPTS = (
    "bench/vf-bench/gate.py", "bench/vf-bench/heldout.py", "bench/vf-bench/replay.py",
    "evals/demo/negative-control/run.sh",
    "runtime/scripts/decisions.py", "runtime/scripts/proof_status.py",
    "runtime/scripts/run_report.py",
    "scripts/bundle.py", "scripts/changelog.py", "scripts/check_trailers.py", "scripts/eval.py",
    "scripts/gen-badges.py", "scripts/shard-tests.py", "scripts/validate.py",
)
# 3. Anything at the root a job could import instead of a tool: scripts/shard-tests.py runs
#    `python -m coverage` and `-m unittest` from the root, which is on sys.path there. A root
#    module file, or a top-level directory this repository does not have (the test holds the list
#    to the tree), is the grader.
TOP_LEVEL_DIRS = frozenset({".claude-plugin", ".github", "bench", "changelog.d", "docs", "evals",
                            "hooks", "playbooks", "runtime", "scripts", "skills", "tests"})
ROOT_MODULE_SUFFIXES = (".py", ".pyc", ".pyd", ".so", ".pth")
# 4. What the test runner imports before any test: every shard runs `-m unittest tests.<module>`,
#    so a `tests/__init__.py` would run first in each and could rewrite the runner.
RUNNER_FILES = ("tests/__init__.py",)
# The compare API lists at most 300 changed files; a list that long may be missing the one that
# matters.
FILES_LIST_CAP = 300
SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _author_trusted(review, pr_author):
    """Whether a review's author is a trusted tier, whatever the review's state. ``pr_author`` grants nothing: a
    fork author's GO on their own PR is self-assertion, not a binding (W6-06). The owner's
    own-PR GO still counts, through the OWNER tier."""
    del pr_author
    return review.get("author_association") in TRUSTED_ASSOCIATIONS


def _verdict_at(review, head, pr_author):
    """"GO", "NO-GO" or None: what one review says about the head ``head`` (lowercase).

    Only a trusted author's review is a verdict at all. A GO is an APPROVED or COMMENTED review
    whose every VERDICT line reads exactly GO and whose full reviewed_sha is the head. A NO-GO is
    a CHANGES_REQUESTED review, or a review with any other VERDICT line, bound to the head by its
    reviewed_sha or, lacking one, by the commit GitHub recorded it on (``commit_id``). A
    DISMISSED review, a review without a verdict, or one bound to another commit says nothing.
    """
    state = review.get("state")
    if state not in ("APPROVED", "COMMENTED", "CHANGES_REQUESTED") \
            or not _author_trusted(review, pr_author):
        return None
    body = review.get("body") or ""
    lines = ANY_VERDICT_RE.findall(body)
    match = SHA_RE.search(body)
    bound = (match.group(1).lower() if match else (review.get("commit_id") or "").lower()) == head
    if state == "CHANGES_REQUESTED" or any(v.strip() != "GO" for v in lines):
        return "NO-GO" if bound and (state == "CHANGES_REQUESTED" or lines) else None
    if lines and match and match.group(1).lower() == head:
        return "GO"
    return None


def _latest_verdict(reviews, head_sha, pr_author=None):
    """(verdict, review) for the latest trusted verdict bound to the head, or (None, None).

    Latest by ``submitted_at``, then by list order (GitHub lists reviews oldest first): a later
    trusted NO-GO vetoes an earlier GO, and a later GO clears an earlier NO-GO (PR #718
    re-attack: an owner's CHANGES_REQUESTED after a GO left the gate green).
    """
    head = (head_sha or "").lower()
    said = [(review.get("submitted_at") or "", i, verdict, review)
            for i, review in enumerate(reviews)
            if isinstance(review, dict) and (verdict := _verdict_at(review, head, pr_author))]
    if not said:
        return None, None
    _when, _i, verdict, review = max(said, key=lambda entry: (entry[0], entry[1]))
    return verdict, review


def go_reviews_at_tip(reviews, head_sha, pr_author=None):
    """Return the trusted GO reviews bound to ``head_sha``, or [] when the latest trusted
    verdict bound to it is a NO-GO.

    ``reviews`` is a list of GitHub review objects (``state``, ``body``,
    ``user.login``, ``author_association``, ``submitted_at``, ``commit_id`` keys).
    The VERDICT line matches the exact uppercase literal; the SHA comparison
    is case-insensitive hex but must be a full 40 hex digits — short SHAs
    never match.
    """
    if _latest_verdict(reviews, head_sha, pr_author)[0] == "NO-GO":
        return []
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
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False,
                              timeout=GH_API_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{GH_API} {path} gave no answer in {GH_API_TIMEOUT}s") from exc
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


# The PR object check_pr read, by (repo, number): grader_refusal decides the owner's own-branch
# exemption from it, so no further read can turn the owner's PR into a failed gate.
_PRS_READ = {}


def _as_pr(value):
    if isinstance(value, list):  # tolerate a wrapped single-object response
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def check_pr(pr_number, repo):
    """Fetch the PR head SHA + reviews and evaluate the verdict rule."""
    pr = _as_pr(_gh_api(f"pulls/{pr_number}", repo))
    _PRS_READ[(repo, str(pr_number))] = pr
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
            if isinstance(path, str) and path and _is_grader(path):
                hits.add(path)
    return sorted(hits)


def _is_grader(path):
    if path in GRADER_FILES or path in GATE_SCRIPTS or path in RUNNER_FILES \
            or path.startswith(GRADER_DIRS):
        return True
    if any(directory.startswith(path.rstrip("/") + "/") for directory in GRADER_DIRS):
        return True  # the directory itself, or a parent, changed as a path (a file or a symlink)
    top, slash, _rest = path.partition("/")
    if not slash:
        return path.endswith(ROOT_MODULE_SUFFIXES)
    return top not in TOP_LEVEL_DIRS


def _same_repo(pr):
    """The PR's head branch lives in the base repository: a fork keeps push access to its own
    branch whoever opened the PR, so only a head here is the opener's alone."""
    head = ((pr.get("head") or {}).get("repo") or {}).get("full_name") or ""
    base = ((pr.get("base") or {}).get("repo") or {}).get("full_name") or ""
    return bool(head) and head.lower() == base.lower()


def _is_owner(pr, repo):
    """The PR's author is the repository owner: GitHub says OWNER, or the login is the owner's
    (logins compare case-insensitively, as GitHub resolves them)."""
    login = (pr.get("user") or {}).get("login", "")
    owner = repo.split("/", 1)[0]
    return pr.get("author_association") == "OWNER" or bool(login) and login.lower() == owner.lower()


def grader_refusal(pr_number, repo, head_sha):
    """(grader paths, refusal reason or None) for the PR at ``head_sha`` (W6-01).

    The owner's PR from a branch of this repository may change the grader, and is decided from
    the PR object check_pr already read, before anything else is read: it gets no refusal, and
    the compare read below only lists its grader paths, best-effort. An API failure there must
    never fail the owner's PR, or one bad read would block every owner PR on main, the fix
    included, with admins enforced (PR #718 review).

    Any other PR fails closed, and every read failure is a refusal (a posted failure status, not
    a missing one). The PR is re-read (its head must still be ``head_sha``), then what that exact
    commit changes is read with the compare API, base...head_sha: the PR files list names no
    commit, so a head flipped M -> benign -> M between the gate's reads passed it (PR #718
    re-attack). A list the API may have cut short fails closed, and so does a PR whose base
    cannot be named.
    """
    first = _PRS_READ.get((repo, str(pr_number)))
    if first is not None and _is_owner(first, repo) and _same_repo(first):
        try:
            return _changed_grader_paths(first, repo, head_sha)[0] or [], None
        except RuntimeError as exc:
            print(f"verdict_check: owner's own-branch PR: grader paths not listed ({exc})",
                  file=sys.stderr)
            return [], None
    try:
        pr = _as_pr(_gh_api(f"pulls/{pr_number}", repo))
        now = (pr.get("head") or {}).get("sha", "")
        if not head_sha or now.lower() != head_sha.lower():
            return [], (f"head moved to {now[:12] or 'nothing'} while it was read; "
                        "re-run the gate on the new head")
        if _is_owner(pr, repo) and _same_repo(pr):  # only when check_pr's read is not at hand
            try:
                return _changed_grader_paths(pr, repo, head_sha)[0] or [], None
            except RuntimeError:
                return [], None
        paths, files = _changed_grader_paths(pr, repo, head_sha)
    except RuntimeError as exc:
        print(f"verdict_check: grader read failed: {exc}", file=sys.stderr)
        return [], f"cannot read what this head changes, so the gate fails closed: {exc}"[:140]
    if paths is None:
        return [], "cannot name the PR's base, so what this head changes cannot be read"
    changed = pr.get("changed_files")
    if len(files) >= FILES_LIST_CAP or (isinstance(changed, int) and len(files) < changed):
        return paths, (f"the files list may be cut short ({len(files)} listed of "
                       f"{changed if isinstance(changed, int) else '?'} changed), so a grader "
                       "change could hide")
    if paths:
        more = f" +{len(paths) - 1} more" if len(paths) > 1 else ""
        return paths, (f"changes the CI grader ({paths[0]}{more}); only the owner's own-branch "
                       "PR may — this PR's checks ran its own copy")
    return paths, None


def _changed_grader_paths(pr, repo, head_sha):
    """(grader paths, the compare files list) for what ``head_sha`` changes against the PR's base
    branch, or (None, None) when the base cannot be named. Raises RuntimeError when the read
    fails."""
    base = pr.get("base") or {}
    ref = base.get("ref") or ""
    base_name = ref if SAFE_REF_RE.match(ref) and ".." not in ref else base.get("sha")
    if not base_name or not FULL_SHA_RE.match(head_sha or "") \
            or (base_name == base.get("sha") and not FULL_SHA_RE.match(base_name)):
        return None, None
    comparison = _gh_api(f"compare/{base_name}...{head_sha}", repo)
    files = comparison.get("files") if isinstance(comparison, dict) else None
    if not isinstance(files, list):
        files = []
    return grader_paths(files), files


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
    # The status carries the gate's identity (verdict-gate.yml: the app's token); every read
    # above used GH_TOKEN, the job's own token, which holds the Contents: read compare needs.
    env = dict(os.environ)
    if os.environ.get("GH_STATUS_TOKEN"):
        env["GH_TOKEN"] = os.environ["GH_STATUS_TOKEN"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
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
    latest, veto = _latest_verdict(reviews, head_sha, pr_author)
    if hits:
        passed, reason = True, "GO verdict binds the merge tip"
    elif latest == "NO-GO":
        passed = False
        reason = (f"the latest trusted verdict at the head is a NO-GO "
                  f"(@{(veto.get('user') or {}).get('login', '?')}, {veto.get('state')}); "
                  "a later GO at this head clears it")
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
