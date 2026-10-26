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
    The sentinel appends its argv to a marker file, so "bash ran the hole with the payload's
    words" is an observation, not an inference;
  * the FORBIDDEN form puts a refused command in the same hole (`git push --force origin main`,
    HIGH tier; `gh issue close 34`, rule 5; `rm -r -f ./build`, a Never-list ask) and is fed
    ONLY to the hook as a PreToolUse payload. It is never executed, and no safe form may name
    git, gh, rm or another real tool (checked before every run, minimizer shrinks included).

Scoring keeps the two error directions apart:

  * MISS       -- bash ran the sentinel and the hook allowed the forbidden form (a hole);
  * DOWNGRADE  -- bash ran it and the hook only asked a HIGH or rule 5 shape (they must deny);
  * FALSE-DENY -- bash ran nothing and the hook refused. Literal documentation examples
                  (quoted heredocs, single quotes, comments, escaped openers) are the allow
                  controls; a refusal of text bash treats as a syntax error is counted as
                  fail-closed, not as a false denial.

Every mismatch is minimized (ddmin over the template, placeholders atomic) and stored in
tests/fixtures/deny_hook_conformance.json with the bash version and seed that found it.
tests/test_deny_hook_conformance.py runs the bounded corpus in CI and replays the fixtures.

Usage:
  python3 scripts/deny_hook_corpus.py                      bounded corpus (the CI one), report
  python3 scripts/deny_hook_corpus.py --random 2000 --both larger corpus, every payload per case
  python3 scripts/deny_hook_corpus.py --minimize --write   minimize mismatches into the fixtures
  python3 scripts/deny_hook_corpus.py --list               print the rendered forbidden forms
  --hook PATH   judge another copy of the hook (a mutant, or `git show <base>:...`)
  --both        judge every case with every payload (default: one payload per case, rotating)
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
# Guard mode (PR #648 review): the hole is a guarded FILE, not a command. The safe form names a
# decoy copy of it (_decoy) inside the throwaway directory, and "ran" means bash deleted or
# changed that decoy; the forbidden form names the real path and is only ever judged. Payload
# "guard:<path>". Mirrors GUARD_SAMPLES in the hook (a test keeps the two equal).
GUARD_SAMPLES = (".claude/settings.json", ".claude/settings.local.json", ".codex/hooks.json",
                 ".openhands/hooks.json", ".agents/plugins/orca-deny-hook/hooks/hooks.json",
                 ".opencode/plugin/orca-deny-hook.ts", ".open-fleet/hooks/deny-hook.sh",
                 ".open-fleet/bridges/omp_pi_deny_bridge.ts", ".crush/crush.json",
                 ".crush-orca-ro/crush.json", ".hermes-open-fleet/config.yaml",
                 ".orca/human-grant-pubkey", ".orca/dispatch-pubkey")
GUARD_FIND_SAMPLES = (".orca/human-grant-pubkey", ".orca/dispatch-pubkey", ".claude/settings.json")
DELETER = "dcoy_unlink"   # the safe form's rm: deletes only inside the throwaway directory
# Receipt mode (PR #648 review): payload "receipt". {R} is an egress receipt and {SEND} an
# off-repo write. The safe form uses a receipt sentinel that records "R" (exiting 0, or 1 in a
# second run) and the send sentinel; "ran" means some send in bash was NOT covered by a fresh
# successful receipt -- one receipt per send, counted at run time, not inferred from the text.
RECEIPT_SENTINEL = "dcoy_receipt"
RECEIPT_FORM = "python3 runtime/scripts/egress.py write --payload-class pr-body --consent grant:x"
SEND_ARGS = "issue close 34"
LATER = "{LATER}"
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


def payload_kind(payload):
    if payload == "receipt":
        return "receipt"
    return "guard" if payload.startswith("guard:") else "cmd"


def expect(payload):
    """The refusal a live hole earns: deny, or ask for a Never-list shape."""
    return EXPECT.get(payload, "deny")


def _decoy(path):
    """The throwaway twin of a guarded path: same shape, first segment and any orca renamed."""
    first, _sep, rest = path.partition("/")
    first = ("." + "x" * (len(first) - 1)) if first.startswith(".") else "x" * len(first)
    return (first + "/" + rest).replace("orca", "xxxx")


def render(template, payload, safe, root=None):
    """The safe (oracle) or forbidden (hook) form of a template. {ROOT} stays for the caller
    unless root is given: the oracle fills in its own directory, the hook side its cwd."""
    if payload_kind(payload) == "guard":
        path = _decoy(payload[6:]) if safe else payload[6:]
        folder, name = os.path.split(path)
        text = (template.replace("{GPU}", path.upper()).replace("{GP}", path)
                .replace("{GD}", folder).replace("{GNU}", name.upper()).replace("{GN}", name)
                .replace("{DEL}", DELETER if safe else "rm"))
        return text if root is None else text.replace("{ROOT}", root)
    if payload_kind(payload) == "receipt":
        return (template.replace("{R}", RECEIPT_SENTINEL + " write" if safe else RECEIPT_FORM)
                .replace("{SEND}", (SENTINEL if safe else "gh") + " " + SEND_ARGS))
    head, args = PAYLOADS[payload]
    head = SENTINEL if safe else head
    c = head[0]
    esc = {"{HX}": "\\x%02x" % ord(c), "{HO}": "\\0%03o" % ord(c),   # \x67it / \0147it (%b octal)
           "{HOF}": "\\%03o" % ord(c), "{HU}": "\\u%04x" % ord(c)}   # \147it (printf FORMAT)
    text = template
    for token, enc in esc.items():
        text = text.replace(token, enc + head[1:])
    return text.replace(CMD, head + " " + args).replace(HEAD, head).replace(ARGS, args)


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
    # several heredocs on one line (PR #648 review PRRT_kwDOTWxN9c6vxmAb): bash gives a command
    # the LAST stdin heredoc, and every command on the line gets its own bodies in order.
    for name, tpl in (
            ("second", "bash <<A <<B" + NL + "echo safe" + NL + "A" + NL + CMD + NL + "B"),
            ("first-discarded", "bash <<A <<B" + NL + CMD + NL + "A" + NL + "echo safe" + NL + "B"),
            ("quoted-second", "bash <<'A' <<\"B\"" + NL + "echo safe" + NL + "A" + NL + CMD + NL + "B"),
            ("dash-second", "bash <<A <<-B" + NL + "echo safe" + NL + "A" + NL + TAB + CMD + NL
             + TAB + "B"),
            ("and-chain", "bash <<A && bash <<B" + NL + "echo safe" + NL + "A" + NL + CMD + NL + "B"),
            ("semi-chain", "bash <<A; bash <<B" + NL + "echo safe" + NL + "A" + NL + CMD + NL + "B"),
            ("pipe-in", "cat <<A <<B | bash" + NL + "echo safe" + NL + "A" + NL + CMD + NL + "B"),
            ("pipe-out", "bash <<A | cat" + NL + CMD + NL + "A"),
            ("other-fd", "bash <<A 3<<B" + NL + CMD + NL + "A" + NL + "echo safe" + NL + "B"),
            ("herestrings", "bash <<< 'echo safe' <<< " + sq(CMD)),
            ("cat-herestring", "cat <<< " + sq(CMD) + " | bash"),
            ("in-sub", "echo $(bash <<'A' <<'B'" + NL + "echo safe" + NL + "A" + NL + CMD + NL + "B"
             + NL + ")")):
        out.append(Case(f"multi-heredoc:{name}", tpl))
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
            # escaped command words fed to a shell (PR #648 review): printf/echo decode these.
            ("esc-printf-fmt-hex", "printf " + sq("{HX} " + ARGS) + " | sh"),
            ("esc-printf-fmt-oct", "printf " + sq("{HOF} " + ARGS) + " | sh"),
            ("esc-printf-b-hex", "printf '%b' " + sq("{HX} " + ARGS) + " | bash"),
            ("esc-printf-b-oct", "printf '%b' " + sq("{HO} " + ARGS) + " | bash"),
            ("esc-printf-b-split", "printf '%b %s" + BS + "n' " + sq("{HX}") + " " + sq(ARGS) + " | sh"),
            ("esc-echo-e-hex", "echo -e " + sq("{HX} " + ARGS) + " | sh"),
            ("esc-printf-head-sub", "$(printf " + sq("{HX}") + ") " + ARGS),
            ("esc-printf-v-head", "printf -v c " + sq("{HX}") + "; $c " + ARGS),
            ("stdin-heredoc", "bash <<'EOF'" + NL + CMD + NL + "EOF"),
            ("stdin-heredoc-live", "bash <<EOF" + NL + CMD + NL + "EOF"),
            ("stdin-herestring", "bash <<< " + sq(CMD)),
            ("stdin-cat-heredoc", "cat <<'EOF' | bash" + NL + CMD + NL + "EOF"),
            ("stdin-s", "echo " + sq(CMD) + " | bash -s"),
            ("script-file", "printf '%s" + BS + "n' " + sq(CMD) + " > s.sh; bash s.sh"),
            ("script-file-heredoc", "cat > s.sh <<'EOF'" + NL + CMD + NL + "EOF" + NL + "bash s.sh"),
            ("script-source", "echo " + sq(CMD) + " > s.sh && . ./s.sh"),
            ("script-written-only", "echo " + sq(CMD) + " > s.sh"),
            ("script-dotslash-run", "printf '%s' " + sq(CMD) + " > ./s.sh; sh s.sh"),
            ("find-exec", "find . -maxdepth 0 -exec " + CMD + " " + BS + ";"),
            ("find-exec-plus", "find . -maxdepth 0 -exec " + CMD + " {} +"),
            ("coproc", "coproc " + CMD), ("time", "time " + CMD), ("negated", "! " + CMD),
            ("subshell", "( " + CMD + " )"), ("group", "{ " + CMD + "; }"),
            ("background", CMD + " &" + NL + "wait"), ("pipeline-tail", "echo x | " + CMD),
            ("while-body", "while :; do " + CMD + "; break; done"),
            ("until-cond", "until " + CMD + "; do :; done"),
            ("select-free", "echo " + sq(CMD)), ("colon-literal", ": " + sq(CMD)),
            ("printf-literal", "printf '%s" + BS + "n' " + DQ + BS + "$(" + CMD + ")" + DQ),
            ("xargs-append", "echo main | xargs " + HEAD + " push --force origin")):
        out.append(Case(f"launch:{name}", tpl))
    return out


# parallel builds its command by replacing {} with, or appending, each ::: argument (PR #648
# review PRRT_kwDOTWxN9c6vvZVr). The `parallel` binary is not on every host, so this family is
# hook-only (judged, never executed); tests/test_deny_hook_conformance.py asserts each denies.
def parallel_family():
    heads = {"push": ("git", "push --force origin main", "--force"),
             "send": ("gh", "issue close 34", "close")}
    cases = []
    for payload, (_h, _full, arg) in heads.items():
        rest = PAYLOADS[payload][1]
        before, _sep, after = rest.partition(arg)
        variants = [
            ("run", "parallel {HEAD} " + rest + " :::"),
            ("placeholder", "parallel {HEAD} " + before + "{} " + after + " ::: " + arg),
            ("jobs", "parallel -j2 {HEAD} " + before + "{} " + after + " ::: " + arg),
            ("numbered", "parallel {HEAD} " + before + "{1} " + after + " ::: " + arg),
            ("colsep", "parallel --colsep , {HEAD} " + before + "{1} " + after + " ::: " + arg)]
        if payload == "push":   # a force flag appended at the end still forces the push
            variants.append(("append", "parallel {HEAD} " + (before + after).strip()
                             + " ::: " + arg))
        for name, tpl in variants:
            cases.append(Case(f"parallel:{name}", tpl, payload))
    return cases


# Brace expansion (2026-10-26 review): bash expands `--force{,}` to two words before anything
# else runs, so the refused flag never appeared as a word to the hook. The oracle cannot score
# these -- it counts a run only when the sentinel receives the payload's words exactly, and an
# expansion by construction yields other words -- so, like parallel, the family is hook-only:
# tests/test_deny_hook_conformance.py asserts each form is refused.
def brace_family():
    cases = []
    for name, tpl in (
            ("force-dup", "{HEAD} push --force{,} origin main"),
            ("force-alt", "{HEAD} push {--force,} origin main"),
            ("force-split", "{HEAD} push --fo{rce,rce} origin main"),
            ("force-late", "{HEAD} push origin --force{,} main"),
            ("force-feature", "{HEAD} push --force{,} origin feature")):
        cases.append(Case(f"brace:{name}", tpl, "push"))
    for name, tpl in (
            ("root-dup", "{HEAD} -rf /{,}"), ("flag-split", "{HEAD} -r{,}f /")):
        cases.append(Case(f"brace:{name}", tpl, "wipe"))
    return cases


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


# find predicates (PR #648 review, P1): which spellings PROVE a guard file is not deleted. Case,
# negation, -o, grouping, absolute and relative -path forms, -delete position, -exec rm {}.
GUARD_FIND = (
    "find {GD} -delete", "find {GD} -name {GN} -delete", "find {GD} -name other.txt -delete",
    "find {GD} ! -name other.txt -delete", "find {GD} -not -name other.txt -delete",
    "find {GD} -name other.txt -o -name {GN} -delete",
    "find {GD} \\( -name other.txt -o -name {GN} \\) -delete",
    "find {GD} -iname {GNU} -delete", "find {GD} -iname 'OTHER*' -delete",
    "find {GD} -name {GNU} -delete", "find {ROOT} -iwholename '{ROOT}/{GPU}' -delete",
    "find {GD} ! -name xxx -delete",
    "find {GD} -path '{GD}/*' -delete", "find {GD} -path './{GD}/*' -delete",
    "find ./{GD} -path './{GD}/*' -delete", "find {ROOT}/{GD} -path '{ROOT}/{GD}/*' -delete",
    "find {ROOT} -path '{ROOT}/{GP}' -delete", "find {ROOT} -ipath '{ROOT}/{GPU}' -delete",
    "find {ROOT} -path '{ROOT}/notes/*' -delete", "find . -wholename './{GP}' -delete",
    "find . -name '*.txt' -delete", "find . -type f -delete", "find . -type f -name {GN} -delete",
    "find . -delete -name nothing", "find {GD} -name {GN} -exec {DEL} {} \\;",
    "find {GD} -name {GN} -exec {DEL} {} +", "find {GD} -name other.txt -exec {DEL} {} +",
    "find {GD} -type f -exec {DEL} -f {} +", "find {GD} -iname {GNU} -execdir {DEL} {} \\;",
    "find {GD} -maxdepth 1 -name {GN} -delete", "find {GD} -regex '.*{GN}' -delete",
    "find {ROOT}/notes -delete", "find notes {GD} -name keep.txt -delete",
)


def guard_grid(every=False):
    """Guard-mode cases: every find spelling over the anchors (every guarded path if asked)."""
    samples = GUARD_SAMPLES if every else GUARD_FIND_SAMPLES
    return [Case(f"guard-find:{k}", tpl, "guard:" + s)
            for k, tpl in enumerate(GUARD_FIND) for s in samples]


# Receipts: does every send run under a fresh successful receipt? Several heredocs on a line
# (PRRT_kwDOTWxN9c6vxmAb) and a receipt carried into a fed program (PRRT_kwDOTWxN9c6vvZV5).
RECEIPT_GRID = (
    ("and", "{R} && {SEND}"), ("semi", "{R}; {SEND}"), ("or", "{R} || {SEND}"),
    ("two-sends", "{R} && {SEND}; {SEND}"), ("and-two", "{R} && {SEND} && {SEND}"),
    ("sh-c", "{R} && sh -c '{SEND}'"), ("sh-c-two", "{R} && sh -c '{SEND}; {SEND}'"),
    ("echo-pipe", "{R} && echo '{SEND}' | sh"), ("echo-pipe-two", "{R} && echo '{SEND}; {SEND}' | sh"),
    ("heredoc", "{R} && sh <<'EOF'\n{SEND}\nEOF"),
    ("heredoc-second", "sh <<A <<B\necho safe\nA\n{SEND}\nB"),
    ("heredoc-second-and", "{R} && sh <<A <<B\necho safe\nA\n{SEND}\nB"),
    ("heredoc-dash-second", "sh <<A <<-B\necho safe\nA\n\t{SEND}\n\tB"),
    ("heredoc-quoted-second", "sh <<'A' <<\"B\"\necho safe\nA\n{SEND}\nB"),
    ("heredoc-two-shells", "{R} && sh <<A && sh <<B\n{SEND}\nA\n{SEND}\nB"),
    ("heredoc-semi", "sh <<A; sh <<B\necho safe\nA\n{SEND}\nB"),
    ("heredoc-pipe", "cat <<A | sh\n{SEND}\nA"), ("heredoc-pipe-and", "{R} && cat <<A | sh\n{SEND}\nA"),
    ("herestring-two", "sh <<< 'echo safe' <<< '{SEND}'"), ("herestring-cat", "cat <<< '{SEND}' | sh"),
    ("sub-heredoc", "echo $(sh <<'EOF'\n{SEND}\nEOF\n)"),
    ("sub-heredoc-inner", "echo $({R} && sh <<'EOF'\n{SEND}\nEOF\n)"),
)


# Launchers that may run their command more than once (PR #648 review PRRT_kwDOTWxN9c6vxmAh):
# find -exec per match, xargs per batch, loop conditions per iteration. One receipt, one send.
REPEAT_GRID = (
    ("find-each", "{R} && find . -type f -exec {SEND} \\;"),
    ("find-each-dir", "{R} && find . -type f -execdir {SEND} \\;"),
    ("find-batch", "{R} && find . -type f -exec {SEND} {} +"),
    ("find-one", "{R} && find . -maxdepth 0 -exec {SEND} \\;"),
    ("find-inner", "find . -type f -exec sh -c '{R} && {SEND}' \\;"),
    ("xargs-file", "{R} && xargs -n1 {SEND} < list.txt"),
    ("xargs-batch", "{R} && xargs {SEND} < list.txt"),
    ("xargs-pipe", "{R} && printf '1\\n2\\n' | xargs -n1 {SEND}"),
    ("xargs-inner", "xargs -n1 sh -c '{R} && {SEND}' < list.txt"),
    ("until-once", "{R} && until {SEND}; do :; done"),
    ("until-twice", "{R} && until {SEND} && [ -e stop ]; do : > stop; done"),
    ("while-twice", "{R} && while {SEND} && [ ! -e stop ]; do : > stop; done"),
    ("for", "{R} && for i in 1 2; do {SEND}; done"),
    ("for-inner", "for i in 1 2; do {R} && {SEND}; done"),
    ("while-inner", "i=0; while [ $i -lt 2 ]; do i=$((i+1)); {R} && {SEND}; done"),
)


def receipt_grid():
    return [Case(f"receipt:{name}", tpl, "receipt") for name, tpl in RECEIPT_GRID + REPEAT_GRID]


# Who reads which body (PR #648 review PRRT_kwDOTWxN9c6vzGqz, PRRT_kwDOTWxN9c6vzGq3): a heredoc
# or here-string on a reader, crossed with every redirection form in every position and every
# pipeline position (first, middle, last, |&). {X} is the hole: {CMD}, or {SEND} in receipt mode.
# These run under bash AND dash (DASH_FAMILIES): a hole either shell runs must be refused.
STDIN_SOURCES = (   # (name, redirection on the reader, the body lines after the command line)
    ("heredoc", "<<EOF", "{X}" + NL + "EOF"), ("heredoc-q", "<<'EOF'", "{X}" + NL + "EOF"),
    ("heredoc-dash", "<<-EOF", TAB + "{X}" + NL + TAB + "EOF"), ("herestring", "<<< '{X}'", ""),
    ("fd0-heredoc", "0<<EOF", "{X}" + NL + "EOF"), ("fd0-herestring", "0<<< '{X}'", ""),
    ("dup-heredoc", "3<<EOF 0<&3", "{X}" + NL + "EOF"), ("dup-herestring", "3<<< '{X}' 0<&3", ""),
    # controls: a body on another descriptor, or dup-ed before it opens, is never read
    ("fd3-heredoc", "3<<EOF", "{X}" + NL + "EOF"), ("dup-early", "0<&3 3<<EOF", "{X}" + NL + "EOF"),
)
STDIN_READERS = ("bash", "sh", "bash -s", "sh /dev/stdin")
STDIN_REDIRS = ("", "> /dev/null", ">/dev/null 2>&1", "2>&1", "2>/dev/null", "&>/dev/null",
                ">> out.txt", "> out.txt", ">&2", "1>&2", ">| out.txt", "3>&1", "< /dev/null")
STDIN_PIPES = (("alone", "{C}"), ("first", "{C} | cat"), ("first-amp", "{C} |& cat"),
               ("middle", "echo safe | {C} | cat"), ("last", "echo safe | {C}"),
               ("last-amp", "echo safe |& {C}"), ("middle-amp", "echo safe |& {C} |& cat"),
               ("and", "true && {C}"))
# A body reaching a reader through another command: a pass-through stage, a group, a loop, a
# function, exec, xargs, read, a process substitution, $(cat) reading the pipe.
STDIN_ROUTES = (
    ("cat-pipe", "cat {S} | {READER}"), ("cat-tee", "cat {S} | tee t.txt | {READER}"),
    ("cat-cat", "cat {S} | cat | {READER}"), ("cat-amp", "cat {S} |& {READER}"),
    ("cat-quiet", "cat {S} 2>/dev/null | {READER}"), ("echo-cat", "echo '{X}' | cat | {READER}"),
    ("echo-amp", "echo '{X}' |& {READER}"), ("printf-amp", "printf '%s\\n' '{X}' |& cat |& {READER}"),
    ("group", "{ {READER}; } {S}"), ("subshell", "( {READER} ) {S}"),
    ("subshell-cd", "(cd .; {READER}) {S}"), ("group-late", "{ {READER}; true; } {S}"),
    ("pipe-group", "echo '{X}' | { true; {READER}; }"), ("pipe-subshell", "echo '{X}' | (cd .; {READER})"),
    ("while-read", "while read -r l; do $l; done {S}"), ("read-var", "read -r l {S}; $l"),
    ("pipe-read", "echo '{X}' | while read -r l; do $l; done"), ("exec", "exec {S}; {READER}"),
    ("func", "f() { {READER}; }; f {S}"), ("func-glued", "f(){ {READER};};f {S}"), ("xargs-i", "xargs -I{} {READER} -c '{}' {S}"),
    ("procsub", "{READER} <(echo '{X}')"), ("procsub-stdin", "{READER} < <(echo '{X}')"),
    ("procsub-cat", "{READER} <(cat {S})"), ("eval-cat", "echo '{X}' | eval \"$(cat)\""),
    ("eval-sub", "eval \"$(cat {S})\""), ("head-sub", "$(cat {S})"),
    ("eval-sub-heredoc", "eval \"$(cat <<EOF" + NL + "{X}" + NL + "EOF" + NL + ")\""),
    ("head-sub-heredoc", "$(cat <<EOF" + NL + "{X}" + NL + "EOF" + NL + ")"),
    # allow controls: the body is data -- written, printed, or handed to a command that ignores
    # its standard input -- and must stay allowed
    ("control/cat-file", "cat {S} > notes.txt"), ("control/cat-tee", "cat {S} | tee notes.txt"),
    ("control/tee", "tee notes.txt {S}"), ("control/cat-cat-file", "cat {S} | cat > notes.txt"),
    ("control/null", ": {S}"), ("control/sh-c", "{READER} -c 'echo hi' {S}"),
    ("control/sh-c-cat", "{READER} -c cat {S}"), ("control/group-cat", "{ cat; } {S}"),
    ("control/read-echo", "read -r l {S}; echo \"$l\""), ("control/xargs-echo", "xargs echo {S}"),
    ("control/echo-file", "echo '{X}' > notes.txt"), ("control/echo-cat-file", "echo '{X}' | cat > notes.txt"),
)


def _stdin_text(line, body, x, armed=False):
    """One template: the command line (receipt-armed if asked), then any heredoc body lines."""
    text = ("{R} && " if armed else "") + line
    return (text + NL + body if body else text).replace("{X}", x)


def _reader_cmd(reader, src, redir, where):
    parts = {"pre": (redir, reader, src), "mid": (reader, redir, src), "post": (reader, src, redir)}
    return " ".join(w for w in parts[where] if w)


def stdin_grid(every=False):
    """Command-mode cases (payloads rotating) and receipt-mode cases for the stdin family. The
    bounded set crosses each source with each redirection and with each pipeline position, each
    reader with each source, and every route; every=True is the whole product (readers bash and
    sh /dev/stdin). Receipt mode: each case unreceipted, and receipted where bash reads one body."""
    cmd, rcpt = [], []
    readers = ("bash", "sh /dev/stdin") if every else STDIN_READERS
    combos = []
    if every:
        combos = [(r, s, d, w, p) for r in readers for s in STDIN_SOURCES for d in STDIN_REDIRS
                  for w in ("pre", "mid", "post") for p in STDIN_PIPES]
    else:
        wheres = ("pre", "mid", "post")
        for k, (s, d) in enumerate(product(STDIN_SOURCES, STDIN_REDIRS)):
            w = wheres[k % 3] if d != "< /dev/null" else "pre"
            combos.append(("bash", s, d, w, STDIN_PIPES[0]))
        for k, (s, p) in enumerate(product(STDIN_SOURCES, STDIN_PIPES)):
            combos.append((STDIN_READERS[k % len(STDIN_READERS)], s, "> /dev/null", "mid", p))
        combos += [(r, s, "", "post", STDIN_PIPES[0]) for r in STDIN_READERS for s in STDIN_SOURCES]
        combos.append(("bash", STDIN_SOURCES[0], "< /dev/null", "post", STDIN_PIPES[0]))
    seen = set()
    for reader, (sname, src, body), redir, where, (pname, pipe) in combos:
        line = pipe.replace("{C}", _reader_cmd(reader, src, redir, where))
        name = f"stdin:{pname}/{sname}/{reader.replace(' ', '_')}/{redir.replace(' ', '') or 'none'}@{where}"
        if line + body in seen:
            continue
        seen.add(line + body)
        cmd.append(Case(name, _stdin_text(line, body, CMD), tuple(PAYLOADS)[len(cmd) % len(PAYLOADS)]))
        rcpt.append(Case(name, _stdin_text(line, body, "{SEND}"), "receipt"))
        last_wins = "/dev/null" not in redir or "<" not in redir or where == "pre"
        if pname in ("alone", "first", "first-amp") and last_wins:
            rcpt.append(Case(name + "/receipted", _stdin_text(line, body, "{SEND}", True), "receipt"))
    for (rname, route), (sname, src, body) in product(STDIN_ROUTES, STDIN_SOURCES[:4:3]):
        if "{S}" not in route and sname != "heredoc":
            continue   # a route with no source of its own is one case
        if "{S}" in route and body and ("$(" in route or "<(" in route):
            continue   # a heredoc inside a substitution keeps its body inside: the -heredoc routes
        for reader in (("sh",) if "{READER}" in route else ("",)):
            line = route.replace("{READER}", reader).replace("{S}", src)
            name = f"stdin:route/{rname}/{sname}"
            body_ = body if "{S}" in route else ""
            cmd.append(Case(name, _stdin_text(line, body_, CMD), tuple(PAYLOADS)[len(cmd) % len(PAYLOADS)]))
            rcpt.append(Case(name, _stdin_text(line, body_, "{SEND}"), "receipt"))
    cmd.append(Case("stdin:route/xargs-append", "xargs {HEAD} <<< '{ARGS}'", "push"))
    cmd.append(Case("stdin:route/xargs-append-pipe", "echo '{ARGS}' | xargs {HEAD}", "send"))
    return cmd + rcpt


def corpus(random_count=BOUNDED_RANDOM, seed=SEED, both=False):
    cases = list(guard_grid(every=both)) + receipt_grid()
    known = {c.id for c in cases} | {Case("", c.template, p).id for c in grid() for p in PAYLOADS}
    for case in stdin_grid(every=both):   # a stdin case another family already holds runs once
        if case.id not in known:
            known.add(case.id)
            cases.append(case)
    for k, case in enumerate(grid()):
        payloads = tuple(PAYLOADS) if both else (tuple(PAYLOADS)[k % len(PAYLOADS)],)
        cases += [Case(case.family, case.template, p) for p in payloads]
    for case in compositions(random_count, seed):
        payloads = tuple(PAYLOADS) if both else (case.payload,)
        cases += [Case(case.family, case.template, p) for p in payloads]
    return cases


# --- the oracle: real bash, inert sentinel, throwaway directory ----------------------------
# Families also run under dash: a hole that either shell runs is live (ran = either). bash
# stays the one that names a parse error.
DASH_FAMILIES = ("stdin:",)


def shells_for(case, oracle):
    return ("bash", "dash") if case.family.startswith(DASH_FAMILIES) and oracle.dash else ("bash",)


class BashOracle:
    def __init__(self, bash=None):
        self.bash = bash or shutil.which("bash") or "/bin/bash"
        self.dash = shutil.which("dash") or ("/bin/dash" if os.path.exists("/bin/dash") else None)
        self.root = Path(tempfile.mkdtemp(prefix="dh-oracle-"))
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        sentinel = self.bindir / SENTINEL
        # It records its own argv, one word per unit separator: the hole RAN only when the
        # sentinel got exactly the payload's words, so `{HEAD};{ARGS}` (the head alone, then a
        # stray command) or one quoted word holding them all is not a run of the payload.
        # It stands for a BINARY (git, gh, rm): a shell handed it as a script (sh orca_sentinel
        # ARGS finds it on PATH, where sh gh ARGS fails on a binary) records nothing. Run as a
        # program, $0 is the path the shell found.
        sentinel.write_text("#!/bin/sh\ncase $0 in */*) ;; *) exit 0 ;; esac\n"
                            "IFS=$(printf '\\037')\n"
                            "printf '%s\\n' \"$*\" >> \"$ORCA_SENTINEL_MARK\"\n", encoding="utf-8")
        sentinel.chmod(0o755)
        # The guard mode's rm: removes its operands only when they resolve inside the case dir.
        deleter = self.bindir / DELETER
        deleter.write_text(
            "#!/bin/sh\nfor f; do\n  case \"$f\" in -*) continue ;; esac\n"
            "  d=$(cd \"$(dirname -- \"$f\")\" 2>/dev/null && pwd -P) || continue\n"
            "  case \"$d/\" in \"$DCOY_HOME\"/*) /bin/rm -f -- \"$f\" ;; esac\ndone\n",
            encoding="utf-8")
        deleter.chmod(0o755)
        # The receipt mode's egress receipt: records R, exits DCOY_RECEIPT_RC (0 or 1).
        receipt = self.bindir / RECEIPT_SENTINEL
        receipt.write_text("#!/bin/sh\nprintf 'R\\n' >> \"$ORCA_SENTINEL_MARK\"\n"
                           "exit \"${DCOY_RECEIPT_RC:-0}\"\n", encoding="utf-8")
        receipt.chmod(0o755)
        # Harmless helpers only: the templates call bash/sh -c, cat, find, tee and xargs.
        for tool in ("bash", "sh", "cat", "find", "tee", "xargs"):
            real = self.bash if tool == "bash" else shutil.which(tool)
            if real:
                (self.bindir / tool).symlink_to(real)
        # The hook side of every case runs in this empty directory; {ROOT} there is its path.
        self.hook_root = self.root / "hook-cwd"
        self.hook_root.mkdir()
        self.hook_root = str(self.hook_root.resolve())
        self._n = 0
        self._lock = threading.Lock()
        self.version = subprocess.run([self.bash, "-c", "printf %s \"$BASH_VERSION\""],
                                      capture_output=True, text=True, timeout=BASH_TIMEOUT).stdout

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run(self, text, payload="push", shells=("bash",)):
        """(the hole ran, bash reported a parse error) for one safe form of a payload."""
        return self.observe(text, payload, shells)[:2]

    def observe(self, text, payload="push", shells=("bash",)):
        """run(), plus whether the hole was touched at all (the sentinel with any argv). Under
        several shells the hole ran if ANY ran it; the parse error is bash's."""
        if not safe_form_ok(text):
            raise ValueError(f"a safe form may reach only the sentinel: {text!r}")
        seen = [self._observe(text, payload, shell) for shell in shells]
        return any(s[0] for s in seen), seen[0][1], any(s[2] for s in seen)

    def _exec(self, shell, text, cwd, env):
        """bash (no rc files) or dash running text, under CPU, file-size and core limits set by
        the parent sh (preexec_fn is not safe beside the worker threads), with a timeout."""
        exe, opts = (self.bash, "--norc --noprofile ") if shell == "bash" else (self.dash, "")
        limited = ['/bin/sh', '-c', 'ulimit -t 5 2>/dev/null; ulimit -f 2048 2>/dev/null; '
                   'ulimit -c 0 2>/dev/null; exec "$0" ' + opts + '-c "$1"', exe, text]
        proc = subprocess.Popen(limited, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                start_new_session=True)
        try:
            _out, err = proc.communicate(timeout=BASH_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 9)
            _out, err = proc.communicate()
        return err.decode("utf-8", "replace")

    def _observe(self, text, payload, shell):
        if payload_kind(payload) == "receipt":
            return self._observe_receipts(text, shell)
        with self._lock:
            self._n += 1
            work = self.root / f"case-{self._n}"
        work.mkdir()
        home = str(work.resolve())
        decoy = None
        if payload_kind(payload) == "guard":
            decoy = work / _decoy(payload[6:])
            decoy.parent.mkdir(parents=True)
            decoy.write_text("pin\n", encoding="utf-8")
            (decoy.parent / "other.txt").write_text("x\n", encoding="utf-8")
            (work / "notes").mkdir()
            (work / "notes" / "keep.txt").write_text("x\n", encoding="utf-8")
            text = text.replace("{ROOT}", home)
        mark = work / ".sentinel"
        env = {"PATH": str(self.bindir), "HOME": str(work), "TMPDIR": str(work), "LC_ALL": "C",
               "ORCA_SENTINEL_MARK": str(mark), "DCOY_HOME": home}
        err = self._exec(shell, text, work, env)
        # A parse error refuses to run the text: bash exits 2 for a syntax error and 1 for a bad
        # substitution, so the message, not the status, says which runs ended there.
        syntax = bool(re.search(r"syntax error|unexpected EOF|unexpected end of file|"
                                r"bad substitution|here-document .* delimited by end-of-file",
                                err))
        if decoy is not None:
            ran = touched = decoy.is_symlink() or not decoy.is_file() \
                or decoy.read_text(encoding="utf-8", errors="replace") != "pin\n"
        else:
            want = PAYLOADS[payload][1].split()
            lines = mark.read_text(encoding="utf-8").splitlines() if mark.exists() else []
            touched = bool(lines)
            # The payload's words leading its argv: arguments a launcher appends (find -exec
            # {} +, xargs) keep the command what it is.
            ran = any(line.split("\x1f")[:len(want)] == want for line in lines)
        shutil.rmtree(work, ignore_errors=True)
        return ran, syntax, touched

    def _observe_receipts(self, text, shell="bash"):
        """(a send ran without its own fresh successful receipt, parse error, any send ran).
        Run twice: receipts succeeding, where each send must consume one receipt recorded since
        the last send; and receipts failing, where no send may run at all."""
        want, ungated, syntax, touched = SEND_ARGS.split(), False, False, False
        for rc in ("0", "1"):
            with self._lock:
                self._n += 1
                work = self.root / f"case-{self._n}"
            work.mkdir()
            for name, body in (("a.txt", "a\n"), ("b.txt", "b\n"), ("list.txt", "1\n2\n")):
                (work / name).write_text(body, encoding="utf-8")
            mark = work / ".sentinel"
            env = {"PATH": str(self.bindir), "HOME": str(work), "TMPDIR": str(work), "LC_ALL": "C",
                   "ORCA_SENTINEL_MARK": str(mark), "DCOY_RECEIPT_RC": rc}
            err = self._exec(shell, text.replace(LATER, NL), work, env)
            syntax = syntax or bool(re.search(r"syntax error|unexpected EOF|unexpected end of "
                                              r"file|bad substitution", err))
            lines = mark.read_text(encoding="utf-8").splitlines() if mark.exists() else []
            shutil.rmtree(work, ignore_errors=True)
            available = 0
            for line in lines:
                if line == "R":
                    available += rc == "0"
                    continue
                touched = True
                if line.split("\x1f")[:len(want)] == want:
                    available -= 1
                    ungated = ungated or available < 0
        return ungated, syntax, touched


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
        return "downgrade" if decision == "ask" and expect(payload) == "deny" else "agree"
    if decision == "allow":
        return "agree"
    return "fail-closed" if syntax else "false-deny"


def evaluate(cases, oracle, hook=HOOK, jobs=4, bash_cache=None):
    """One result dict per case, in order. bash_cache maps safe text -> (ran, syntax)."""
    cache = {} if bash_cache is None else bash_cache

    def one(case):
        safe, shells = render(case.template, case.payload, True), shells_for(case, oracle)
        if (case.payload, safe, shells) not in cache:
            cache[(case.payload, safe, shells)] = oracle.run(safe, case.payload, shells)
        ran, syntax = cache[(case.payload, safe, shells)]
        decision = hook_decision(render(case.template, case.payload, False, oracle.hook_root),
                                 hook, oracle.hook_root)
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
    return re.findall(r"\{[A-Z0-9]+\}|.", template, re.DOTALL)


# A shrink may not glue a word character onto the payload: `{CMD}i` names another command.
_GLUED = re.compile(r"(\{CMD\}|\{ARGS\})[A-Za-z0-9_./-]|[A-Za-z0-9_./-]\{(CMD|HEAD)\}")


def ddmin(template, keeps):
    """The smallest template (by ddmin) for which keeps(template) still holds."""
    atoms, n = _atoms(template), 2
    holed = re.search(r"\{[A-Z0-9]+\}", template)   # a template with a hole keeps one
    while len(atoms) >= 2:
        chunk = max(1, len(atoms) // n)
        reduced = False
        for start in range(0, len(atoms), chunk):
            trial = atoms[:start] + atoms[start + chunk:]
            text = "".join(trial)
            if trial and (not holed or re.search(r"\{[A-Z0-9]+\}", text)) and keeps(text):
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
        payload = result["payload"]
        safe = render(template, payload, True)
        if payload_kind(payload) == "cmd" and not any(p in template for p in (CMD, HEAD)):
            return False   # the payload must still be in the hole
        if payload_kind(payload) == "receipt" and "{SEND}" not in template:
            return False
        if (HEAD in template and ARGS not in template) or not safe_form_ok(safe) \
                or _GLUED.search(template):
            return False   # never run a real tool name; never glue text onto the payload words
        ran, syntax, touched = oracle.observe(
            safe, payload, shells_for(Case(result.get("family", ""), template, payload), oracle))
        if want == "false-deny" and touched:
            return False   # the hole ran with other words: a shrink that changed the command
        decision = hook_decision(render(template, payload, False, oracle.hook_root), hook,
                                 oracle.hook_root)
        return classify(ran, syntax, decision, payload) == want

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
