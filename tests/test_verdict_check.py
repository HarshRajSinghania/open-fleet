"""Tests for scripts/verdict_check.py (#452): GO-at-tip verdict rule."""

import contextlib
import importlib.util
import io
import os
import re
import runpy
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "verdict_check", _ROOT / "scripts" / "verdict_check.py")
verdict_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verdict_check)
go_reviews_at_tip = verdict_check.go_reviews_at_tip
verdict_at_tip = verdict_check.verdict_at_tip

HEAD = "a" * 40
OTHER = "b" * 40


def review(body, state="APPROVED", login="reviewer", association="MEMBER"):
    return {"state": state, "body": body, "submitted_at": "2026-09-16T00:00:00Z",
            "user": {"login": login}, "author_association": association}


def go_body(sha):
    return f"Looks good.\n\nVERDICT: GO\nreviewed_sha: {sha}\n"


class VerdictAtTip(unittest.TestCase):
    def test_fresh_go_at_tip_passes(self):
        self.assertTrue(verdict_at_tip([review(go_body(HEAD))], HEAD))

    def test_stale_go_fails(self):
        self.assertFalse(verdict_at_tip([review(go_body(OTHER))], HEAD))

    def test_no_go_fails(self):
        self.assertFalse(verdict_at_tip([review("lgtm"), review("", "COMMENTED")], HEAD))
        self.assertFalse(verdict_at_tip([], HEAD))

    def test_dismissed_go_does_not_count(self):
        self.assertFalse(verdict_at_tip([review(go_body(HEAD), state="DISMISSED")], HEAD))

    def test_short_sha_never_matches(self):
        self.assertFalse(verdict_at_tip([review(go_body(HEAD[:7]))], HEAD))
        self.assertFalse(verdict_at_tip([review(go_body(HEAD[:39] + "zz"))], HEAD))

    def test_sha_comparison_is_case_insensitive(self):
        self.assertTrue(verdict_at_tip([review(go_body(HEAD.upper()))], HEAD))

    def test_verdict_marker_is_exact_uppercase(self):
        # PR #465 review, P1: the CI job gate matches the literal `VERDICT: GO`,
        # so the parser must too — a case-insensitive parser would accept verdicts
        # CI never evaluates.
        self.assertFalse(verdict_at_tip([review(go_body(HEAD).replace("VERDICT", "verdict"))], HEAD))
        self.assertFalse(verdict_at_tip([review(go_body(HEAD).replace("GO", "go"))], HEAD))
        self.assertFalse(verdict_at_tip([review("VERDICT: GOAHEAD\nreviewed_sha: " + HEAD)], HEAD))
        self.assertFalse(verdict_at_tip([review("VERDICT: NO-GO\nreviewed_sha: " + HEAD)], HEAD))

    def test_approved_go_always_counts(self):
        self.assertTrue(verdict_at_tip([review(go_body(HEAD), state="APPROVED")], HEAD))
        self.assertFalse(verdict_at_tip(
            [review(go_body(HEAD), state="CHANGES_REQUESTED")], HEAD))
        self.assertFalse(verdict_at_tip(
            [review(go_body(HEAD), state="PENDING")], HEAD))

    def test_commented_go_counts_from_pr_author(self):
        # The coordinator binding its own verdict — the normal fleet flow, since
        # GitHub forbids approving your own PR. A SHA binding, not review: required
        # approvals stay branch protection's (module docstring). It counts because the
        # author is the OWNER: a fork author's own GO does not (W6-06, below).
        mine = review(go_body(HEAD), state="COMMENTED", login="coord",
                      association="OWNER")
        self.assertTrue(verdict_at_tip([mine], HEAD, pr_author="coord"))

    def test_commented_go_counts_from_trusted_tiers(self):
        for association in ("OWNER", "MEMBER", "COLLABORATOR"):
            with self.subTest(association=association):
                r = review(go_body(HEAD), state="COMMENTED", login="peer",
                           association=association)
                self.assertTrue(verdict_at_tip([r], HEAD, pr_author="coord"))

    def test_commented_go_from_a_stranger_never_counts(self):
        # PR #460 review, P1: COMMENTED is open to any signed-in user, so a
        # drive-by comment must never satisfy this required check.
        for association in ("CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER",
                            "NONE", None):
            with self.subTest(association=association):
                r = review(go_body(HEAD), state="COMMENTED", login="stranger",
                           association=association)
                self.assertFalse(verdict_at_tip([r], HEAD, pr_author="coord"))

    def test_missing_body_is_not_a_go(self):
        self.assertFalse(verdict_at_tip([{"state": "APPROVED"}], HEAD))
        self.assertFalse(verdict_at_tip([{"state": "APPROVED", "body": None}], HEAD))

    def test_newest_go_wins_among_several(self):
        reviews = [review(go_body(OTHER)), review(go_body(HEAD))]
        hits = go_reviews_at_tip(reviews, HEAD)
        self.assertEqual(len(hits), 1)


class GhApiUnits(unittest.TestCase):
    def _proc(self, stdout="", stderr="", code=0):
        return subprocess.CompletedProcess(["gh", "api"], code, stdout, stderr)

    def _call(self, proc, paginate=False):
        with mock.patch.object(verdict_check.subprocess, "run", return_value=proc) as m:
            result = verdict_check._gh_api("pulls/1", "o/r", paginate=paginate)
        argv = m.call_args[0][0]
        if paginate:
            self.assertEqual(argv[:4], ["gh", "api", "--paginate", "--slurp"])
        else:
            self.assertEqual(argv[:2], ["gh", "api"])
            self.assertNotIn("--paginate", argv)
        self.assertIn("repos/o/r/pulls/1", argv)
        return result

    def test_a_json_object_comes_back_parsed(self):
        self.assertEqual(self._call(self._proc('{"sha": "abc"}')), {"sha": "abc"})

    def test_empty_output_is_empty(self):
        self.assertEqual(self._call(self._proc("")), {})
        self.assertEqual(self._call(self._proc(""), paginate=True), [])

    def test_slurped_pages_are_merged(self):
        proc = self._proc('[[{"a": 1}], [{"b": 2}, {"c": 3}]]\n')
        self.assertEqual(self._call(proc, paginate=True), [{"a": 1}, {"b": 2}, {"c": 3}])

    def test_concatenated_pages_without_separators_are_merged(self):
        # Plain --paginate prints `][` with no newline between pages; a line
        # splitter read that as one malformed document.
        for text in ('[{"a": 1}][{"b": 2}]', '[{"a": 1}]\n\n[{"b": 2}]\n',
                     '[{"a": 1}, {"x": "]["}]  [{"b": 2}]'):
            with self.subTest(text=text):
                got = self._call(self._proc(text), paginate=True)
                self.assertEqual(got[0], {"a": 1})
                self.assertEqual(got[-1], {"b": 2})

    def test_garbage_raises_instead_of_reading_as_no_reviews(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._call(self._proc('[{"a": 1}] trailing'), paginate=True)
        self.assertIn("unparseable", str(ctx.exception))
        with self.assertRaises(RuntimeError):
            self._call(self._proc('{"a": 1}{"b": 2}'))
        with self.assertRaises(RuntimeError):
            self._call(self._proc('{"a": 1}'), paginate=True)

    def test_a_nonzero_exit_raises_with_the_stderr(self):
        with mock.patch.object(verdict_check.subprocess, "run",
                               return_value=self._proc("", "Not Found", 1)):
            with self.assertRaises(RuntimeError) as ctx:
                verdict_check._gh_api("pulls/1", "o/r")
        self.assertIn("gh api pulls/1 failed: Not Found", str(ctx.exception))


class CheckPrUnits(unittest.TestCase):
    PR = {"head": {"sha": HEAD}, "user": {"login": "coord"}}

    def _check(self, pr_payload, reviews_payload):
        def fake(path, repo, paginate=False):
            self.assertEqual(repo, "o/r")
            # Only the LIST endpoint paginates; the PR object is one document.
            self.assertEqual(paginate, path != "pulls/7")
            return pr_payload if path == "pulls/7" else reviews_payload
        with mock.patch.object(verdict_check, "_gh_api", side_effect=fake):
            return verdict_check.check_pr("7", "o/r")

    def test_head_author_reviews_and_hits_come_back_wired(self):
        reviews = [review(go_body(HEAD)), review("lgtm")]
        head, got, hits, author = self._check(dict(self.PR), reviews)
        self.assertEqual(head, HEAD)
        self.assertEqual(got, reviews)
        self.assertEqual(len(hits), 1)
        self.assertEqual(author, "coord")

    def test_a_paginated_single_object_response_unwraps(self):
        head, _got, hits, _author = self._check([dict(self.PR)], [review(go_body(HEAD))])
        self.assertEqual(head, HEAD)
        self.assertEqual(len(hits), 1)

    def test_an_empty_pr_payload_reads_as_no_head(self):
        head, _got, hits, author = self._check([], [])
        self.assertEqual(head, "")
        self.assertEqual(hits, [])
        self.assertEqual(author, "")

    def test_a_non_list_reviews_payload_reads_as_no_reviews(self):
        _head, got, hits, _author = self._check(dict(self.PR), {"message": "odd"})
        self.assertEqual(got, [])
        self.assertEqual(hits, [])


class MainInProc(unittest.TestCase):
    def _main(self, argv, payload=None, error=None):
        def fake(pr_number, repo):
            self.assertEqual(repo, "o/r")
            if error is not None:
                raise error
            return payload
        out, err = io.StringIO(), io.StringIO()
        # These cases are about the verdict: the PR changes no grader path (W6-01 has its own).
        no_grader_change = mock.patch.object(verdict_check, "grader_refusal",
                                             return_value=([], None))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), no_grader_change:
            with mock.patch.object(verdict_check, "check_pr", side_effect=fake):
                code = verdict_check.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _payload(self, reviews):
        return (HEAD, reviews,
                verdict_check.go_reviews_at_tip(reviews, HEAD, "coord"), "coord")

    def test_a_go_at_tip_passes_and_names_the_author(self):
        code, out, err = self._main(["--pr", "7", "--repo", "o/r"],
                                    self._payload([review(go_body(HEAD))]))
        self.assertEqual(code, 0, err)
        self.assertIn("1 trusted at tip", out)
        self.assertIn("@reviewer [APPROVED]", out)
        self.assertIn("PASS", out)

    def test_a_stale_go_fails_asking_for_a_fresh_verdict(self):
        code, _out, err = self._main(["--pr", "7", "--repo", "o/r"],
                                     self._payload([review(go_body(OTHER))]))
        self.assertEqual(code, 1)
        self.assertIn("none binds the current head", err)

    def test_an_untrusted_go_fails_as_a_drive_by(self):
        stranger = review(go_body(HEAD), state="COMMENTED", login="stranger",
                          association="NONE")
        code, _out, err = self._main(["--pr", "7", "--repo", "o/r"],
                                     self._payload([stranger]))
        self.assertEqual(code, 1)
        self.assertIn("drive-by", err)

    def test_no_go_at_all_fails_plainly(self):
        code, _out, err = self._main(["--pr", "7", "--repo", "o/r"], self._payload([]))
        self.assertEqual(code, 1)
        self.assertIn("no GO verdict review", err)

    def test_a_missing_repo_is_a_usage_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code, _out, err = self._main(["--pr", "7"], self._payload([]))
        self.assertEqual(code, 2)
        self.assertIn("need --repo", err)

    def test_a_malformed_repo_is_a_usage_error(self):
        code, _out, err = self._main(["--pr", "7", "--repo", "noslash"], self._payload([]))
        self.assertEqual(code, 2)
        self.assertIn("need --repo", err)

    def test_the_repo_defaults_to_the_environment(self):
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r"}):
            code, _out, err = self._main(["--pr", "7"], self._payload([]))
        self.assertEqual(code, 1, err)  # parsed the env repo, then failed on no GO

    def test_an_api_failure_is_exit_2(self):
        code, _out, err = self._main(["--pr", "7", "--repo", "o/r"],
                                     error=RuntimeError("gh api down"))
        self.assertEqual(code, 2)
        self.assertIn("gh api down", err)

    def test_a_missing_pr_number_exits_2_through_system_exit(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                verdict_check.main(["--repo", "o/r"])
        self.assertEqual(ctx.exception.code, 2)

    def test_the_module_entry_point_rejects_a_missing_pr(self):
        argv = ["verdict_check.py", "--repo", "o/r"]
        with contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(sys, "argv", argv):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(str(_ROOT / "scripts" / "verdict_check.py"),
                                   run_name="__main__")
        self.assertEqual(ctx.exception.code, 2)


class PostStatusGate(unittest.TestCase):
    """--post-status is the authoritative gate (verdict-gate.yml): the verdict becomes a
    commit status on the PR's current head, and the exit code says whether it was posted."""

    OTHER_PR = {"number": 9, "head": {"sha": "c" * 40}}

    def _run(self, argv, reviews, pulls=None, post_rc=0):
        posted = []

        def fake_api(path, repo, paginate=False):
            self.assertEqual(repo, "o/r")
            if path.startswith("pulls?"):
                return pulls or []
            if path == "pulls/7":
                return {"number": 7, "head": {"sha": HEAD, "repo": {"full_name": "o/r"}},
                        "base": {"sha": OTHER, "repo": {"full_name": "o/r"}},
                        "user": {"login": "coord"}}
            return reviews

        def fake_run(cmd, **_kw):
            posted.append(cmd)
            return subprocess.CompletedProcess(cmd, post_rc, "", "denied" if post_rc else "")

        out, err = io.StringIO(), io.StringIO()
        env = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_RUN_ID": "42"}
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.dict(os.environ, env), \
                mock.patch.object(verdict_check, "_gh_api", side_effect=fake_api), \
                mock.patch.object(verdict_check.subprocess, "run", side_effect=fake_run):
            code = verdict_check.main(argv + ["--repo", "o/r"])
        return code, posted, out.getvalue() + err.getvalue()

    def _fields(self, cmd):
        return dict(cmd[i + 1].split("=", 1) for i, a in enumerate(cmd) if a == "-f")

    def test_a_go_at_tip_posts_success_on_the_head(self):
        code, posted, _ = self._run(["--pr", "7", "--post-status"], [review(go_body(HEAD))])
        self.assertEqual(code, 0)
        self.assertEqual(len(posted), 1)
        self.assertIn(f"repos/o/r/statuses/{HEAD}", posted[0])
        fields = self._fields(posted[0])
        self.assertEqual((fields["state"], fields["context"]), ("success", "verdict-gate"))
        self.assertEqual(fields["target_url"], "https://github.com/o/r/actions/runs/42")

    def test_no_go_posts_failure_and_still_exits_zero(self):
        # The status IS the verdict; a red run on the default branch for every
        # unverdicted review would be noise, so the exit code reports the post.
        code, posted, _ = self._run(["--pr", "7", "--post-status"], [review(go_body(OTHER))])
        self.assertEqual(code, 0)
        fields = self._fields(posted[0])
        self.assertEqual(fields["state"], "failure")
        self.assertIn("none binds the current head", fields["description"])
        self.assertLessEqual(len(fields["description"]), 140)

    def test_a_custom_context_is_honoured(self):
        _code, posted, _ = self._run(["--pr", "7", "--post-status", "gate-x"], [])
        self.assertEqual(self._fields(posted[0])["context"], "gate-x")

    def test_a_failed_post_is_exit_2(self):
        code, _posted, out = self._run(["--pr", "7", "--post-status"], [], post_rc=1)
        self.assertEqual(code, 2)
        self.assertIn("denied", out)

    def test_without_post_status_nothing_is_posted(self):
        code, posted, _ = self._run(["--pr", "7"], [])
        self.assertEqual((code, posted), (1, []))

    def test_head_sha_finds_the_one_open_pr_at_that_head(self):
        pulls = [self.OTHER_PR, {"number": 7, "head": {"sha": HEAD.upper()}}]
        code, posted, out = self._run(["--head-sha", HEAD, "--post-status"],
                                      [review(go_body(HEAD))], pulls=pulls)
        self.assertEqual(code, 0, out)
        self.assertIn("PR #7", out)
        self.assertEqual(self._fields(posted[0])["state"], "success")

    def test_head_sha_with_no_or_several_prs_posts_nothing(self):
        for pulls in ([], [{"number": 7, "head": {"sha": HEAD}},
                           {"number": 8, "head": {"sha": HEAD}}]):
            with self.subTest(n=len(pulls)):
                code, posted, out = self._run(["--head-sha", HEAD, "--post-status"], [],
                                              pulls=pulls)
                self.assertEqual((code, posted), (2, []))
                self.assertIn("exactly one", out)

    def test_a_short_head_sha_is_refused(self):
        code, posted, out = self._run(["--head-sha", "abc123", "--post-status"], [])
        self.assertEqual((code, posted), (2, []))
        self.assertIn("full 40-hex", out)

    def test_resolve_pr_prints_the_number_and_posts_nothing(self):
        pulls = [{"number": 7, "head": {"sha": HEAD}}]
        code, posted, out = self._run(["--head-sha", HEAD, "--resolve-pr"], [], pulls=pulls)
        self.assertEqual((code, posted), (0, []))
        self.assertEqual(out.strip(), "7")

    def test_resolve_pr_refuses_a_numberless_match_and_needs_head_sha(self):
        code, _posted, out = self._run(["--head-sha", HEAD, "--resolve-pr"], [],
                                       pulls=[{"number": None, "head": {"sha": HEAD}}])
        self.assertEqual(code, 2)
        self.assertIn("no usable number", out)
        code, _posted, out = self._run(["--pr", "7", "--resolve-pr"], [])
        self.assertEqual(code, 2)
        self.assertIn("needs --head-sha", out)

    def test_pr_and_head_sha_are_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                verdict_check.main(["--pr", "7", "--head-sha", HEAD, "--repo", "o/r"])
        self.assertEqual(ctx.exception.code, 2)


class TheGateRunsOnlyDefaultBranchCode(unittest.TestCase):
    """verdict-gate.yml is the required check: nothing the PR under review can edit may run
    in it, runs for one PR must post in order, and its status must come from an identity a
    fork PR or a writer's branch workflow cannot mint."""

    TEXT = (_ROOT / ".github" / "workflows" / "verdict-gate.yml").read_text(encoding="utf-8")
    TRIGGER = (_ROOT / ".github" / "workflows" / "verdict-check.yml").read_text(encoding="utf-8")

    def _job(self, name):
        jobs = "\n" + self.TEXT.split("\njobs:\n", 1)[1]
        body = jobs.split(f"\n  {name}:\n", 1)[1]
        return body.split("\n  gate:\n", 1)[0] if name == "resolve" else body

    def test_it_runs_only_on_workflow_run_of_verdict_check(self):
        on = self.TEXT.split("\non:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(on, "  workflow_run:\n    workflows: [verdict-check]\n"
                             "    types: [completed]")
        # a dispatch loads the workflow from whichever branch is picked (PR #572 review)
        self.assertNotIn("workflow_dispatch", self.TEXT.split("\nname:", 1)[1])

    def test_every_checkout_is_the_default_branch_checker_alone(self):
        checkouts = self.TEXT.split("actions/checkout@")[1:]
        self.assertEqual(len(checkouts), 2)
        for block in checkouts:
            head = block.split("- uses:", 1)[0]
            self.assertIn("ref: ${{ github.sha }}", head)
            self.assertIn("sparse-checkout: scripts/verdict_check.py", head)
            self.assertIn("persist-credentials: false", head)
        self.assertNotRegex(self.TEXT, r"ref:\s*\$\{\{\s*github\.event\.workflow_run\.head")
        self.assertNotIn("pull_request.head", self.TEXT)

    def test_resolve_names_the_pr_through_the_default_branch_script(self):
        job = self._job("resolve")
        self.assertIn("--head-sha \"$RUN_HEAD_SHA\" --resolve-pr", job)
        self.assertIn("*[!0-9]*", job)  # only a number reaches the lock and the gate
        self.assertNotIn("statuses: write", job)

    def test_gate_serialises_per_pr_and_posts_through_the_default_branch_script(self):
        job = self._job("gate")
        self.assertIn("needs: resolve", job)
        self.assertIn("group: verdict-gate-pr-${{ needs.resolve.outputs.pr }}", job)
        self.assertIn("cancel-in-progress: false", job)
        self.assertIn('python3 scripts/verdict_check.py --post-status --pr "$PR_NUMBER"', job)
        self.assertEqual(verdict_check.STATUS_CONTEXT, "verdict-gate")

    def test_permissions_are_per_job_and_only_the_gate_writes_statuses(self):
        self.assertRegex(self.TEXT, r"(?m)^permissions: \{\}$")
        self.assertEqual(len(re.findall(r"(?m)^ +statuses: write$", self.TEXT)), 1)
        self.assertIn("    permissions:\n      contents: read\n      pull-requests: read\n"
                      "      statuses: write\n", self._job("gate"))

    def test_the_app_key_lives_in_the_branch_restricted_environment(self):
        job = self._job("gate")
        self.assertIn("environment: verdict-gate", job)
        self.assertIn("if: vars.VERDICT_GATE_CLIENT_ID != ''", job)
        self.assertRegex(job, r"actions/create-github-app-token@[0-9a-f]{40} # v")
        self.assertIn("steps.app.outputs.token || secrets.GITHUB_TOKEN", job)
        self.assertIn("::warning::verdict-gate posts as github-actions", job)
        self.assertNotIn("VERDICT_GATE_PRIVATE_KEY", self._job("resolve"))

    def test_the_trigger_always_completes_a_run(self):
        # A `relay` job with no `if:` — every review, GO or not, wakes the gate.
        jobs = self.TRIGGER.split("\njobs:\n", 1)[1]
        relay = jobs.split("\n  verdict:\n", 1)[0]
        self.assertIn("  relay:\n", relay)
        self.assertNotIn("if:", relay)


class WorkflowRunsTheBaseChecker(unittest.TestCase):
    """verdict-check.yml must never run a checker the PR under review could rewrite."""

    TEXT = (_ROOT / ".github" / "workflows" / "verdict-check.yml").read_text(encoding="utf-8")

    def test_the_checker_is_checked_out_from_the_base_sha_into_its_own_path(self):
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}", self.TEXT)
        self.assertIn("path: base-checker", self.TEXT)
        self.assertIn("python3 base-checker/scripts/verdict_check.py", self.TEXT)
        # exactly one checkout, and it is the base one — no PR tree on disk at all
        self.assertEqual(self.TEXT.count("actions/checkout@"), 1)
        self.assertNotRegex(self.TEXT, r"(?m)^\s+run: python3 scripts/verdict_check\.py")

    def test_permissions_are_read_only_and_explicit(self):
        self.assertRegex(self.TEXT,
                         r"(?m)^permissions:\n  contents: read\n  pull-requests: read\n")

    def test_the_trigger_gate_mirrors_the_scripts_trust_tiers(self):
        # The PR author's GO-marker review still triggers evaluation: the owner's self-GO
        # counts, and a fork author sees theirs refused (W6-06).
        self.assertIn(
            "github.event.review.user.login == github.event.pull_request.user.login",
            self.TEXT)



class AContradictedGoIsNotAGo(unittest.TestCase):
    """2026-10-23 review, §5: `VERDICT: GO` followed by `VERDICT: NO-GO` in one review body read
    as GO — the first GO line won. Any non-GO verdict line voids the review (fail closed)."""

    def test_go_then_no_go_is_not_a_go(self):
        body = f"VERDICT: GO\nreviewed_sha: {HEAD}\n\nOn reflection:\nVERDICT: NO-GO\n"
        self.assertFalse(verdict_at_tip([review(body)], HEAD))
        self.assertFalse(verdict_at_tip([review(body, state="COMMENTED", association="OWNER")], HEAD))

    def test_no_go_then_go_is_not_a_go_either(self):
        body = f"VERDICT: NO-GO\nreviewed_sha: {HEAD}\nVERDICT: GO\n"
        self.assertFalse(verdict_at_tip([review(body)], HEAD))

    def test_any_other_verdict_line_voids_the_review(self):
        for other in ("VERDICT: HOLD", "  VERDICT: GO-ISH", "VERDICT:"):
            body = go_body(HEAD) + other + "\n"
            with self.subTest(other=other):
                self.assertFalse(verdict_at_tip([review(body)], HEAD))

    def test_a_repeated_go_is_still_a_go(self):
        self.assertTrue(verdict_at_tip([review(go_body(HEAD) + "VERDICT: GO\n")], HEAD))


class AForkAuthorCannotGoTheirOwnPr(unittest.TestCase):
    """2026-10-27 security audit, W6-06: a COMMENTED GO from the PR author counted whoever the
    author was, so a fork author could post `VERDICT: GO` on their own head and turn the last
    required context green. The author's own GO is a SHA binding only from a trusted account."""

    def test_a_fork_authors_self_go_never_counts(self):
        for association in ("CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE", None):
            with self.subTest(association=association):
                mine = review(go_body(HEAD), state="COMMENTED", login="forker",
                              association=association)
                self.assertFalse(verdict_at_tip([mine], HEAD, pr_author="forker"))

    def test_an_approved_go_from_an_untrusted_account_never_counts(self):
        # PR #718 review (Codex, P1): any GitHub account can submit an APPROVED review on a public
        # repository; it only fails to count toward native required reviews. The state proves
        # nothing about the author, so APPROVED passes the same trust tiers as COMMENTED.
        for association in ("NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", None):
            for login, pr_author in (("outsider", "coord"), ("forker", "forker")):
                with self.subTest(association=association, login=login):
                    approved = review(go_body(HEAD), state="APPROVED", login=login,
                                      association=association)
                    self.assertFalse(verdict_at_tip([approved], HEAD, pr_author=pr_author))

    def test_the_gate_reports_an_untrusted_approval_as_untrusted(self):
        pr = {"number": 7, "head": {"sha": HEAD}, "user": {"login": "coord"},
              "author_association": "OWNER", "changed_files": 0}
        approved = review(go_body(HEAD), state="APPROVED", login="outsider", association="NONE")

        def fake_api(path, repo, paginate=False):
            return {"pulls/7": pr, "pulls/7/reviews": [approved]}.get(path, [])

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(verdict_check, "_gh_api", side_effect=fake_api):
            code = verdict_check.main(["--pr", "7", "--repo", "o/r"])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("untrusted", err.getvalue())

    def test_the_owners_self_go_still_binds(self):
        mine = review(go_body(HEAD), state="COMMENTED", login="ravidsrk", association="OWNER")
        self.assertTrue(verdict_at_tip([mine], HEAD, pr_author="ravidsrk"))

    def test_the_gate_reports_a_self_go_from_a_fork_as_untrusted(self):
        pr = {"number": 7, "head": {"sha": HEAD}, "user": {"login": "forker"},
              "author_association": "CONTRIBUTOR", "changed_files": 0}
        mine = review(go_body(HEAD), state="COMMENTED", login="forker", association="CONTRIBUTOR")

        def fake_api(path, repo, paginate=False):
            return {"pulls/7": pr, "pulls/7/reviews": [mine]}.get(path, [])

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(verdict_check, "_gh_api", side_effect=fake_api):
            code = verdict_check.main(["--pr", "7", "--repo", "o/r"])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("untrusted", err.getvalue())


class TheLatestTrustedVerdictAtTheHeadDecides(unittest.TestCase):
    """PR #718 re-attack (W6-06): a trusted NO-GO did not veto. An owner's CHANGES_REQUESTED, or a
    `VERDICT: NO-GO` bound to the same head, posted after a GO left the gate green. The latest
    trusted verdict bound to the head decides: a later NO-GO blocks, a later GO clears it."""

    @staticmethod
    def at(body, when, state="COMMENTED", association="OWNER", login="o", commit=HEAD):
        r = review(body, state=state, login=login, association=association)
        r["submitted_at"], r["commit_id"] = when, commit
        return r

    GO = staticmethod(lambda when, **kw: TheLatestTrustedVerdictAtTheHeadDecides.at(
        go_body(HEAD), when, **kw))
    NO_GO = f"Not yet.\n\nVERDICT: NO-GO\nreviewed_sha: {HEAD}\n"

    def test_a_later_trusted_no_go_blocks(self):
        for later in (self.at(self.NO_GO, "2026-10-27T02:00:00Z"),
                      self.at("Needs work.", "2026-10-27T02:00:00Z", state="CHANGES_REQUESTED"),
                      self.at("VERDICT: NO-GO\n", "2026-10-27T02:00:00Z"),  # bound by commit_id
                      self.at(self.NO_GO, "2026-10-27T02:00:00Z", state="APPROVED",
                              association="MEMBER", login="peer")):
            with self.subTest(later=later["body"], state=later["state"]):
                reviews = [self.GO("2026-10-27T01:00:00Z"), later]
                self.assertFalse(verdict_at_tip(reviews, HEAD, pr_author="o"))

    def test_a_later_go_clears_a_no_go(self):
        reviews = [self.at(self.NO_GO, "2026-10-27T01:00:00Z"),
                   self.at("Needs work.", "2026-10-27T01:30:00Z", state="CHANGES_REQUESTED"),
                   self.GO("2026-10-27T02:00:00Z")]
        self.assertTrue(verdict_at_tip(reviews, HEAD, pr_author="o"))

    def test_only_a_trusted_verdict_at_this_head_can_veto(self):
        go = self.GO("2026-10-27T01:00:00Z")
        for later in (
                self.at(self.NO_GO, "2026-10-27T02:00:00Z", association="NONE", login="x"),
                self.at("Needs work.", "2026-10-27T02:00:00Z", state="CHANGES_REQUESTED",
                        association="CONTRIBUTOR", login="x"),
                self.at(self.NO_GO.replace(HEAD, OTHER), "2026-10-27T02:00:00Z"),
                self.at("Needs work.", "2026-10-27T02:00:00Z", state="CHANGES_REQUESTED",
                        commit=OTHER),
                self.at("Needs work.", "2026-10-27T02:00:00Z", state="DISMISSED"),
                self.at("A comment, no verdict.", "2026-10-27T02:00:00Z")):
            with self.subTest(later=later["body"], state=later["state"]):
                self.assertTrue(verdict_at_tip([go, later], HEAD, pr_author="o"))

    def test_the_gate_names_the_veto(self):
        pr = {"number": 7, "head": {"sha": HEAD}, "user": {"login": "o"},
              "author_association": "OWNER", "changed_files": 0}
        reviews = [self.GO("2026-10-27T01:00:00Z"), self.at(self.NO_GO, "2026-10-27T02:00:00Z")]

        def fake_api(path, repo, paginate=False):
            return {"pulls/7": pr, "pulls/7/reviews": reviews}.get(path, [])

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(verdict_check, "_gh_api", side_effect=fake_api), \
                mock.patch.object(verdict_check, "grader_refusal", return_value=([], None)):
            code = verdict_check.main(["--pr", "7", "--repo", "o/r"])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("NO-GO", err.getvalue())


class APrCannotChangeItsOwnGrader(unittest.TestCase):
    """2026-10-27 security audit, W6-01 (P1): a `pull_request` run loads its workflow from the
    PR's merge ref, so a fork PR that empties the `gates`, `guard` and `pinned-demo` jobs gets
    three green required contexts with nothing checked. `verdict-gate` is the one required
    context whose code comes from the default branch; it now refuses a PR that changes the
    grader unless the repository owner wrote it."""

    OWNER_GO = review(go_body(HEAD), state="COMMENTED", login="o", association="OWNER")

    def _pr(self, login="forker", association="CONTRIBUTOR", changed=None, head=HEAD):
        pr = {"number": 7, "head": {"sha": head}, "user": {"login": login},
              "author_association": association}
        if changed is not None:
            pr["changed_files"] = changed
        return pr

    def _run(self, files, pr=None, pr_after=None, post=True, reviews=None):
        pr = pr or self._pr(changed=len(files))
        seen = {"pulls/7": 0}
        posted = []

        def fake_api(path, repo, paginate=False):
            self.assertEqual(repo, "o/r")
            if path == "pulls/7":
                seen["pulls/7"] += 1
                return pr if seen["pulls/7"] == 1 or pr_after is None else pr_after
            if path == "pulls/7/reviews":
                self.assertTrue(paginate)
                return [self.OWNER_GO] if reviews is None else reviews
            if path.startswith("pulls/7/files"):
                self.assertTrue(paginate, "the files list is paginated")
                return files
            self.fail(f"unexpected API path {path}")

        def fake_run(cmd, **_kw):
            posted.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        argv = ["--pr", "7", "--repo", "o/r"] + (["--post-status"] if post else [])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(verdict_check, "_gh_api", side_effect=fake_api), \
                mock.patch.object(verdict_check.subprocess, "run", side_effect=fake_run):
            code = verdict_check.main(argv)
        fields = (dict(c[i + 1].split("=", 1) for i, a in enumerate(c) if a == "-f")
                  for c in posted)
        return code, list(fields), out.getvalue() + err.getvalue()

    @staticmethod
    def _files(*names, status="modified"):
        return [{"filename": n, "status": status} for n in names]

    def test_a_fork_pr_that_edits_a_workflow_is_refused_even_with_a_go(self):
        for path in (".github/workflows/validate.yml", ".github/workflows/guard.yml",
                     ".github/workflows/new-gate.yml", ".github/actions/setup/action.yml",
                     ".github/ci-tools.lock"):
            with self.subTest(path=path):
                code, posted, out = self._run(self._files("scripts/x.py", path))
                self.assertEqual(code, 0, out)  # --post-status: the status IS the verdict
                self.assertEqual(len(posted), 1)
                self.assertEqual(posted[0]["state"], "failure", out)
                self.assertIn("grader", posted[0]["description"])
                self.assertLessEqual(len(posted[0]["description"]), 140)
                self.assertIn(path, out)

    def test_without_post_status_the_refusal_is_exit_1(self):
        code, posted, out = self._run(self._files(".github/workflows/validate.yml"), post=False)
        self.assertEqual((code, posted), (1, []))
        self.assertIn("grader", out)

    def test_a_removed_or_renamed_workflow_is_a_grader_change(self):
        for files in (self._files(".github/workflows/negative-control.yml", status="removed"),
                      [{"filename": "docs/old-gate.yml", "status": "renamed",
                        "previous_filename": ".github/workflows/guard.yml"}],
                      [{"filename": ".github/workflows/guard.yml", "status": "renamed",
                        "previous_filename": "docs/guard.yml"}]):
            with self.subTest(files=files):
                _code, posted, out = self._run(files)
                self.assertEqual(posted[0]["state"], "failure", out)

    def test_the_owners_pr_may_change_the_grader(self):
        files = self._files(".github/workflows/validate.yml", ".github/ci-tools.lock")
        for login, association in (("o", "OWNER"), ("O", "CONTRIBUTOR"), ("someone", "OWNER")):
            with self.subTest(login=login, association=association):
                pr = self._pr(login=login, association=association, changed=len(files))
                _code, posted, out = self._run(files, pr=pr)
                self.assertEqual(posted[0]["state"], "success", out)

    def test_a_collaborator_is_not_the_owner(self):
        files = self._files(".github/workflows/validate.yml")
        for association in ("MEMBER", "COLLABORATOR"):
            with self.subTest(association=association):
                pr = self._pr(login="peer", association=association, changed=1)
                _code, posted, out = self._run(files, pr=pr)
                self.assertEqual(posted[0]["state"], "failure", out)

    def test_a_pr_that_leaves_the_grader_alone_passes_on_its_go(self):
        files = self._files("scripts/x.py", "tests/test_x.py", ".github/CONTRIBUTING.md",
                            ".github/CODEOWNERS", "docs/.github/workflows/x.yml",
                            ".github/workflows-notes.md")
        _code, posted, out = self._run(files)
        self.assertEqual(posted[0]["state"], "success", out)

    def test_a_files_list_that_may_be_truncated_is_refused(self):
        # GitHub lists at most 3000 files; a grader change past the cut must not hide.
        few = self._files("scripts/x.py")
        _code, posted, out = self._run(few, pr=self._pr(changed=2))
        self.assertEqual(posted[0]["state"], "failure", out)
        self.assertIn("files", posted[0]["description"])
        many = self._files(*(f"docs/f{i}.md" for i in range(3000)))
        _code, posted, out = self._run(many, pr=self._pr())
        self.assertEqual(posted[0]["state"], "failure", out)

    def test_a_head_that_moves_during_the_evaluation_is_refused(self):
        moved = self._pr(changed=1, head=OTHER)
        _code, posted, out = self._run(self._files("scripts/x.py"), pr_after=moved)
        self.assertEqual(posted[0]["state"], "failure", out)
        self.assertIn("moved", posted[0]["description"])

    def test_the_grader_refusal_outranks_a_missing_go(self):
        _code, posted, out = self._run(self._files(".github/workflows/validate.yml"),
                                       reviews=[])
        self.assertEqual(posted[0]["state"], "failure")
        self.assertIn("grader", posted[0]["description"])

    def test_the_gate_job_can_read_the_files_list(self):
        # The files endpoint needs Pull requests: read, which the gate's app token carries.
        gate = (_ROOT / ".github" / "workflows" / "verdict-gate.yml").read_text(encoding="utf-8")
        self.assertIn("permission-pull-requests: read", gate)


if __name__ == "__main__":
    unittest.main()
