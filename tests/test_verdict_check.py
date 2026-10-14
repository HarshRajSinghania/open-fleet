"""Tests for scripts/verdict_check.py (#452): GO-at-tip verdict rule."""

import contextlib
import importlib.util
import io
import os
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
        # approvals stay branch protection's (module docstring).
        mine = review(go_body(HEAD), state="COMMENTED", login="coord",
                      association="CONTRIBUTOR")
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
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
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
        # A self-GO counts (SHA binding), so it must trigger evaluation too.
        self.assertIn(
            "github.event.review.user.login == github.event.pull_request.user.login",
            self.TEXT)


if __name__ == "__main__":
    unittest.main()
