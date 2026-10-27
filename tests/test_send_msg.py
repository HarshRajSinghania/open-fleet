#!/usr/bin/env python3
"""Contract tests for runtime/scripts/send_msg.py (S11).

orchestration send with the upstream handler's rules enforced client-side:
worker_done requires --outcome (and --outcome only rides worker_done),
worker_done/heartbeat never target a group, lifecycle sends never run
identity-less, and an explicit --from that disagrees with
ORCA_TERMINAL_HANDLE is refused. Refusals exit 2 with no orca call.
"""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "runtime" / "scripts" / "send_msg.py"

RELAY = {"relay": {"messageId": "msg_7", "sequence": 3,
                   "dispatchId": "ctx_1", "accepted": True}}


def load():
    spec = importlib.util.spec_from_file_location("send_msg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_cli(args, env_extra=None, payload=None):
    with tempfile.TemporaryDirectory() as tmp:
        resp = Path(tmp) / "resp.json"
        resp.write_text(json.dumps(payload if payload is not None else {
            "result": RELAY}))
        log = Path(tmp) / "calls.log"
        stub = Path(tmp) / "orca"
        stub.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{log}"\ncat "{resp}"\n')
        stub.chmod(0o755)
        env = {"PATH": f"{tmp}:/usr/bin:/bin", "ORCA_CLI_COMMAND": "orca"}
        env.update(env_extra or {})
        p = subprocess.run(["python3", str(SCRIPT), *args], env=env,
                           capture_output=True, text=True)
        calls = log.read_text() if log.exists() else ""
        return p.returncode, p.stdout, p.stderr, calls


class TestRules(unittest.TestCase):
    ENV = {"ORCA_TERMINAL_HANDLE": "term_9"}

    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def build(self, args, env=None):
        return self.m.build_argv(self.m.parse_args(args), env or {})

    def test_minimal_send(self):
        self.assertEqual(self.build(["--subject", "hi"]),
                         ["orchestration", "send", "--subject", "hi"])

    def test_full_passthrough(self):
        argv = self.build(["--subject", "s", "--to", "run:r1", "--run", "r1",
                           "--body", "b", "--type", "status",
                           "--priority", "high", "--thread-id", "t",
                           "--payload", '{"a":1}', "--task-id", "tk",
                           "--dispatch-id", "d", "--files-modified", "f",
                           "--report-path", "p", "--phase", "ph",
                           "--retry-request", "q",
                           "--dispatch-capability", "cap"])
        for flag in ("--to", "run:r1", "--priority", "high", "--payload",
                     '{"a":1}', "--dispatch-capability", "cap"):
            self.assertIn(flag, argv)

    def test_empty_subject_refused(self):
        with self.assertRaises(self.m.Refused):
            self.build(["--subject", ""])

    def test_unknown_type_refused(self):
        with self.assertRaises(self.m.Refused):
            self.build(["--subject", "s", "--type", "BOGUS"])

    def test_worker_done_requires_outcome(self):
        with self.assertRaises(self.m.Refused):
            self.build(["--subject", "s", "--type", "worker_done"], self.ENV)

    def test_worker_done_accepts_both_outcomes(self):
        for outcome in ("succeeded", "failed"):
            argv = self.build(["--subject", "s", "--type", "worker_done",
                              "--outcome", outcome], self.ENV)
            self.assertIn(outcome, argv)

    def test_outcome_without_worker_done_refused(self):
        with self.assertRaises(self.m.Refused):
            self.build(["--subject", "s", "--type", "status",
                        "--outcome", "succeeded"])

    def test_bad_outcome_refused(self):
        with self.assertRaises(self.m.Refused):
            self.build(["--subject", "s", "--type", "worker_done",
                        "--outcome", "maybe"], self.ENV)

    def test_lifecycle_to_group_refused(self):
        for mtype in ("worker_done", "heartbeat"):
            with self.subTest(mtype=mtype):
                args = ["--subject", "s", "--type", mtype, "--to", "@all"]
                if mtype == "worker_done":
                    args += ["--outcome", "succeeded"]
                with self.assertRaises(self.m.Refused):
                    self.build(args, self.ENV)

    def test_lifecycle_without_identity_refused(self):
        with self.assertRaises(self.m.Refused):
            self.build(["--subject", "s", "--type", "worker_done",
                        "--outcome", "succeeded"], {})

    def test_lifecycle_with_explicit_from_ok(self):
        argv = self.build(["--subject", "s", "--type", "heartbeat",
                          "--from", "term_9"], {})
        self.assertIn("term_9", argv)

    def test_from_mismatch_refused(self):
        with self.assertRaises(self.m.Refused):
            self.build(["--subject", "s", "--from", "term_other"], self.ENV)

    def test_from_defaults_to_env(self):
        argv = self.build(["--subject", "s"], self.ENV)
        self.assertIn("--from", argv)
        self.assertIn("term_9", argv)

    def test_non_json_payload_refused(self):
        with self.assertRaises(self.m.Refused):
            self.build(["--subject", "s", "--payload", "nope"])


class TestCli(unittest.TestCase):
    def test_send_reports_message_id(self):
        rc, out, err, calls = run_cli(["--subject", "hi", "--type", "status"])
        self.assertEqual(rc, 0, err)
        self.assertIn("MESSAGE_ID=msg_7", out)
        self.assertIn("orchestration send --subject hi --type status --json",
                      calls)

    def test_refusal_exits_2_with_no_call(self):
        rc, _o, err, calls = run_cli(
            ["--subject", "s", "--type", "worker_done", "--to", "@all",
             "--outcome", "succeeded"],
            env_extra={"ORCA_TERMINAL_HANDLE": "term_9"})
        self.assertEqual(rc, 2, err)
        self.assertIn("REFUSED", err)
        self.assertEqual(calls, "")

    def test_error_envelope_exits_1(self):
        rc, _o, err, _c = run_cli(
            ["--subject", "s"],
            payload={"error": {"code": "consumer_fenced", "message": "no"}})
        self.assertEqual(rc, 1, err)
        self.assertIn("consumer_fenced", err)


class TestSenderIdentityIsSaidPlainly(unittest.TestCase):
    """W5-19 (2026-10-27 audit): `--from` is accepted whenever it EQUALS ORCA_TERMINAL_HANDLE, and
    both are the caller's own (argv, its own env), so `ORCA_TERMINAL_HANDLE=<sibling>` speaks as the
    sibling. The docstring claimed that passing another pane's handle "would speak as that worker"
    and was prevented; it now says what the check is (an accidental-mismatch guard) and where the
    authority is. And relay.messageId printed raw: a newline in it forged extra receipt lines."""

    def setUp(self):
        self.m = load()

    def test_the_docstring_names_the_limit_and_the_authority(self):
        doc = " ".join(self.m.__doc__.split())
        self.assertIn("self-asserted", doc)
        self.assertIn("ACCIDENTAL mismatch", doc)
        self.assertIn("dispatch_capability_invalid", doc)

    def test_a_matching_forged_ambient_handle_is_not_detected_here(self):
        # The honest limit, pinned: the client-side check cannot see this spoof.
        argv = load().build_argv(load().parse_args(
            ["--subject", "s", "--type", "heartbeat", "--from", "term_sibling"]),
            {"ORCA_TERMINAL_HANDLE": "term_sibling"})
        self.assertIn("term_sibling", argv)

    def test_the_message_id_prints_inert_on_one_line(self):
        lines = self.m.format_send({"relay": {"messageId": "msg_1\nWORKER_DONE=forged\x1b[2J\u202e"}})
        self.assertEqual(len(lines), 1)
        self.assertNotIn("\n", lines[0])
        self.assertNotIn("\x1b", lines[0])
        self.assertNotIn("\u202e", lines[0])
        self.assertTrue(lines[0].startswith("MESSAGE_ID=msg_1"), lines[0])

    def test_a_tab_in_the_message_id_is_escaped(self):
        # W4-11 re-attack: a TAB stayed raw in single-line fields.
        line = self.m.format_send({"relay": {"messageId": "msg_1\tFORGED=1"}})[0]
        self.assertNotIn("\t", line)

    def test_the_cli_prints_exactly_one_receipt_line(self):
        rc, out, err, _calls = run_cli(["--subject", "s"], payload={
            "result": {"relay": {"messageId": "msg_1\nMESSAGE_ID=msg_forged"}}})
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(out.splitlines()), 1, out)
        self.assertNotIn("\nMESSAGE_ID=msg_forged", out)


if __name__ == "__main__":
    unittest.main()
