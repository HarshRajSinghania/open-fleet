#!/usr/bin/env python3
"""Differential conformance corpus: runtime/scripts/deny-hook.sh against real bash (#598).

The hook PARSES shell text; bash EXECUTES it. Every hole the hook has had in this class
(heredoc delimiters, escaped backslashes, continuations, comment boundaries, escaped
substitution openers -- PR #592) was a place where the two disagreed about which text runs.
So this corpus asks bash, not a reviewer.

One case is a TEMPLATE: shell text with a hole ({CMD}, or {HEAD} and {ARGS}) in some lexical
context. It is rendered twice:

  * the SAFE form puts an inert sentinel in the hole (`orca_sentinel push --force origin main`)
    and runs it in real bash, in a throwaway directory, with PATH holding only the sentinel and
    a few harmless tools, no credentials, no network tool, CPU/file-size limits and a timeout.
    The sentinel appends one line to a marker file, so "bash ran the hole" is an observation;
  * the FORBIDDEN form puts a refused command in the same hole (`git push --force origin main`,
    HIGH tier; `gh issue close 34`, rule 5) and is fed ONLY to the hook as a PreToolUse payload.
    It is never executed, and no safe form may name git, gh or another real tool (checked).

Scoring keeps the two error directions apart:

  * MISS       -- bash ran the sentinel and the hook allowed the forbidden form (a hole);
  * DOWNGRADE  -- bash ran it and the hook only asked (a HIGH shape must deny);
  * FALSE-DENY -- bash ran nothing and the hook refused. Literal documentation examples
                  (quoted heredocs, single quotes, comments, escaped openers) are the allow
                  controls; a refusal of text bash treats as a syntax error is counted as
                  fail-closed, not as a false denial.

Every mismatch is minimized (ddmin over the template, placeholders atomic) and stored in
tests/fixtures/deny_hook_conformance.json with the bash version and seed that found it.
tests/test_deny_hook_conformance.py runs the bounded corpus in CI and replays the fixtures.

Usage:
  python3 scripts/deny_hook_corpus.py                      bounded corpus (the CI one), report
  python3 scripts/deny_hook_corpus.py --random 2000 --both larger corpus, both payloads per case
  python3 scripts/deny_hook_corpus.py --minimize --write   minimize mismatches into the fixtures
  python3 scripts/deny_hook_corpus.py --list               print the rendered forbidden forms
  --hook PATH   judge another copy of the hook (a mutant, or `git show <base>:...`)
  --bash PATH   the bash to use as the oracle (default: bash on PATH)
  --seed N      the generator seed (default 598)
"""
import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "runtime" / "scripts" / "deny-hook.sh"
FIXTURES = ROOT / "tests" / "fixtures" / "deny_hook_conformance.json"
SEED = 598
BOUNDED_RANDOM = 160   # the CI corpus: the whole grid plus this many seeded compositions
SENTINEL = "orca_sentinel"
# payload -> (refused head, its arguments). The safe form swaps ONLY the head for the sentinel,
# so both forms have the same words, quotes and separators. push is a HIGH-tier deny, send a
# rule 5 deny, wipe a Never-list ask -- three different judging paths in the hook.
PAYLOADS = {"push": ("git", "push --force origin main"), "send": ("gh", "issue close 34"),
            "wipe": ("rm", "-r -f ./build")}
EXPECT = {"push": "deny", "send": "deny", "wipe": "ask"}
CMD, HEAD, ARGS = "{CMD}", "{HEAD}", "{ARGS}"
NL, BS, TAB, SQ, DQ, BT = "\n", "\\", "\t", "'", '"', "`"
# Words a safe form must never contain: the oracle runs it, so it may only reach the sentinel.
_REAL_TOOLS = re.compile(r"(^|[^A-Za-z0-9_])(git|gh|rm|curl|wget|ssh|sudo|scp|nc|python[0-9.]*)"
                         r"([^A-Za-z0-9_]|$)")
BASH_TIMEOUT = 5
HOOK_TIMEOUT = 60
# Hook-relevant environment a developer shell may carry; the corpus judges the default contract.
_SCRUB = ("ORCA_UNIT_WORKTREE", "OPEN_FLEET_UNIT_WORKTREE", "ORCA_HOOK_STRICT_EXIT",
          "OPEN_FLEET_HOOK_STRICT_EXIT", "OPEN_FLEET_HOOK_EXIT2", "OPEN_FLEET_HEADLESS_STRICT",
          "CODEX_CI", "CODEX_SANDBOX", "JCODE_HOOK_TOOL_NAME", "GOOSE_MODE", "OPEN_FLEET_STATE_DB",
          "ORCA_FLEET_STATE_DB", "ORCA_EGRESS_LEDGER", "OPEN_FLEET_EGRESS_LEDGER")


@dataclass(frozen=True)
class Case:
    family: str
    template: str
    payload: str = "push"

    @property
    def id(self):
        return hashlib.sha256(f"{self.payload}\0{self.template}".encode()).hexdigest()[:12]


def render(template, payload, safe):
    head, args = PAYLOADS[payload]
    head = SENTINEL if safe else head
    return template.replace(CMD, head + " " + args).replace(HEAD, head).replace(ARGS, args)


def sq(text):
    """Single-quote text for a shell (the quote itself spelled '\\'')."""
    return SQ + text.replace(SQ, SQ + BS + SQ + SQ) + SQ


# --- the grid: every dimension the issue names, enumerated ---------------------------------
OPENERS = {"dollar": ("$(", ")"), "backtick": (BT, BT), "procsub": ("<(", ")"),
           "dollar-nl": ("$(" + NL, NL + ")"), "procsub-out": (">(", ")")}
QUOTES = {"none": ("", ""), "dq": (DQ, DQ), "sq": (SQ, SQ), "ansi": ("$'", SQ),
          "locale": ('$"', DQ)}
HEREDOC_OPENERS = (  # (spelling after <<, terminator line)
    ("EOF", "EOF"), ("'EOF'", "EOF"), ('"EOF"', "EOF"), (BS + "EOF", "EOF"),
    ('E"O"F', "EOF"), ("'E'OF", "EOF"), ("E" + BS + "OF", "EOF"), (" EOF", "EOF"),
    (" 'EOF'", "EOF"), (TAB + "EOF", "EOF"), ("'EOF X'", "EOF X"), ('"EOF X"', "EOF X"),
    ("E" + BS + " OF", "E OF"), ("-EOF", TAB + "EOF"), ("-'EOF'", TAB + "EOF"),
    ("- EOF", TAB + TAB + "EOF"), ("-" + BS + "EOF", TAB + "EOF"), ("''", ""),
    ("$X", "$X"), ("'$X'", "$X"),
)
HEREDOC_LINES = ("$(" + CMD + ")", BT + CMD + BT, BS + "$(" + CMD + ")", BS * 2 + "$(" + CMD + ")",
                 SQ + "$(" + CMD + ")" + SQ, DQ + "$(" + CMD + ")" + DQ, CMD,
                 "${u:-$(" + CMD + ")}", "$" + BS + NL + "(" + CMD + ")", "x" + BS + NL + "$(" + CMD + ")",
                 "x" + BS * 2 + NL + "$(" + CMD + ")", "# $(" + CMD + ")", "$((1))$(" + CMD + ")")
TERMINATOR_VARIANTS = (  # how a line that LOOKS like the terminator is spelled
    "{T}", "{T} ", " {T}", TAB + "{T}", "{T}" + BS, "'{T}'", "{T};", "{T}" + TAB)


def grid():
    out = []
    # quote state x backslash parity x substitution opener
    for (oname, (opn, cls)), (qname, (qo, qc)), parity in product(OPENERS.items(), QUOTES.items(),
                                                                 range(4)):
        out.append(Case(f"quote:{qname}/{oname}/bs{parity}",
                        "echo " + qo + "x" + BS * parity + opn + CMD + cls + qc))
    # newline continuation, with backslash parity before the newline
    for parity, (name, tpl) in product(range(1, 4), (
            ("opener", "echo x$" + "{P}" + NL + "(" + CMD + ")"),
            ("dq-opener", 'echo "x$' + "{P}" + NL + "(" + CMD + ')"'),
            ("sq-opener", "echo 'x$" + "{P}" + NL + "(" + CMD + ")'"),
            ("before-cmd", "echo x" + "{P}" + NL + CMD),
            ("before-hash", "echo a" + "{P}" + NL + "#$(" + CMD + ")"),
            ("blank-hash", "echo a " + "{P}" + NL + "#$(" + CMD + ")"),
            ("inside-sub", "echo $(" + "{P}" + NL + CMD + ")"),
            ("head-args", HEAD + "{P}" + NL + " " + ARGS),
            ("comment", "# note" + "{P}" + NL + CMD),
            ("escaped-dollar", "echo " + BS + "$" + "{P}" + NL + "(" + CMD + ")"))):
        out.append(Case(f"continuation:{name}/bs{parity}", tpl.replace("{P}", BS * parity)))
    # comments: word position decides, and a comment ends at its newline
    for name, tpl in (
            ("trailing", "echo a #$(" + CMD + ")"), ("glued", "echo a#$(" + CMD + ")"),
            ("line", "# " + CMD), ("indented", "  # " + CMD), ("after-semi", "echo x;#" + CMD),
            ("after-amp", "echo x&#" + CMD), ("quoted-hash", "echo '#' $(" + CMD + ")"),
            ("dq-hash", 'echo "#$(' + CMD + ')"'), ("in-sub", "echo $(# " + CMD + NL + ")"),
            ("paren-in-comment", "echo $(: # )" + NL + CMD + NL + ")"),
            ("ends-at-newline", "echo a # note" + NL + CMD),
            ("backslash-comment", "echo a # note" + BS + NL + CMD),
            ("param-hash", "x=1; echo ${x#$(" + CMD + ")}"), ("hash-var", "echo $#$(" + CMD + ")"),
            ("brace-hash", "echo {a,#}$(" + CMD + ")")):
        out.append(Case(f"comment:{name}", tpl))
    # heredocs: delimiter quoting/spacing/tabs x body line
    for (spelling, term), line in product(HEREDOC_OPENERS, HEREDOC_LINES):
        indent = TAB if spelling.startswith("-") else ""
        out.append(Case(f"heredoc:{spelling!r}/{line[:12]!r}",
                        ": <<" + spelling + NL + indent + line + NL + term + NL + "echo done"))
    # heredocs: which line ENDS the body (a missed terminator runs the next line, or hides it)
    for (spelling, term), variant in product(HEREDOC_OPENERS[:14], TERMINATOR_VARIANTS):
        looks = variant.replace("{T}", term.strip(TAB))
        out.append(Case(f"terminator:{spelling!r}/{variant!r}",
                        ": <<" + spelling + NL + "safe" + NL + looks + NL + CMD + NL + term + NL))
    for name, tpl in (  # text sharing the opener line, and heredocs inside substitutions
            ("same-line", ": <<'EOF'; " + CMD + NL + "body" + NL + "EOF"),
            ("same-line-and", ": <<'EOF' && " + CMD + NL + "body" + NL + "EOF"),
            ("two-bodies", ": <<'A' <<B" + NL + "$(" + CMD + ")" + NL + "A" + NL + "$(" + CMD + ")"
             + NL + "B"),
            ("two-bodies-quoted", ": <<A <<'B'" + NL + "x" + NL + "A" + NL + "$(" + CMD + ")" + NL
             + "B"),
            ("in-sub-quoted", "echo $(: <<'EOF'" + NL + "$(" + CMD + ")" + NL + "EOF" + NL + ")"),
            ("in-sub-live", "echo $(: <<EOF" + NL + "$(" + CMD + ")" + NL + "EOF" + NL + ")"),
            ("in-sub-paren", "echo $(: <<'EOF'" + NL + ")" + NL + "EOF" + NL + CMD + NL + ")"),
            ("here-string", ": <<< " + DQ + "$(" + CMD + ")" + DQ),
            ("here-string-sq", ": <<< " + SQ + "$(" + CMD + ")" + SQ),
            ("unterminated-quoted", ": <<'EOF'" + NL + "$(" + CMD + ")"),
            ("unterminated-live", ": <<EOF" + NL + "$(" + CMD + ")"),
            ("paren-terminator", "x=$(: <<'EOF'" + NL + "x" + NL + "EOF)" + NL + CMD + NL + "EOF"
             + NL + ")"),
            ("paren-terminator-live", "x=$(: <<EOF" + NL + "x" + NL + "EOF)" + NL + CMD + NL + "EOF"
             + NL + ")"),
            ("arith-shift", "echo $((1 << 2))" + NL + CMD),
            ("arith-shift-dq", 'echo "$((1<<2))"' + NL + CMD)):
        out.append(Case(f"heredoc-shape:{name}", tpl))
    # nested substitutions
    for name, tpl in (
            ("dollar-dollar", "echo $(echo $(" + CMD + "))"),
            ("dollar-sq", "echo $(echo '$(" + CMD + ")')"),
            ("dq-dollar-sq", 'echo "$(echo ' + "'$(" + CMD + ")'" + ')"'),
            ("backtick-in-dollar", "echo $(echo `" + CMD + "`)"),
            ("dollar-in-backtick", "echo `echo $(" + CMD + ")`"),
            ("backtick-backtick", "echo `echo " + BS + "`" + CMD + BS + "``"),
            ("arith-dollar", "echo $(( $(" + CMD + ") ))"),
            ("param-default", "echo ${u:-$(" + CMD + ")}"),
            ("param-default-sq", "echo ${u:-'$(" + CMD + ")'}"),
            ("dq-param-default-sq", 'echo "${u:-' + "'$(" + CMD + ")'" + '}"'),
            ("assign", "x=$(" + CMD + ")"), ("assign-backtick", "x=`" + CMD + "`"),
            ("dq-paren", 'echo $(echo ")"; ' + CMD + ")"),
            ("sq-paren", "echo $(echo ')'; " + CMD + ")"),
            ("case-in-sub", "echo $(case x in x) " + CMD + ";; esac)"),
            ("case-in-sub-open", "echo $(case x in (x) " + CMD + ";; esac)"),
            ("case-in-sub-nl", "echo $(case x in" + NL + "x) " + CMD + ";;" + NL + "esac)"),
            ("funsub", "echo ${ " + CMD + "; }"), ("valsub", "echo ${| " + CMD + "; }"),
            ("procsub-in-dq", 'echo "<(' + CMD + ')"'),
            ("array", "a=( $(" + CMD + ") )"), ("array-index", "a[$(" + CMD + ")]=x"),
            ("cond", "[[ -n $(" + CMD + ") ]]"), ("for-list", "for i in $(" + CMD + "); do :; done"),
            ("case-word", "case $(" + CMD + ") in *) :;; esac")):
        out.append(Case(f"nested:{name}", tpl))
    # deferred execution and launch contexts the shell itself provides
    for name, tpl in (
            ("eval-sq", "eval " + sq(CMD)), ("eval-words", "eval " + CMD),
            ("bash-c", "bash -c " + sq(CMD)), ("bash-c-dq", "bash -c " + DQ + CMD + DQ),
            ("bash-c-newline", "bash -c " + sq("echo x" + NL + CMD)),
            ("eval-newline", "eval " + sq("echo x" + NL + CMD)),
            ("printed-head", "$(echo " + sq(CMD) + ")"), ("printed-backtick", BT + "echo " + sq(CMD) + BT),
            ("printed-printf", "$(printf '%s %s' " + HEAD + " " + sq(ARGS) + ")"),
            ("trap-exit", "trap " + sq(CMD) + " EXIT"), ("trap-dq", "trap " + DQ + CMD + DQ + " EXIT"),
            ("trap-dashdash", "trap -- " + sq(CMD) + " EXIT"),
            ("trap-unfired", "trap " + sq(CMD) + " USR2"),
            ("function-called", "f() { " + CMD + "; }; f"),
            ("function-multiline", "f() {" + NL + CMD + NL + "}" + NL + "f"),
            ("function-keyword", "function f { " + CMD + "; }; f"),
            ("function-uncalled", "f() { " + CMD + "; }"),
            ("alias-expanded", "shopt -s expand_aliases" + NL + "alias a=" + sq(CMD) + NL + "a"),
            ("alias-unexpanded", "alias a=" + sq(CMD) + NL + "a"),
            ("var-command", "c=" + sq(CMD) + "; $c"),
            ("var-command-braced", "c=" + sq(CMD) + NL + "${c}"),
            ("var-head", "c=" + HEAD + "; $c " + ARGS), ("var-head-quoted", "c=" + HEAD + '; "$c" ' + ARGS),
            ("var-head-export", "export c=" + HEAD + NL + "$c " + ARGS),
            ("var-quoted-whole", "c=" + sq(CMD) + '; "$c"'),
            ("var-assigned-only", "c=" + sq(CMD)),
            ("stdin-echo", "echo " + sq(CMD) + " | bash"),
            ("stdin-printf", "printf '%s" + BS + "n' " + sq(CMD) + " | bash"),
            ("stdin-printf-fmt", "printf " + sq("%s" + CMD) + " | bash"),
            ("stdin-printf-split", "printf '%s %s" + BS + "n' " + HEAD + " " + sq(ARGS) + " | bash"),
            ("stdin-heredoc", "bash <<'EOF'" + NL + CMD + NL + "EOF"),
            ("stdin-heredoc-live", "bash <<EOF" + NL + CMD + NL + "EOF"),
            ("stdin-herestring", "bash <<< " + sq(CMD)),
            ("stdin-cat-heredoc", "cat <<'EOF' | bash" + NL + CMD + NL + "EOF"),
            ("stdin-s", "echo " + sq(CMD) + " | bash -s"),
            ("script-file", "printf '%s" + BS + "n' " + sq(CMD) + " > s.sh; bash s.sh"),
            ("script-file-heredoc", "cat > s.sh <<'EOF'" + NL + CMD + NL + "EOF" + NL + "bash s.sh"),
            ("script-source", "echo " + sq(CMD) + " > s.sh && . ./s.sh"),
            ("script-written-only", "echo " + sq(CMD) + " > s.sh"),
            ("find-exec", "find . -maxdepth 0 -exec " + CMD + " " + BS + ";"),
            ("find-exec-plus", "find . -maxdepth 0 -exec " + CMD + " {} +"),
            ("coproc", "coproc " + CMD), ("time", "time " + CMD), ("negated", "! " + CMD),
            ("subshell", "( " + CMD + " )"), ("group", "{ " + CMD + "; }"),
            ("background", CMD + " &" + NL + "wait"), ("pipeline-tail", "echo x | " + CMD),
            ("while-body", "while :; do " + CMD + "; break; done"),
            ("until-cond", "until " + CMD + "; do :; done"),
            ("select-free", "echo " + sq(CMD)), ("colon-literal", ": " + sq(CMD)),
            ("printf-literal", "printf '%s" + BS + "n' " + DQ + BS + "$(" + CMD + ")" + DQ)):
        out.append(Case(f"launch:{name}", tpl))
    return out


# --- seeded compositions: the grid's contexts stacked two and three deep -------------------
def _wrappers():
    """(name, wrap(inner) -> outer or None). None: the context cannot hold this inner text."""
    def no(*chars):
        return lambda inner: not any(ch in inner for ch in chars)

    def sub(open_, close, ok=lambda _i: True):
        return lambda inner: (open_ + inner + close) if ok(inner) else None

    return (
        ("echo-dollar", sub("echo $(", ")")),
        ("echo-dq-dollar", sub('echo "$(', ')"')),
        ("echo-backtick", sub("echo `", "`", no(BT))),
        ("procsub", sub("cat <(", ")")),   # cat drains it: an unread pipe kills the writer
        ("assign", sub("x=$(", ")")),
        ("eval", lambda i: "eval " + sq(i)),
        ("bash-c", lambda i: "bash -c " + sq(i)),
        ("heredoc-live", sub(": <<EOF" + NL + "$(", ")" + NL + "EOF", no("EOF"))),
        ("heredoc-quoted", sub(": <<'EOF'" + NL + "$(", ")" + NL + "EOF", no("EOF"))),
        ("heredoc-dash", sub(": <<-EOF" + NL + TAB + "$(", ")" + NL + TAB + "EOF", no("EOF"))),
        ("comment", sub("# ", "", no(NL))),
        ("trailing-comment", sub("", " # ) note", no(NL))),
        ("and", sub(": && ", "")), ("semi", sub("echo x; ", "")), ("newline", sub("echo x" + NL, "")),
        ("group", sub("{ ", "; }")), ("subshell", sub("( ", " )")),
        ("if", sub("if :; then ", "; fi")), ("function", sub("f() { ", "; }; f")),
        ("continued", sub("echo a" + BS + NL + "#$(", ")", no(NL))),
        ("escaped-opener", sub("echo " + BS + "$(", ")")),
        ("sq-literal", lambda i: "echo " + sq(i)),
        ("param-default", sub("echo ${u:-$(", ")}", no("}"))),
        ("here-string", sub(": <<< " + DQ + "$(", ")" + DQ, no(DQ))),
        ("trap", lambda i: "trap " + sq(i) + " EXIT"),
        ("stdin-shell", lambda i: "echo " + sq(i) + " | bash"),
    )


def compositions(count, seed=SEED):
    rng = random.Random(seed)
    wrappers = _wrappers()
    out, seen, tries = [], set(), 0
    while len(out) < count and tries < count * 50:
        tries += 1
        text, names = CMD, []
        for _ in range(rng.choice((2, 2, 3))):
            name, wrap = rng.choice(wrappers)
            nxt = wrap(text)
            if nxt is not None:
                text, names = nxt, names + [name]
        if len(names) < 2 or text in seen:
            continue
        seen.add(text)
        out.append(Case("random:" + "/".join(names), text, rng.choice(tuple(PAYLOADS))))
    return out


def corpus(random_count=BOUNDED_RANDOM, seed=SEED, both=False):
    cases = []
    for k, case in enumerate(grid()):
        payloads = tuple(PAYLOADS) if both else (tuple(PAYLOADS)[k % len(PAYLOADS)],)
        cases += [Case(case.family, case.template, p) for p in payloads]
    for case in compositions(random_count, seed):
        payloads = tuple(PAYLOADS) if both else (case.payload,)
        cases += [Case(case.family, case.template, p) for p in payloads]
    return cases


# --- the oracle: real bash, inert sentinel, throwaway directory ----------------------------
class BashOracle:
    def __init__(self, bash=None):
        self.bash = bash or shutil.which("bash") or "/bin/bash"
        self.root = Path(tempfile.mkdtemp(prefix="dh-oracle-"))
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        sentinel = self.bindir / SENTINEL
        # It records its own argv: the hole RAN only when the sentinel got the payload's words,
        # so `{HEAD};{ARGS}` (the head alone, then a stray command) is not a run of the payload.
        sentinel.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$ORCA_SENTINEL_MARK\"\n",
                            encoding="utf-8")
        sentinel.chmod(0o755)
        # Harmless helpers only: the templates call bash -c, cat and find. Nothing else resolves.
        for tool in ("bash", "cat", "find"):
            real = self.bash if tool == "bash" else shutil.which(tool)
            if real:
                (self.bindir / tool).symlink_to(real)
        self._n = 0
        self._lock = threading.Lock()
        self.version = subprocess.run([self.bash, "-c", "printf %s \"$BASH_VERSION\""],
                                      capture_output=True, text=True, timeout=BASH_TIMEOUT).stdout

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run(self, text, args=""):
        """(sentinel ran with args leading its argv, bash reported a parse error) for a safe form."""
        if not safe_form_ok(text):
            raise ValueError(f"a safe form may reach only the sentinel: {text!r}")
        with self._lock:
            self._n += 1
            work = self.root / f"case-{self._n}"
        work.mkdir()
        mark = work / ".sentinel"
        env = {"PATH": str(self.bindir), "HOME": str(work), "TMPDIR": str(work), "LC_ALL": "C",
               "ORCA_SENTINEL_MARK": str(mark)}
        # CPU seconds, file size and core limits are set by the parent sh before bash starts:
        # preexec_fn is not safe beside the worker threads.
        limited = ['/bin/sh', '-c', 'ulimit -t 5 2>/dev/null; ulimit -f 2048 2>/dev/null; '
                   'ulimit -c 0 2>/dev/null; exec "$0" --norc --noprofile -c "$1"', self.bash, text]
        proc = subprocess.Popen(limited, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                start_new_session=True)
        try:
            _out, err = proc.communicate(timeout=BASH_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 9)
            _out, err = proc.communicate()
        err = err.decode("utf-8", "replace")
        # A parse error refuses to run the text: bash exits 2 for a syntax error and 1 for a bad
        # substitution, so the message, not the status, says which runs ended there.
        syntax = bool(re.search(r"syntax error|unexpected EOF|unexpected end of file|"
                                r"bad substitution|here-document .* delimited by end-of-file",
                                err))
        want = args.split()
        ran = mark.exists() and any(line.split()[:len(want)] == want
                                    for line in mark.read_text(encoding="utf-8").splitlines())
        shutil.rmtree(work, ignore_errors=True)
        return ran, syntax


def safe_form_ok(text):
    """False when the text names a real tool (git, gh, rm, curl, ssh, ...) -- never run it."""
    return not (_REAL_TOOLS.search(text) or "orca" in text.replace(SENTINEL, ""))


def hook_decision(text, hook=HOOK, cwd=None):
    """allow / ask / deny for one forbidden form, as the hook's Claude Code contract reports it."""
    env = {k: v for k, v in os.environ.items() if k not in _SCRUB}
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                          "tool_input": {"command": text}})
    proc = subprocess.run(["sh", str(hook)], input=payload, capture_output=True, text=True,
                          env=env, cwd=cwd or tempfile.gettempdir(), timeout=HOOK_TIMEOUT)
    if not proc.stdout.strip():
        return "allow" if proc.returncode == 0 else "deny"
    try:
        return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
    except (ValueError, KeyError, TypeError):
        return "deny"   # a hook that answered something unreadable refused, as far as a host knows


def classify(ran, syntax, decision, payload="push"):
    if ran:
        if decision == "allow":
            return "miss"
        return "downgrade" if decision == "ask" and EXPECT[payload] == "deny" else "agree"
    if decision == "allow":
        return "agree"
    return "fail-closed" if syntax else "false-deny"


def evaluate(cases, oracle, hook=HOOK, jobs=4, bash_cache=None):
    """One result dict per case, in order. bash_cache maps safe text -> (ran, syntax)."""
    cache = {} if bash_cache is None else bash_cache

    def one(case):
        safe = render(case.template, case.payload, True)
        if safe not in cache:
            cache[safe] = oracle.run(safe, PAYLOADS[case.payload][1])
        ran, syntax = cache[safe]
        decision = hook_decision(render(case.template, case.payload, False), hook)
        return {"id": case.id, "family": case.family, "payload": case.payload,
                "template": case.template, "ran": ran, "syntax": syntax, "decision": decision,
                "verdict": classify(ran, syntax, decision, case.payload)}

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        return list(pool.map(one, cases))


def summary(results):
    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    controls = [r for r in results if not r["ran"]]
    return {"cases": len(results), "live": sum(r["ran"] for r in results),
            "allow_controls": len(controls), **counts}


def mismatches(results):
    return [r for r in results if r["verdict"] in ("miss", "downgrade", "false-deny")]


# --- minimization: ddmin over the template, placeholders atomic ----------------------------
def _atoms(template):
    return re.findall(r"\{CMD\}|\{HEAD\}|\{ARGS\}|.", template, re.DOTALL)


# A shrink may not glue a word character onto the payload: `{CMD}i` names another command.
_GLUED = re.compile(r"(\{CMD\}|\{ARGS\})[A-Za-z0-9_./-]|[A-Za-z0-9_./-]\{(CMD|HEAD)\}")


def ddmin(template, keeps):
    """The smallest template (by ddmin) for which keeps(template) still holds."""
    atoms, n = _atoms(template), 2
    while len(atoms) >= 2:
        chunk = max(1, len(atoms) // n)
        reduced = False
        for start in range(0, len(atoms), chunk):
            trial = atoms[:start] + atoms[start + chunk:]
            text = "".join(trial)
            if trial and any(p in text for p in (CMD, HEAD)) and keeps(text):
                atoms, n, reduced = trial, max(n - 1, 2), True
                break
        if not reduced:
            if n >= len(atoms):
                break
            n = min(len(atoms), n * 2)
    return "".join(atoms)


def minimize(result, oracle, hook=HOOK):
    """Shrink one mismatch to the smallest template that still disagrees the same way."""
    want = result["verdict"]

    def keeps(template):
        safe = render(template, result["payload"], True)
        if (HEAD in template and ARGS not in template) or not safe_form_ok(safe) \
                or _GLUED.search(template):
            return False   # never run a real tool name; never glue text onto the payload words
        ran, syntax = oracle.run(safe, PAYLOADS[result["payload"]][1])
        decision = hook_decision(render(template, result["payload"], False), hook)
        return classify(ran, syntax, decision, result["payload"]) == want

    return ddmin(result["template"], keeps)


def load_fixtures(path=FIXTURES):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def add_fixtures(doc, found, bash_version, seed, hook_label):
    """Append each mismatch (minimized template when present) not already stored; return count."""
    known = {(f["payload"], f["template"]) for f in doc["fixtures"]}
    added = 0
    for r in found:
        tpl = r.get("minimized", r["template"])
        if (r["payload"], tpl) in known:
            continue
        known.add((r["payload"], tpl))
        doc["fixtures"].append({
            "kind": r["verdict"], "payload": r["payload"], "template": tpl,
            "original": r["template"], "family": r["family"], "bash": bash_version,
            "seed": seed, "hook": hook_label, "status": "open", "note": ""})
        added += 1
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--hook", default=str(HOOK))
    ap.add_argument("--hook-label", default="working tree",
                    help="the hook revision a written fixture names (e.g. origin/main@<sha>)")
    ap.add_argument("--bash", default=None)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--random", type=int, default=BOUNDED_RANDOM)
    ap.add_argument("--both", action="store_true", help="judge every case with every payload")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--list", action="store_true", help="print the forbidden forms and exit")
    ap.add_argument("--minimize", action="store_true")
    ap.add_argument("--write", action="store_true", help="append mismatches to the fixtures")
    ap.add_argument("--fixtures", default=str(FIXTURES))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    cases = corpus(args.random, args.seed, args.both)
    if args.list:
        for case in cases:
            print(json.dumps({"id": case.id, "family": case.family,
                              "forbidden": render(case.template, case.payload, False)}))
        return 0
    oracle = BashOracle(args.bash)
    try:
        started = time.monotonic()
        results = evaluate(cases, oracle, args.hook, args.jobs)
        found = mismatches(results)
        report = {"bash": oracle.version, "seed": args.seed, "seconds":
                  round(time.monotonic() - started, 1), **summary(results)}
        if args.minimize and found:
            with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
                for r, small in zip(found, pool.map(lambda r: minimize(r, oracle, args.hook),
                                                    found), strict=True):
                    r["minimized"] = small
        if args.write and found:
            doc = load_fixtures(args.fixtures)
            report["written"] = add_fixtures(doc, found, oracle.version, args.seed,
                                             args.hook_label)
            Path(args.fixtures).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
        if args.json:
            print(json.dumps({"report": report, "mismatches": found}, indent=2))
        else:
            print(json.dumps(report))
            for r in found:
                print(f"{r['verdict']:10} {r['family']}: "
                      f"{render(r.get('minimized', r['template']), r['payload'], False)!r}")
        return 1 if found else 0
    finally:
        oracle.close()


if __name__ == "__main__":
    sys.exit(main())
