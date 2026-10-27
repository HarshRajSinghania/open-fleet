#!/usr/bin/env python3
"""Repo-hygiene contracts (#300).

Three unrelated findings from the supply-chain pass, each a file rather than code, and each
easy to undo silently in a later edit. The assertions are about the FILES, so they hold whoever
changes them next.
"""
import ast
import contextlib
import importlib.util
import io
import os
import re
import sys
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


class RuntimeStateIsNotCommittable(unittest.TestCase):
    """`.orca/` is the Orca runtime's working directory, not repository content.

    egress.py defaults its ledger to `.orca/egress.jsonl` at mode 0600 and the dispatch key
    lives there too, so an unignored `.orca/` lets a worker commit runtime state — a private
    key among it — by accident.
    """

    def _ignored(self, rel):
        r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT)
        return r.returncode == 0

    def test_the_runtime_working_directory_is_ignored(self):
        for rel in (".orca/", ".orca/egress.jsonl", ".orca/keys/dispatch.key",
                    ".orca/anything/nested/deep.json"):
            with self.subTest(path=rel):
                self.assertTrue(self._ignored(rel), f"{rel} would be committable")

    def test_the_ignore_matches_the_path_the_code_actually_uses(self):
        # The rule is only worth anything if it covers the default the runtime writes to.
        egress = (ROOT / "runtime" / "scripts" / "egress.py").read_text(encoding="utf-8")
        m = re.search(r'^DEFAULT_LEDGER = "([^"]+)"', egress, re.M)
        self.assertIsNotNone(m, "egress.py no longer declares DEFAULT_LEDGER")
        self.assertTrue(self._ignored(m.group(1)),
                        f"egress.py writes {m.group(1)} and .gitignore does not cover it")

    def test_the_public_key_is_still_committable(self):
        """The one thing in `.orca/` that MUST be commitable — and the first cut broke it.

        Committing `.orca/dispatch-pubkey` is what turns dispatch-signature enforcement on
        (dispatch-sign.py:127). A blanket `.orca/` swept it up, and test_dispatch_sign.py said
        so; this is the same contract stated from the ignore rule's side, because the two are
        easy to change independently.
        """
        self.assertFalse(self._ignored(".orca/dispatch-pubkey"),
                         "the pubkey is ignored — signature enforcement can no longer be "
                         "turned on by committing it")
        self.assertFalse(self._ignored(".orca/human-grant-pubkey"),
                         "the human grant pubkey is ignored — signed one-way grants "
                         "can no longer be turned on by committing it")

    def test_the_rule_excludes_contents_so_the_exception_can_work(self):
        # `.orca/` would read more naturally and would NOT work: git never descends into an
        # excluded directory, so a `!` negation under one is dead. `.orca/*` is what makes the
        # pubkey exception above possible. Same idiom as `.secrets/*` + `!.secrets/*.pub`.
        rules = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
                 if ln.strip().startswith((".orca", "!.orca"))]
        self.assertEqual(rules, [".orca/*", "!.orca/dispatch-pubkey",
                                 "!.orca/human-grant-pubkey"],
                         "the runtime-state rule changed shape — a bare `.orca/` would make "
                         "the pubkey exception silently inert")

    def test_ordinary_repository_paths_are_still_tracked(self):
        for rel in ("runtime/scripts/egress.py", "skills/prove-it/SKILL.md", "README.md"):
            with self.subTest(path=rel):
                self.assertFalse(self._ignored(rel), f"{rel} was swept up by an ignore rule")


class EveryScriptCompilesWithoutWarnings(unittest.TestCase):
    """A SyntaxWarning is a future SyntaxError, and CI was printing two of them.

    `run_report.py` had `\\S` inside plain docstrings, which Python flags as an invalid escape
    sequence. Local runs never showed it — a cached .pyc does not recompile — so it only appeared
    in the CI log, where every file is compiled fresh. Python has announced these become errors.
    """

    def _compile_warnings(self, files):
        import py_compile
        import tempfile
        import warnings
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "c.pyc")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                for f in files:
                    py_compile.compile(str(f), cfile=out, doraise=False)
                return [f"{Path(f).name}: {w.category.__name__}: {w.message}" for w in caught]

    def test_the_compile_check_can_actually_see_a_warning(self):
        """Without this the check is a tautology on a clean tree.

        A mutant replacing `assertEqual(found, [])` with `assertEqual([], [])` survived, because
        both are true when nothing warns — the same vacuity the stdlib-import guard above had.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad_escape.py"
            bad.write_text('"""a docstring with \\S in it"""\n', encoding="utf-8")
            self.assertTrue(self._compile_warnings([bad]),
                            "the compile scan cannot see an invalid escape sequence")
            good = Path(tmp) / "good_escape.py"
            good.write_text('r"""a raw docstring with \\S in it"""\n', encoding="utf-8")
            self.assertEqual(self._compile_warnings([good]), [],
                             "the compile scan flags a raw string that is perfectly legal")

    def test_no_source_file_compiles_with_a_warning(self):
        roots = ("scripts", "runtime/scripts", "tests", "bench", "evals/demo")
        files = [f for r in roots for f in sorted((ROOT / r).rglob("*.py"))
                 if "__pycache__" not in f.parts]
        self.assertGreater(len(files), 40, "the scan found almost no sources to compile")
        self.assertEqual(self._compile_warnings(files), [],
                         "these are future SyntaxErrors, and CI prints them today")


class TheSecretWaiverCarriesIdentityNotContent(unittest.TestCase):
    """A waiver needs the finding's fingerprint, not the finding.

    The `--baseline-path` baseline this replaced embedded each finding's commit message, author
    name and e-mail address. Measured before switching: gitleaks 8.30.1 compares Email, Author,
    Date, Message, Entropy, Description and Commit when matching a baseline entry, so deleting
    those fields stops a baseline suppressing anything at all. `.gitleaksignore` matches on the
    fingerprint alone, which is why the switch is the fix rather than a trim.
    """

    IGNORE = ROOT / ".gitleaksignore"
    # <40-hex commit>:<path>:<rule-id>:<line>
    FINGERPRINT = re.compile(r"^[0-9a-f]{40}:[^:]+:[A-Za-z0-9._-]+:\d+$")

    def _lines(self):
        text = self.IGNORE.read_text(encoding="utf-8")
        return [ln.strip() for ln in text.splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")]

    def test_the_baseline_that_carried_content_is_gone(self):
        self.assertFalse((ROOT / ".gitleaks-baseline.json").exists(),
                         "the content-carrying baseline is back")

    # The exact set. Widening is the dangerous direction — one more line here silences a real
    # finding with nothing to show for it — and narrowing turns CI red rather than silent, so
    # pinning both ends is what makes this file reviewable at a glance.
    #
    # 2026-09-16 addition (PR #461, owner decision on the waiver the harden-it campaign run
    # parked in 111af419): the run's transcript quotes the AWS-doc fixture key and the
    # api_key fixture string in its own scan capture. Byte-inspected fixtures, nothing live,
    # nothing rotated; gitleaks detect scans every ref in the clone, so these fired on all
    # PRs once the campaign archive branches were pushed.
    WAIVED = {
        "03e481a106bea9dbe124fd5b5181d5769e28061f:tests/test_decisions.py:generic-api-key:111",
        "03e481a106bea9dbe124fd5b5181d5769e28061f:tests/test_decisions.py:aws-access-token:102",
        "03e481a106bea9dbe124fd5b5181d5769e28061f:tests/test_decisions.py:aws-access-token:115",
        "57760b66a8f8e282bb6ff5a8afa4a7661dd6701a:docs/runs/campaign-2026-09-16-harden-it/ADDENDUM-gitleaks-waiver.md:generic-api-key:17",
        "f0c83cb1f1aa099206058f15570706f90482414e:docs/runs/campaign-2026-09-16-harden-it/receipts/gitleaks-audit.json:generic-api-key:50",
        "f0c83cb1f1aa099206058f15570706f90482414e:docs/runs/campaign-2026-09-16-harden-it/receipts/gitleaks-audit.json:aws-access-token:9",
        "f0c83cb1f1aa099206058f15570706f90482414e:docs/runs/campaign-2026-09-16-harden-it/receipts/gitleaks-audit.json:aws-access-token:10",
        "f0c83cb1f1aa099206058f15570706f90482414e:docs/runs/campaign-2026-09-16-harden-it/receipts/gitleaks-audit.json:aws-access-token:29",
        "f0c83cb1f1aa099206058f15570706f90482414e:docs/runs/campaign-2026-09-16-harden-it/receipts/gitleaks-audit.json:aws-access-token:30",
    }

    def test_every_waived_entry_is_a_bare_fingerprint(self):
        entries = self._lines()
        self.assertTrue(entries, ".gitleaksignore waives nothing — is the scan still gated?")
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertRegex(entry, self.FINGERPRINT)

    def test_the_waived_set_is_exactly_the_known_fixtures(self):
        self.assertEqual(set(self._lines()), self.WAIVED,
                         "the secret-scan waiver changed — every entry here is a finding "
                         "nobody will see again, so an addition needs its own justification")

    # Paths allowed to carry waived fingerprints, each with its justification above.
    WAIVED_PATHS = {
        "tests/test_decisions.py",
        "docs/runs/campaign-2026-09-16-harden-it/ADDENDUM-gitleaks-waiver.md",
        "docs/runs/campaign-2026-09-16-harden-it/receipts/gitleaks-audit.json",
    }

    def test_nothing_outside_the_fixture_file_is_waived(self):
        for entry in self._lines():
            with self.subTest(entry=entry):
                self.assertIn(entry.split(":")[1], self.WAIVED_PATHS,
                              "only the credential-shaped fixtures are waived")

    def test_the_waiver_carries_no_address_and_no_commit_message(self):
        text = self.IGNORE.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                            "an e-mail address is back in the secret waiver")
        for field in ('"Message"', '"Author"', '"Email"', '"Secret"', '"Match"'):
            self.assertNotIn(field, text, f"{field} is finding CONTENT, not its identity")

    def test_the_scan_reads_this_file_and_no_baseline(self):
        # A MENTION is fine — the step explains at length why the baseline went away. What must
        # not survive is an INVOCATION, which would point gitleaks at a file the repo no longer
        # has. (This test caught exactly that distinction on its own comment first.)
        wf = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        invoked = [ln.strip() for ln in wf.splitlines()
                   if "--baseline-path" in ln and not ln.lstrip().startswith("#")]
        self.assertEqual(invoked, [],
                         "the workflow still PASSES a baseline the repo no longer has")
        self.assertIn("gitleaksignore", wf,
                      "nothing in the workflow explains where the waiver lives")

    def test_the_planted_credential_control_still_runs(self):
        """The waiver is only as good as the proof that it waives nothing else.

        Checking for the WORD `canary` was not enough — it survives in the prose after the
        block that plants the key is gone. The control is three things that have to be there
        together: a throwaway clone, a key written into the waived file, and a scan of that
        clone whose SUCCESS fails the build.
        """
        wf = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        body = [ln for ln in wf.splitlines() if not ln.lstrip().startswith("#")]
        run = "\n".join(body)
        self.assertRegex(run, r'git clone --quiet \. "\$canary"',
                         "nothing clones a throwaway repo to plant the key in")
        self.assertRegex(run, r'printf .*AKIA.*>> "\$canary/tests/test_decisions\.py"',
                         "nothing plants a real-shaped key in the waived file")
        self.assertRegex(run, r'(?s)if \(cd "\$canary".{0,200}?detect.{0,400}?exit 1',
                         "a passing scan of the planted key no longer fails the build")


class TheSuiteRunsOnTheStdlibAlone(unittest.TestCase):
    """CI installs no test dependencies, so a third-party import is a red build, not a skip.

    Learned the expensive way: a `yaml.safe_load` in this very file passed locally, where pyyaml
    happens to be installed, and failed on the runner. The repo already believed this —
    test_floor_guard.py uses `import yaml` as its example of a third-party import — but nothing
    enforced it, so the belief was worth exactly one commit.
    """

    # Modules that live in this directory and are imported by path, not by name.
    # orca_cli is the sibling module every runtime script imports for the CLI name (#510):
    # local, stdlib-only, not a distributable package.
    LOCAL = {"test_pins", "test_evals", "conftest", "orca_cli"}

    def _offenders(self, source, name="sample.py"):
        """Every module imported by this source, via `ast` — not a line regex.

        The first cut skipped any line containing a quote (to let test_floor_guard.py's quoted
        examples through) and read only the FIRST name of an import. `import os, yaml` and
        `import yaml  # "parser"` both sailed past it, and so did `from os import ...` on a
        commented line (PR #308 review, P2). A guard with holes is the defect it exists to catch.

        `ast` has neither problem and needs no heuristic: a quoted example parses to a string
        constant, never an Import node, and every alias in a multi-name import is visited.
        """
        stdlib = set(sys.stdlib_module_names)
        found = []
        for node in ast.walk(ast.parse(source, filename=name)):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                # level > 0 is a relative import — no distributable package behind it.
                mods = [] if node.level else [node.module or ""]
            else:
                continue
            for mod in mods:
                top = mod.split(".")[0]
                if not top or top in stdlib or top in self.LOCAL or top == Path(name).stem:
                    continue
                found.append(f"{name}:{node.lineno}: {top}")
        return found

    def test_the_check_sees_imports_a_line_regex_missed(self):
        """PR #308 review, P2 — the holes in the first cut, each reproduced before fixing.

        All three passed the regex version and would have failed in dependency-free CI.
        """
        for source in ("import os, yaml\n",
                       'import yaml  # "parser"\n',
                       "import json\nimport requests, os\n",
                       "from yaml import safe_load\n",
                       "def f():\n    import yaml\n"):
            with self.subTest(source=source.strip()):
                self.assertTrue(self._offenders(source),
                                "a third-party import slipped past the guard")
        # And a quoted example is still not an import — test_floor_guard.py carries several.
        self.assertEqual(self._offenders('BAD = ["import yaml", "import requests"]\n'), [])
        for relative in ("from . import helpers\n", "from .helpers import thing\n",
                         "from ..pkg.mod import thing\n"):
            with self.subTest(source=relative.strip()):
                self.assertEqual(self._offenders(relative), [],
                                 "a relative import names no distributable package")

    def test_the_check_can_actually_see_a_third_party_import(self):
        """A clean tree makes `assertEqual(offenders, [])` pass whether or not the check works.

        Two negative-control mutants proved that: scanning no files at all, and allowlisting
        everything, both left the suite green. So the detector gets a sample it MUST flag —
        otherwise this is a check that only ever agrees with itself.
        """
        bad = self._offenders("import os\nimport yaml\nfrom requests import get\n")
        self.assertEqual(len(bad), 2, f"the third-party scan missed something: {bad}")
        self.assertTrue(any("yaml" in o for o in bad))
        self.assertTrue(any("requests" in o for o in bad))
        self.assertEqual(self._offenders("import os\nimport json\nfrom pathlib import Path\n"),
                         [], "the scan flagged the standard library")

    def test_no_test_imports_a_package_ci_does_not_install(self):
        offenders = []
        paths = sorted(Path(__file__).resolve().parent.glob("test_*.py"))
        self.assertGreater(len(paths), 20, "the scan found almost no test files to read")
        for path in paths:
            offenders += self._offenders(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(offenders, [],
                         "CI installs no test dependencies — these imports are a red build on "
                         "the runner and a pass on any machine that happens to have them")


class TheAlertWorkflowCannotBeTrippedByAFork(unittest.TestCase):
    """`branches: [main]` filters the workflow_run's HEAD branch, and a fork's PR branch can be
    named `main` too. No token reaches the fork, so the exposure is issue spam rather than
    credentials — but both halves of the guard are needed and neither is obvious."""

    WF = ROOT / ".github" / "workflows" / "alert-on-failure.yml"

    def _condition(self):
        """The job's `if:` folded scalar, read with the stdlib.

        This used `yaml.safe_load` and CI went red: pyyaml is not on the runner, and the whole
        suite is stdlib-only by design — test_floor_guard.py treats a bare `import yaml` as the
        third-party marker it is. Same folded-scalar shape test_pins.py already reads by hand.
        """
        out, active, indent = [], False, 0
        for line in self.WF.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not active and stripped.startswith("if:"):
                active, indent = True, len(line) - len(line.lstrip())
                rest = stripped[len("if:"):].strip()
                if rest not in (">-", ">", "|", "|-"):
                    out.append(rest)
                continue
            if active:
                if not stripped or stripped.startswith("#"):
                    continue
                if len(line) - len(line.lstrip()) <= indent:
                    break
                out.append(stripped)
        self.assertTrue(out, "the alert job has no `if:` condition at all")
        return " ".join(" ".join(out).split())

    def test_the_run_must_have_come_from_a_push(self):
        self.assertIn("github.event.workflow_run.event == 'push'", self._condition(),
                      "a PR-triggered validate run can still file an issue")

    def test_the_run_must_have_come_from_this_repository(self):
        self.assertIn(
            "github.event.workflow_run.head_repository.full_name == github.repository",
            self._condition(),
            "a fork pushing to its own `main` can still file an issue here")

    def test_the_failure_condition_and_the_drill_both_survive(self):
        cond = self._condition()
        self.assertIn("github.event.workflow_run.conclusion == 'failure'", cond,
                      "the workflow would now alert on a SUCCESSFUL run")
        self.assertIn("github.event_name == 'workflow_dispatch'", cond,
                      "the manual drill path is gone, so the alert can no longer be proven")


WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
# ANY expression inside a `run:` script (2026-10-23 review, §5 CI). The runner pastes an
# expression's value into the script text before the shell parses it, so whether one is safe
# inline depends on where the value came from, which no regex can decide: the old list of
# PR-controlled contexts (base_ref, head_ref, event.*) missed github.ref_name, inputs.*,
# steps.*, needs.*, and env.* holding any of those, and a matrix can be built from
# fromJSON(needs.*). So there is no allowlist: every value reaches a script through env:,
# where the shell expands it as data and never re-parses it.
_TAINTED_EXPR_RE = re.compile(r"\$\{\{")


def _jobs(text):
    """{job: [lines]} for the top-level `jobs:` map — stdlib only (no pyyaml on the runner)."""
    jobs, current, in_jobs = {}, None, False
    for line in text.splitlines():
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if in_jobs and line and not line[0].isspace() and not line.startswith("#"):
            in_jobs = False
        if not in_jobs:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            current = m.group(1)
            jobs[current] = []
        elif current:
            jobs[current].append(line)
    return jobs


def _run_scripts(text):
    """Every `run:` script body, inline or block scalar."""
    scripts, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not m:
            continue
        indent, rest = len(m.group(1)), m.group(2)
        body = [] if rest in ("|", "|-", ">", ">-") else [rest]
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            body.append(nxt)
        scripts.append((i + 1, "\n".join(body)))
    return scripts


class WorkflowsAreBoundedAndInjectionFree(unittest.TestCase):
    def test_the_scan_sees_every_workflow(self):
        self.assertGreaterEqual(len(WORKFLOWS), 10)
        self.assertGreaterEqual(sum(len(_jobs(p.read_text(encoding="utf-8")))
                                    for p in WORKFLOWS), 15)

    def test_every_job_declares_a_timeout(self):
        # Without one a hung job holds a runner for GitHub's 6-hour default.
        for path in WORKFLOWS:
            for job, body in _jobs(path.read_text(encoding="utf-8")).items():
                with self.subTest(workflow=path.name, job=job):
                    self.assertTrue(
                        any(re.match(r"^    timeout-minutes:\s*\d+\s*$", ln) for ln in body),
                        f"{path.name}:{job} has no job-level timeout-minutes")

    def test_no_run_script_interpolates_a_pr_controlled_context(self):
        for path in WORKFLOWS:
            for lineno, script in _run_scripts(path.read_text(encoding="utf-8")):
                with self.subTest(workflow=path.name, line=lineno):
                    self.assertIsNone(
                        _TAINTED_EXPR_RE.search(script),
                        f"{path.name}:{lineno} interpolates a PR-controlled context into "
                        "shell — pass it through env: and quote the variable")

    def test_the_injection_scan_can_actually_see_one(self):
        planted = ("jobs:\n  x:\n    steps:\n      - run: |\n"
                   "          echo ${{ github.base_ref }}\n")
        self.assertTrue(any(_TAINTED_EXPR_RE.search(s) for _, s in _run_scripts(planted)))
        self.assertEqual(list(_jobs(planted)), ["x"])


def _steps(job_lines):
    """A job's steps as lists of lines (each starts at its `      - ` item) — stdlib only."""
    steps, current, in_steps = [], None, False
    for line in job_lines:
        if re.match(r"^    steps:\s*$", line):
            in_steps = True
            continue
        if not in_steps:
            continue
        if re.match(r"^    \S", line):
            break
        if line.startswith("      - "):
            current = [line]
            steps.append(current)
        elif current is not None:
            current.append(line)
    return steps


def _step_name(step):
    for line in step:
        m = re.match(r"^\s*(?:- )?name:\s*(.*)$", line)
        if m:
            return m.group(1).strip()
    return ""


def _step_env(step):
    """{NAME: raw value} of a step's own `env:` map."""
    env, in_env = {}, False
    for line in step:
        if re.match(r"^        env:\s*$", line):
            in_env = True
            continue
        if in_env:
            m = re.match(r"^          ([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$", line)
            if m:
                env[m.group(1)] = m.group(2)
            elif not line.strip().startswith("#"):
                in_env = False
    return env


def _step_script(step):
    """The step's `run:` body, dedented — what the runner hands the shell."""
    found = _run_scripts("\n".join(step))
    return textwrap.dedent(found[0][1]) if found else ""


def _bash(script, env, cwd=None):
    """Run a script the way a `run:` step with no `shell:` runs on Linux: `bash -e`."""
    full = {**os.environ, **env}
    full["PATH"] = os.path.dirname(sys.executable) + os.pathsep + full.get("PATH", "")
    return subprocess.run(["bash", "-e", "-c", script], env=full, cwd=cwd,
                          capture_output=True, text=True, timeout=60)


class TheWidenedInjectionScanSeesEveryContext(unittest.TestCase):
    """2026-10-23 review, §5 CI: the scan matched only base_ref, head_ref and event.*, so
    `steps.alert.outputs.*` sat inline in alert-on-failure.yml and nothing flagged it."""

    CONTEXTS = ("github.ref_name", "github.head_ref", "inputs.tag", "steps.alert.outputs.number",
                "needs.resolve.outputs.pr", "env.HEAD_BRANCH", "matrix.shard", "secrets.TOKEN",
                "github.event.pull_request.title")

    def test_every_context_class_inside_a_run_block_is_flagged(self):
        for ctx in self.CONTEXTS:
            for opener in ("run: |", "run: >-", "run:"):
                with self.subTest(context=ctx, opener=opener):
                    body = ("\n          echo ${{ %s }}\n" % ctx if opener != "run:"
                            else " echo ${{ %s }}\n" % ctx)
                    planted = "jobs:\n  x:\n    steps:\n      - " + opener + body
                    scripts = _run_scripts(planted)
                    self.assertTrue(scripts, "the planted run: block was not even found")
                    self.assertTrue(any(_TAINTED_EXPR_RE.search(s) for _, s in scripts),
                                    f"${{{{ {ctx} }}}} inside {opener!r} went unflagged")

    def test_an_expression_passed_through_env_is_not_a_script(self):
        # The fix the rule asks for must itself pass, or the rule could only be met by deletion.
        planted = ("jobs:\n  x:\n    steps:\n      - name: s\n        env:\n"
                   "          N: ${{ steps.alert.outputs.number }}\n"
                   "        run: |\n          echo \"$N\"\n")
        self.assertEqual([s for _, s in _run_scripts(planted) if _TAINTED_EXPR_RE.search(s)], [])

    def test_the_alert_workflow_reads_step_outputs_through_env(self):
        text = (ROOT / ".github" / "workflows" / "alert-on-failure.yml").read_text(encoding="utf-8")
        envs = {}
        for step in _steps(_jobs(text)["alert"]):
            envs.update(_step_env(step))
        self.assertEqual(envs.get("ISSUE_NUMBER"), "${{ steps.alert.outputs.number }}")
        self.assertEqual(envs.get("ALERT_ACTION"), "${{ steps.alert.outputs.action }}")


class EveryWorkflowToolComesFromAHashedLock(unittest.TestCase):
    """2026-10-23 review, §5 CI: fixture-target-app.yml ran an unpinned uvx ruff, the one tool
    install outside .github/ci-tools.lock. tests/test_pins.py pins validate.yml; this pins
    every workflow, so the next unpinned resolver fails wherever it lands."""

    UNLOCKED = re.compile(r"\buvx\b|\bpipx\s+run\b|\buv\s+tool\s+(run|install)\b")

    def _offenders(self, text):
        bad = []
        for lineno, script in _run_scripts(text):
            joined = script.replace("\\\n", " ")
            for line in joined.splitlines():
                code = line.split(" #", 1)[0]
                if self.UNLOCKED.search(code) or (
                        re.search(r"\bpip\s+install\b", code) and "--require-hashes" not in code):
                    bad.append(f"{lineno}: {line.strip()}")
        return bad

    def test_no_workflow_resolves_a_tool_outside_the_lock(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                self.assertEqual(self._offenders(path.read_text(encoding="utf-8")), [],
                                 f"{path.name} installs a tool by name, not by hash")

    def test_the_fixture_lint_installs_ruff_from_the_lock(self):
        text = (ROOT / ".github" / "workflows" / "fixture-target-app.yml").read_text(
            encoding="utf-8")
        scripts = "\n".join(s for _, s in _run_scripts("\n".join(_jobs(text)["ruff"])))
        self.assertIn("--require-hashes", scripts)
        self.assertIn(".github/ci-tools.lock", scripts)
        self.assertRegex(scripts, r"(?m)^\s*ruff check evals/demo/target-app\s*$")

    def test_the_scan_can_actually_see_one(self):
        for line in ("uvx ruff check .", "pip install ruff==0.16.7",
                     "python3 -m pip install -r requirements.txt", "uv tool run ruff"):
            with self.subTest(line=line):
                self.assertTrue(self._offenders(
                    "jobs:\n  x:\n    steps:\n      - run: |\n          " + line + "\n"))
        self.assertEqual(self._offenders(
            "jobs:\n  x:\n    steps:\n      - run: |\n"
            "          python3 -m pip install --require-hashes --only-binary :all: \\\n"
            "            -r .github/ci-tools.lock\n"), [])


class TagPublishersRefuseAnyoneButTheMaintainer(unittest.TestCase):
    """2026-10-23 review, P2-23: release.yml and publish-dist.yml published on ANY `v*` tag push
    with `contents: write` (publish-dist force-pushes `dist`), while docs/ops.md says only the
    owner authorizes a cut. Each publisher's first step now refuses any other actor; the step is
    run here, not just read, so a guard that cannot fail is caught."""

    PUBLISHERS = ("release.yml", "publish-dist.yml")
    STEP = "Only the release maintainer publishes"

    def _guard(self, name):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        jobs = _jobs(text)
        self.assertEqual(len(jobs), 1, f"{name}: expected its one publishing job")
        steps = _steps(next(iter(jobs.values())))
        self.assertTrue(steps, f"{name}: no steps parsed")
        return text, steps

    def test_the_guard_is_the_first_step_of_every_publisher(self):
        for name in self.PUBLISHERS:
            with self.subTest(workflow=name):
                _, steps = self._guard(name)
                self.assertEqual(_step_name(steps[0]), self.STEP,
                                 f"{name}: something runs before the maintainer guard")
                env = _step_env(steps[0])
                self.assertEqual(env.get("RELEASE_MAINTAINER"), "${{ github.repository_owner }}")
                self.assertEqual(env.get("RUN_ACTOR"), "${{ github.actor }}")
                self.assertEqual(env.get("RUN_TRIGGERING_ACTOR"),
                                 "${{ github.triggering_actor }}")

    def test_the_guard_refuses_every_actor_but_the_owner(self):
        cases = (("ravidsrk", "ravidsrk", "ravidsrk", 0),
                 ("ravidsrk", "a-writer", "a-writer", 1),
                 ("ravidsrk", "ravidsrk", "a-writer", 1),
                 ("ravidsrk", "a-writer", "ravidsrk", 1),
                 ("", "", "", 1))
        for name in self.PUBLISHERS:
            script = _step_script(self._guard(name)[1][0])
            self.assertTrue(script.strip(), f"{name}: the guard step has no run: body")
            for owner, actor, trigger, want in cases:
                with self.subTest(workflow=name, actor=actor, triggering=trigger):
                    r = _bash(script, {"RELEASE_MAINTAINER": owner, "RUN_ACTOR": actor,
                                       "RUN_TRIGGERING_ACTOR": trigger})
                    self.assertEqual(r.returncode != 0, bool(want), r.stdout + r.stderr)
                    if want:
                        self.assertIn("::error::", r.stdout)

    def test_the_tag_commit_must_be_on_main(self):
        for name in self.PUBLISHERS:
            with self.subTest(workflow=name):
                text, _ = self._guard(name)
                scripts = "\n".join(s for _, s in _run_scripts(text))
                self.assertRegex(scripts, r'git merge-base --is-ancestor "\$cut" origin/main\b')


class TheNegativeControlDiagnosticIsReachable(unittest.TestCase):
    """2026-10-23 review, §5 CI: `set -uo pipefail` under the runner's default `bash -e` ended
    the step on the pipeline, so the "demo itself is RED" diagnostic never printed. The step is
    run here under `bash -e` with a stub run.sh, so the diagnostic must actually appear."""

    def _script(self):
        text = (ROOT / ".github" / "workflows" / "negative-control.yml").read_text(
            encoding="utf-8")
        steps = [s for s in _steps(_jobs(text)["pinned-demo"])
                 if "evals/demo/negative-control/run.sh" in "\n".join(s)]
        self.assertEqual(len(steps), 1, "the demo step is gone")
        return _step_script(steps[0])

    def _run(self, stub_body, pinned):
        with tempfile.TemporaryDirectory() as tmp:
            demo = Path(tmp) / "evals" / "demo" / "negative-control"
            demo.mkdir(parents=True)
            (demo / "run.sh").write_text(stub_body, encoding="utf-8")
            (demo / "head-to-head.txt").write_text(pinned, encoding="utf-8")
            return _bash(self._script(), {}, cwd=tmp)

    def test_a_red_demo_prints_its_diagnostic_and_fails(self):
        r = self._run("echo partial output\nexit 3\n", "partial output\n")
        self.assertNotEqual(r.returncode, 0, "a red demo passed the gate")
        self.assertIn("the demo itself is RED", r.stdout, r.stdout + r.stderr)
        self.assertIn("exited 3", r.stdout)

    def test_a_drifted_demo_fails_as_drift(self):
        r = self._run("echo fresh output\n", "pinned output\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DRIFTED", r.stdout, r.stdout + r.stderr)

    def test_a_matching_demo_passes(self):
        r = self._run("echo same output\n", "same output\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("matches pinned expectations", r.stdout)


_ct_spec = importlib.util.spec_from_file_location(
    "_check_trailers", ROOT / "scripts" / "check_trailers.py")
check_trailers = importlib.util.module_from_spec(_ct_spec)
_ct_spec.loader.exec_module(check_trailers)

# A git that reads no user or system config: the host's signing, hooks and log settings
# cannot leak into the fixture repos or into what check_trailers.py reads from them.
_HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


class CommitTrailersAreRefused(unittest.TestCase):
    """#628 / 2026-10-23 review, §5 Commit hygiene: CONTRIBUTING.md forbids co-author and
    tool-attribution trailers, and 12 of the last 200 commits on main carried them because
    nothing checked. scripts/check_trailers.py reads a PR's own range; these fixtures are real
    repositories, because the mechanism starts from `git log BASE..HEAD`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name).resolve()
        self._env = mock.patch.dict(os.environ, _HERMETIC_GIT)
        self._env.start()
        self._git("init", "-q", ".")
        self.base = self._commit("chore: base")

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _git(self, *args, stdin=None):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "commit.gpgsign=false",
                               "-c", "core.hooksPath=" + os.devnull, *args],
                              input=stdin, capture_output=True, text=True, check=True).stdout

    def _commit(self, message):
        self._git("commit", "--allow-empty", "-q", "-F", "-", stdin=message)
        return self._git("rev-parse", "HEAD").strip()

    def _check(self, base=None, head="HEAD"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = check_trailers.main(["--base", base or self.base, "--head", head,
                                        "--root", str(self.repo)])
        return code, out.getvalue()

    def test_a_clean_range_passes(self):
        self._commit("docs: say why Co-authored-by trailers are refused\n\n"
                     "Generated with uv pip compile --generate-hashes, as before.\n\n"
                     "Signed-off-by: t <t@example.com>\n")
        code, out = self._check()
        self.assertEqual(code, 0, out)
        self.assertIn("1 commit(s)", out)

    def test_a_co_author_trailer_is_refused_in_any_case(self):
        for key in ("Co-authored-by", "Co-Authored-By", "CO-AUTHORED-BY", "co-authored-by",
                    "Co-developed-by"):
            with self.subTest(key=key):
                sha = self._commit(f"fix: a thing\n\nBody.\n\n{key}: Bot <bot@example.com>\n")
                code, out = self._check()
                self.assertEqual(code, 1, out)
                self.assertIn(f"{sha[:12]} co-author: {key}:", out)
                self.base = sha  # the next case starts from a clean range

    def test_a_tool_attribution_line_is_refused(self):
        for line in ("\N{ROBOT FACE} Generated with [Claude Code](https://claude.com/claude-code)",
                     "Generated by GitHub Copilot", "generated-by: an agent",
                     "Assisted-by: Cursor", "AI-Assisted-By: Gemini"):
            with self.subTest(line=line):
                sha = self._commit(f"feat: x\n\n{line}\n")
                code, out = self._check()
                self.assertEqual(code, 1, out)
                self.assertIn(f"{sha[:12]} tool-attribution:", out)
                self.base = sha

    def test_history_below_the_base_is_never_read(self):
        old = self._commit("fix: old\n\nCo-authored-by: Bot <bot@example.com>\n")
        self._commit("fix: new and clean\n")
        self.assertEqual(self._check(base=old)[0], 0)
        self.assertEqual(self._check(base=self.base)[0], 1, "the fixture trailer was not seen")

    def test_a_merge_commit_in_the_range_is_read(self):
        main = self._git("rev-parse", "--abbrev-ref", "HEAD").strip()
        self._git("checkout", "-q", "-b", "side")
        self._commit("feat: side work\n")
        self._git("checkout", "-q", main)
        self._commit("feat: main work\n")
        self._git("merge", "--no-ff", "-q", "side", "-m", "Merge side",
                  "-m", "Co-authored-by: Bot <bot@example.com>")
        code, out = self._check()
        self.assertEqual(code, 1, out)
        self.assertIn("co-author", out)

    def test_an_empty_range_passes(self):
        self.assertEqual(self._check(base=self.base, head=self.base)[0], 0)

    def test_an_unresolvable_end_cannot_pass_as_clean(self):
        self.assertEqual(self._check(base="0" * 40)[0], 2)
        self.assertEqual(self._check(head="no-such-ref")[0], 2)

    def test_the_cli_fails_the_step(self):
        self._commit("fix: x\n\nCo-authored-by: Bot <bot@example.com>\n")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_trailers.py"),
                            "--base", self.base, "--root", str(self.repo)],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("CONTRIBUTING.md forbids", r.stdout)


class TheTrailerCheckRunsOnEveryPullRequest(unittest.TestCase):
    """The check is wired into the `checks` job, which the required `gates` job needs, over the
    PR's own range, after a full-history checkout (a shallow one cannot resolve the base and would
    exit 2). It ran inside `gates` until the CI speed change moved every check that reads no
    shard output into `checks`, which starts beside the shards instead of after them."""

    def test_gates_runs_the_check_over_the_pr_range(self):
        text = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^  pull_request:")
        steps = _steps(_jobs(text)["checks"])
        names = [_step_name(s) for s in steps]
        idx = [i for i, s in enumerate(steps) if "scripts/check_trailers.py" in _step_script(s)]
        self.assertEqual(len(idx), 1, "gates does not run scripts/check_trailers.py once")
        step = steps[idx[0]]
        self.assertIn('--base "$PR_BASE_SHA" --head "$PR_HEAD_SHA"', _step_script(step))
        env = _step_env(step)
        self.assertEqual(env.get("PR_BASE_SHA"), "${{ github.event.pull_request.base.sha }}")
        self.assertEqual(env.get("PR_HEAD_SHA"), "${{ github.event.pull_request.head.sha }}")
        self.assertIn("        if: github.event_name == 'pull_request'", step)
        checkout = [i for i, s in enumerate(steps) if "actions/checkout@" in "\n".join(s)]
        self.assertTrue(checkout and checkout[0] < idx[0],
                        f"the trailer check runs before any checkout: {names}")
        self.assertRegex("\n".join(steps[checkout[0]]), r"fetch-depth:\s*0\b")

    def test_the_job_that_runs_it_blocks_the_merge(self):
        """`checks` is not itself a required context: it blocks the merge only because the
        required `gates` job NEEDS it, and gates' first step fails unless every need succeeded
        (tests/test_shard_tests.py runs that step). Without the need, a red trailer check — and
        every other check that moved with it — would be advisory."""
        text = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        jobs = _jobs(text)
        self.assertIn("checks", jobs, "the checks job is gone from validate.yml")
        needs = [ln for ln in jobs["gates"] if re.match(r"^    needs:", ln)]
        self.assertEqual(len(needs), 1, "gates declares no single needs list")
        listed = [n.strip() for n in needs[0].split("[", 1)[1].split("]", 1)[0].split(",")]
        self.assertIn("checks", listed, "gates no longer needs checks: its checks are advisory")
        self.assertIn("    if: always()", jobs["gates"], "a red checks job would skip gates")


if __name__ == "__main__":
    unittest.main()
