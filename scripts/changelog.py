#!/usr/bin/env python3
"""CHANGELOG entries as one fragment file per change, folded in at the release cut.

Every PR used to add its entry at the top of CHANGELOG.md's `## [Unreleased]`, so any two open
PRs edited the same lines and, with strict up-to-date branches, every merge put every other PR
into conflict (six in a row conflicted on bookkeeping files alone). An entry is now
`changelog.d/<slug>.md`, a file only its own PR touches. The release cut (docs/ops.md, Release
cut) folds every fragment into the new dated section and deletes it, so CHANGELOG.md changes
once per release instead of once per PR.

  python3 scripts/changelog.py check                  every fragment is well formed
  python3 scripts/changelog.py check --base REF       ... and CHANGELOG.md's [Unreleased] holds no
                                                      more entries than at REF (CI, on each PR)
  python3 scripts/changelog.py check --released       ... and nothing is left to fold (a cut)
  python3 scripts/changelog.py preview                the entries the next cut folds in, in order
  python3 scripts/changelog.py assemble VERSION DATE  fold them in as `## [VERSION] - DATE`

A fragment is the entry exactly as the release section will read it: one or more list items,
each opening `- ` at column 0, continuation lines indented, no heading and no blank line (either
would split the release list). A relative link is written from changelog.d/ (`../docs/x.md`) and
the cut makes it root-relative. Its name is a lowercase slug, `changelog.d/<slug>.md`;
changelog.d/README.md says so and is never folded. The cut lists fragments newest first, by the
commit that landed each on the first-parent line (a fragment not yet committed counts as newest),
then the [Unreleased] entries written before fragments existed, which are older than all of them.

Exit: 0 every check holds, 1 a check failed, 2 the input could not be read.
"""
import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRAGMENTS_DIR = ROOT / "changelog.d"
CHANGELOG = ROOT / "CHANGELOG.md"
README_NAME = "README.md"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,78}\.md$")
# A relative Markdown link in a fragment is written from changelog.d/ (`../docs/x.md`), so the
# repository's dead-link test checks it where it sits; the cut drops the leading `../` so the same
# link resolves from CHANGELOG.md at the root.
LINK_RE = re.compile(r"\]\((?!https?:|mailto:|#)([^)\s]+)\)")
# An HTML href/src is not rewritten when the cut moves the entry to the root CHANGELOG.md, so a
# relative one would break there (PR #670): fragments carry Markdown links only. Raw HTML is read
# as CommonMark reads it (spec 0.31, "Raw HTML"): a COMPLETE open tag whose attributes are
# whitespace-separated, quote-aware (a ">" inside a value does not end the tag), and may span
# lines. Only an attribute named exactly href or src, with a value, is a link (Codex at 54fe725bee:
# `data-href`, and `x<a` with `href=value` lines later and no tag ever closed, were refused).
_TAG_NAME_RE = re.compile(r"<[a-z][a-z0-9-]*", re.IGNORECASE)
_TAG_ATTR_RE = re.compile(r"""\s+([a-z_:][a-z0-9_.:-]*)(?:\s*=\s*([^\s"'=<>`]+|'[^']*'|"[^"]*"))?""",
                          re.IGNORECASE)
_TAG_END_RE = re.compile(r"\s*/?>")
# Where a Markdown block may end: a code span never crosses one (CommonMark: inlines are parsed
# within a block). A blank line, or a line whose first mark, at any indentation (a list item's
# blocks sit deeper), can open or close a block: a list item, a setext underline or thematic
# break, a heading, a quote, a table row, an HTML block or a fence. It over-approximates on
# purpose (Codex at 8585b35789 and 3c01b90b5e): a span cut short can only reveal a tag, never
# hide one.
_BLOCK_END_RE = re.compile(r"\n[ \t]*(?:\n|$)|\n[ \t]*(?:[-*+_=#>|<]|\d{1,9}[.)]|```|~~~)", re.MULTILINE)
# Raw HTML blocks (CommonMark 0.31, "HTML blocks"), where tags are real and backticks are text.
# Types 1-5 open on their own marks and end at their own end mark, past blank lines; types 6 and
# 7 end at a blank line. Types 1-6 may interrupt a paragraph; type 7, any other complete tag
# alone on its line, may not. Recognised at any indentation, since a list item's blocks sit
# deeper: missing one could hide a tag, finding a spurious one only reveals more.
_HTML_BLOCK_ENDING = (
    (re.compile(r"<(?:script|pre|style|textarea)(?:[\s>]|$)", re.IGNORECASE),
     re.compile(r"</(?:script|pre|style|textarea)>", re.IGNORECASE)),
    (re.compile(r"<!--"), re.compile(r"-->")),
    (re.compile(r"<\?"), re.compile(r"\?>")),
    (re.compile(r"<![a-z]", re.IGNORECASE), re.compile(r">")),
    (re.compile(r"<!\[CDATA\["), re.compile(r"\]\]>")),
)
_HTML_BLOCK6_RE = re.compile(
    r"</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|"
    r"div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|"
    r"link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|"
    r"th|thead|title|tr|track|ul)(?:[\s/>]|$)", re.IGNORECASE)
_HTML_BLOCK7_RE = re.compile(
    r"(?:<[a-z][a-z0-9-]*(?:\s+[a-z_:][a-z0-9_.:-]*(?:\s*=\s*(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*\s*/?>"
    r"|</[a-z][a-z0-9-]*\s*>)[ \t]*$", re.IGNORECASE)
# A fenced code block's opening line (at any indentation): literal to its closing fence, or to
# where the list item holding it ends (Greptile at 8585b35789).
_FENCE_RE = re.compile(r"([ \t]*)(`{3,}|~{3,})([^\n]*)")
# A line, ending at a CommonMark line ending only (\n, \r\n or \r): str.splitlines would also split
# at U+2028 and friends, inventing lines, and fences, that a renderer never sees (Codex at dde9cbedf9).
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
# A line that ends a paragraph rather than continuing it: a setext underline, a thematic break, an
# ATX heading or a table row. After one, a lone tag opens a type 7 HTML block (Codex at
# dde9cbedf9). Counting a line here when CommonMark would not only reveals more.
_PARA_BREAK_RE = re.compile(r"(?:=+|-+|(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|#{1,6}(?:[ \t].*)?|\|.*)[ \t]*")


def _regions(text):
    """`text` split into line runs, each ("html" | "fence" | "text", start, end). An HTML block's
    tags are real and its backticks text; a fenced block is literal; the rest is inline Markdown.
    A line inside an HTML block opens no fence (Greptile at 1fad2a56e8), so HTML is checked first.
    A fence ends at its closing fence or at the first later line indented less than it, where the
    list item holding it ends, so no tag after that item is hidden."""
    out, state, para = [], None, False
    for match in _LINE_RE.finditer(text):
        line, start, pos = match.group(), match.start(), match.end()
        rest = line.lstrip(" \t").rstrip("\r\n")
        indent = len(line[:len(line) - len(line.lstrip(" \t"))].expandtabs(4))
        if state and state[0] == "fence":
            if rest and indent < state[1]:
                state = None  # the container ended, and the fence with it: read this line afresh
            else:
                out.append(("fence", start, pos))
                state = None if state[2].fullmatch(rest) else state
                continue
        if state and state[0] == "html":
            if state[1] is None and not rest:  # types 6 and 7 end at a blank line
                state, para = None, False
                out.append(("text", start, pos))
            else:
                out.append(("html", start, pos))
                state = None if state[1] is not None and state[1].search(rest) else state
            continue
        opened = next(((m, ends) for opens, ends in _HTML_BLOCK_ENDING if (m := opens.match(rest))), None)
        if opened or _HTML_BLOCK6_RE.match(rest) or (not para and _HTML_BLOCK7_RE.match(rest)):
            ends = opened[1] if opened else None
            out.append(("html", start, pos))
            state, para = (None if ends is not None and ends.search(rest, opened[0].end()) else ("html", ends)), False
            continue
        fence = _FENCE_RE.match(line)
        if fence and not (fence.group(2)[0] == "`" and "`" in fence.group(3)):
            mark = fence.group(2)
            state = ("fence", indent, re.compile(rf"{re.escape(mark[0])}{{{len(mark)},}}[ \t]*"))
            out.append(("fence", start, pos))
            para = False
            continue
        out.append(("text", start, pos))
        para = bool(rest) and not _PARA_BREAK_RE.fullmatch(rest)
    merged = []
    for kind, start, end in out:  # adjacent lines of a kind form one run: a span may cross a soft break
        if merged and merged[-1][0] == kind:
            merged[-1] = (kind, merged[-1][1], end)
        else:
            merged.append((kind, start, end))
    return merged


def _scan(text, i, end, inline):
    """The first link tag starting in text[i:end]. Inline Markdown (`inline`) honours backslash
    escapes and code spans; raw HTML has neither."""
    while i < end:
        if inline and text[i] == "\\":
            i += 2
        elif inline and text[i] == "`":
            run = len(text) - i - len(text[i:].lstrip("`"))
            block = _BLOCK_END_RE.search(text, i + run, end)
            close = re.compile(f"(?<!`){'`' * run}(?!`)").search(text, i + run, block.start() if block else end)
            i = close.end() if close else i + run
        elif text[i] == "<" and (name := _TAG_NAME_RE.match(text, i)):
            pos, link = name.end(), False
            while attr := _TAG_ATTR_RE.match(text, pos):
                link = link or (attr.group(1).lower() in ("href", "src") and attr.group(2) is not None)
                pos = attr.end()
            tag_end = _TAG_END_RE.match(text, pos)
            if tag_end and link:
                return text[i:tag_end.end()]
            i = tag_end.end() if tag_end else i + 1
        else:
            i += 1
    return None
UNRELEASED = "## [Unreleased]"
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def html_link(text):
    """The first HTML tag in Markdown `text` that carries an href or src attribute, or None.

    Read as a renderer reads it: a raw HTML block's tags are real and its backticks text; a fenced
    code block is literal; elsewhere a backslash escape is text and a code span (a run of N
    backticks closed by the next run of exactly N in the same block) renders literally, so a tag
    inside one is no link, and an unclosed run is plain backticks. scripts/run_index.py keeps an
    identical copy: it is loaded alone, so it cannot import this one (tests/test_changelog.py holds
    them equal).
    """
    for kind, start, end in _regions(text):
        if kind != "fence" and (found := _scan(text, start, end, inline=kind == "text")):
            return found
    return None


def fragment_paths(directory=FRAGMENTS_DIR):
    """Every fragment file, sorted by name: changelog.d/* except the README."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.name != README_NAME)


def fragment_errors(path):
    """Why one fragment would not fold cleanly into a release list ([] when it would)."""
    path = Path(path)
    where = f"changelog.d/{path.name}"
    errors = []
    if not NAME_RE.match(path.name):
        errors.append(f"{where}: name it <slug>.md — lowercase letters, digits, '.', '_' or '-'")
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as err:
        return errors + [f"{where}: not readable as UTF-8 ({err})"]
    if "\r" in text:
        errors.append(f"{where}: carriage return found; use LF line endings")
    if not text.strip():
        return errors + [f"{where}: empty — a fragment holds the entry text"]
    if not text.endswith("\n"):
        errors.append(f"{where}: does not end with a newline")
    if html_link(text):  # the whole fragment: a tag may span lines (PR #670 review)
        errors.append(f"{where}: write each link as a Markdown link ([text](../path)); an HTML "
                      "href or src is not rewritten for CHANGELOG.md")
    lines = text.rstrip("\n").split("\n")
    if not lines[0].startswith("- "):
        errors.append(f"{where}:1: an entry opens with '- ' at column 0")
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            errors.append(f"{where}:{n}: blank line — it would split the release list in two")
        elif line.startswith("#"):
            errors.append(f"{where}:{n}: a heading would split the release section")
        elif not (line.startswith("- ") or line.startswith("  ")):
            errors.append(f"{where}:{n}: start the line with '- ' (a new entry) "
                          "or two spaces (a continuation)")
        for target in LINK_RE.findall(line):
            if not target.startswith("../") or target.startswith("../../"):
                errors.append(f"{where}:{n}: link ({target}) must be written from changelog.d/, "
                              "as ../<path from the repo root>; the cut rewrites it for "
                              "CHANGELOG.md")
    return errors


def as_released(text):
    """A fragment's text as CHANGELOG.md reads it: its `../` links made root-relative."""
    return re.sub(r"\]\(\.\./(?!\.\./)", "](", text)


def check_fragments(directory=FRAGMENTS_DIR):
    """Every shape error across changelog.d/ ([] when the next cut can fold them all)."""
    directory = Path(directory)
    errors = []
    if not (directory / README_NAME).is_file():
        errors.append(f"changelog.d/{README_NAME} is missing — it says how to write a fragment, "
                      "and the release cut stages the directory it keeps alive")
    for path in fragment_paths(directory):
        errors += fragment_errors(path)
    return errors


def split_unreleased(text):
    """(before, legacy entries text, rest): the [Unreleased] section's body cut out of CHANGELOG.

    Raises ValueError unless the heading occurs exactly once: a cut that cannot tell which
    section it is folding into must not guess.
    """
    if text.count(UNRELEASED + "\n") != 1 or text.count(UNRELEASED) != 1:
        raise ValueError(f"CHANGELOG.md must hold exactly one '{UNRELEASED}' heading")
    start = text.index(UNRELEASED + "\n")
    body_start = start + len(UNRELEASED) + 1
    nxt = re.search(r"(?m)^## ", text[body_start:])
    body_end = body_start + nxt.start() if nxt else len(text)
    return text[:start], text[body_start:body_end].strip("\n"), text[body_end:]


def unreleased_entries(text):
    """The top-level `- ` entries written straight into [Unreleased], first line of each."""
    _, body, _ = split_unreleased(text)
    return [line for line in body.split("\n") if line.startswith("- ")]


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def check_base(base, root=ROOT):
    """Errors when CHANGELOG.md's [Unreleased] gained an entry since `base` (a PR's base).

    A count, not a diff: fixing a typo in an old entry passes, and the release cut (which
    empties the section) passes. Raises ValueError when `base` has no CHANGELOG.md to compare.
    """
    shown = _git(root, "show", f"{base}:CHANGELOG.md")
    if shown.returncode != 0:
        raise ValueError(f"cannot read CHANGELOG.md at {base!r}: {shown.stderr.strip()}")
    before = unreleased_entries(shown.stdout)
    after = unreleased_entries((Path(root) / "CHANGELOG.md").read_text(encoding="utf-8"))
    if len(after) <= len(before):
        return []
    added = [e for e in after if e not in before] or after[:len(after) - len(before)]
    shown_new = "; ".join(e[:90] for e in added[:3])
    return [f"CHANGELOG.md's [Unreleased] grew from {len(before)} to {len(after)} entries "
            f"({shown_new}). Move the entry text into changelog.d/<slug>.md instead: every PR "
            "editing the top of [Unreleased] conflicts with every other one, and the release "
            "cut folds the fragments in (changelog.d/README.md)."]


def check_released(root=ROOT):
    """Errors unless the cut folded everything: no fragment left, no entry under [Unreleased]."""
    root = Path(root)
    errors = []
    left = fragment_paths(root / "changelog.d")
    if left:
        errors.append(f"{len(left)} fragment(s) not folded into the release: "
                      + ", ".join(p.name for p in left[:5]))
    entries = unreleased_entries((root / "CHANGELOG.md").read_text(encoding="utf-8"))
    if entries:
        errors.append(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} still under "
                      f"{UNRELEASED} after the cut")
    return errors


def landed(path, root=ROOT):
    """The commit time that brought `path` onto the first-parent line, else any commit adding
    it, else None (not committed yet)."""
    rel = Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    for extra in (["--first-parent"], []):
        r = _git(root, "log", *extra, "--diff-filter=A", "--format=%ct", "--", rel)
        stamps = [int(s) for s in r.stdout.split() if s.isdigit()] if r.returncode == 0 else []
        if stamps:
            return stamps[0]
    return None


def ordered(paths, root=ROOT):
    """Newest first: uncommitted fragments, then by landing time, ties by name."""
    keyed = []
    for p in paths:
        t = landed(p, root)
        keyed.append((0 if t is None else 1, -(t or 0), Path(p).name, p))
    return [k[-1] for k in sorted(keyed)]


def release_body(root=ROOT):
    """The text the next cut writes under its dated heading."""
    root = Path(root)
    parts = [as_released(p.read_text(encoding="utf-8").rstrip("\n"))
             for p in ordered(fragment_paths(root / "changelog.d"), root)]
    _, legacy, _ = split_unreleased((root / "CHANGELOG.md").read_text(encoding="utf-8"))
    if legacy:
        parts.append(legacy)
    return "\n".join(parts)


def assemble(version, day, root=ROOT):
    """Fold every fragment and legacy [Unreleased] entry into `## [version] - day`, then delete
    the fragments. Returns (fragments folded, legacy entries folded). Raises ValueError before
    writing anything when the version, date or any fragment is wrong."""
    root = Path(root)
    if not VERSION_RE.match(version):
        raise ValueError(f"version {version!r} is not MAJOR.MINOR.PATCH")
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except ValueError:
        raise ValueError(f"date {day!r} is not YYYY-MM-DD") from None
    errors = check_fragments(root / "changelog.d")
    if errors:
        raise ValueError("fragments that cannot fold: " + "; ".join(errors))
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    if re.search(rf"(?m)^## \[{re.escape(version)}\]", text):
        raise ValueError(f"CHANGELOG.md already has a '## [{version}]' section")
    before, legacy, rest = split_unreleased(text)
    fragments = fragment_paths(root / "changelog.d")
    body = release_body(root)
    section = f"## [{version}] - {day}\n\n" + (body + "\n\n" if body else "")
    path.write_text(before + UNRELEASED + "\n\n" + section + rest, encoding="utf-8")
    for p in fragments:
        p.unlink()
    return len(fragments), len([ln for ln in legacy.split("\n") if ln.startswith("- ")])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="changelog.py",
                                     description="CHANGELOG fragments: check, preview, assemble.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="fragments are well formed (and more, with flags)")
    c.add_argument("--base", help="fail if [Unreleased] gained an entry since this ref")
    c.add_argument("--released", action="store_true",
                   help="fail unless the cut folded every fragment and entry")
    sub.add_parser("preview", help="print what the next cut folds in")
    a = sub.add_parser("assemble", help="fold the fragments into a dated section (release cut)")
    a.add_argument("version")
    a.add_argument("date")
    args = parser.parse_args(argv)
    # Every call names ROOT at call time (not a def-time default), so a test can point the
    # whole CLI at a fixture repository in-process.
    root, fragments = ROOT, ROOT / "changelog.d"
    try:
        if args.cmd == "preview":
            body = release_body(root)
            print(body if body else "(nothing to release)")
            return 0
        if args.cmd == "assemble":
            folded, legacy = assemble(args.version, args.date, root)
            print(f"CHANGELOG.md: [{args.version}] - {args.date} folds {folded} fragment(s) "
                  f"and {legacy} earlier [Unreleased] entr{'y' if legacy == 1 else 'ies'}")
            if not folded and not legacy:
                print("changelog.py: warning: the release section is empty", file=sys.stderr)
            return 0
        errors = check_fragments(fragments)
        if args.base:
            errors += check_base(args.base, root)
        if args.released:
            errors += check_released(root)
    except (OSError, ValueError) as err:
        print(f"changelog.py: {err}", file=sys.stderr)
        return 2
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        return 1
    pending = len(fragment_paths(fragments))
    print(f"changelog: {pending} fragment(s) well formed"
          + ("; nothing left to fold" if args.released else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
