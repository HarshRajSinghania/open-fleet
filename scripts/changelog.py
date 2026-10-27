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
import bisect
import html
import re
import subprocess
import sys
import urllib.parse
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
_TAG_ATTR_RE = re.compile(r"""[ \t\n\x0b\f\r]+([a-z_:][a-z0-9_.:-]*)(?:[ \t\n\x0b\f\r]*=[ \t\n\x0b\f\r]*"""
                          r"""([^ \t\n\x0b\f\r"'=<>`]+|'[^']*'|"[^"]*"))?""", re.IGNORECASE)
_TAG_END_RE = re.compile(r"[ \t\n\x0b\f\r]*/?>")
# Raw HTML blocks (CommonMark 0.31 and GFM, "HTML blocks"): inside one, tags are real, and a
# backtick or a backslash is text. A line may open one when, past any block-quote or list-item
# marks, it starts a type 1-5 block (<script, <pre, <style, <textarea, <!--, <?, <!X, <![CDATA[),
# names a type 6 block tag, or holds one complete tag alone (type 7).
_HTML_OPENER_RE = re.compile(r"<(?:script|pre|style|textarea)(?:[\s>]|$)|<!--|<\?|<![a-z]|<!\[CDATA\[",
                             re.IGNORECASE)
_HTML_BLOCK6_RE = re.compile(
    r"</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|"
    r"div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|"
    r"link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|source|summary|table|tbody|td|"
    r"tfoot|th|thead|title|tr|track|ul)(?:[\s/>]|$)", re.IGNORECASE)
_HTML_BLOCK7_RE = re.compile(
    r"(?:<[a-z][a-z0-9-]*(?:[ \t\n\x0b\f\r]+[a-z_:][a-z0-9_.:-]*(?:[ \t\n\x0b\f\r]*=[ \t\n\x0b\f\r]*"
    r"(?:[^ \t\n\x0b\f\r\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*[ \t\n\x0b\f\r]*/?>"
    r"|</[a-z][a-z0-9-]*[ \t\n\x0b\f\r]*>)[ \t]*$", re.IGNORECASE)
_CONTAINER_RE = re.compile(r"[ \t]*(?:>|[-*+](?=[ \t]|$)|\d{1,9}[.)](?=[ \t]|$))")
# A line, ending at a CommonMark line ending only (\n, \r\n or \r): str.splitlines would also
# split at U+2028 and friends, inventing lines a renderer never sees (Codex at dde9cbedf9).
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
_CLOSE_TAG_RE = re.compile(r"</[a-z][a-z0-9-]*[ \t\n\x0b\f\r]*>", re.IGNORECASE)
# A "<" a renderer may read as the start of raw HTML or an autolink: a tag, closing tag, comment,
# declaration, processing instruction, CDATA, URI or e-mail autolink. Renderers disagree on
# where each ends (Pandoc renders <!X <a href=...> as a link; CommonMark 0.31 calls it one
# declaration), so the scanner never guesses: past such a "<", backticks and escapes are text.
_MAY_OPEN_RE = re.compile(r"<[a-z0-9.!#$%&'*+/=?^_`{|}~-]", re.IGNORECASE)
# What makes a complete tag unsafe to skip whole: a backtick or a "<" inside it, or a line end.
_UNCLEAR_RE = re.compile(r"[`<\r\n]")
# A bare URL GFM turns into a link (an extended autolink): its path may hold a backtick, so no
# code span opens there (fuzzed against Pandoc's GFM reader, #673).
_BARE_URL_RE = re.compile(r"://|www\.", re.IGNORECASE)
# A tag as an HTML5 tokenizer reads raw HTML, for _loose_link: a name, then attributes whose
# names are anything but whitespace, "/", ">" and "=" (a quote included), each with an optional
# value, quoted or not. Whitespace is HTML's five characters exactly; Python's \s also matches a
# no-break space, which let a quote swallow the href (Codex at a276405fe8).
_LOOSE_NAME_RE = re.compile(r"<[a-z][^ \t\n\f\r/>]*", re.IGNORECASE)
_LOOSE_ATTR_RE = re.compile(r"""[ \t\n\f\r/]*([^ \t\n\f\r/>][^ \t\n\f\r/>=]*)"""
                            r"""([ \t\n\f\r]*=[ \t\n\f\r]*(?:"[^"]*"|'[^']*'|[^ \t\n\f\r>]*))?""")
# Raw HTML that is no tag (CommonMark 0.31, "Raw HTML"): a comment, a processing instruction, a
# declaration or CDATA. And an autolink (URI or e-mail), which CommonMark reads before raw HTML,
# so raw_html() steps over it rather than reading it as a tag (2026-10-27 security audit, W6-14).
# A scheme a browser follows to run or read something rather than to open a page (PR #718
# re-attack, W6-14). Reading link constructs missed one (a reference definition inside a list
# item, review round 3), so the scheme is refused as a token, wherever it stands: a word that
# runs into it (`metadata:`) is no scheme, anything else is.
_DANGEROUS_SCHEME_RE = re.compile(r"(?<![a-z0-9+.\-])(?:javascript|vbscript|data|file) *:")
_RAW_OTHER_RE = re.compile(r"<!--|<\?|<![A-Za-z]|<!\[CDATA\[")
# A line that may be a GFM table's delimiter row (`--- | ---`, `|:-:|`), past quote and list
# marks. GFM splits a row into cells, before it reads a code span, only inside a table, and a
# table needs one: without such a line a "|" is plain text and a code span holding one is code.
_DELIMITER_ROW_RE = re.compile(r"(?m)^[ \t>]*(?:[-*+][ \t]+|\d{1,9}[.)][ \t]+)?"
                               r"(?=[^\n]*\|)(?=[^\n]*-)[|:\- \t]+$")
_AUTOLINK_RE = re.compile(r"<[A-Za-z][A-Za-z0-9.+-]{1,31}:[^\x00-\x20<>]*>"
                          r"|<[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}"
                          r"[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*>")


def _opens_html(line):
    """Whether `line`, past any block-quote and list-item marks, may open a raw HTML block."""
    rest = line.rstrip("\r\n")
    while mark := _CONTAINER_RE.match(rest):
        rest = rest[mark.end():]
    rest = rest.lstrip(" \t")
    return bool(_HTML_OPENER_RE.match(rest) or _HTML_BLOCK6_RE.match(rest) or _HTML_BLOCK7_RE.match(rest))


# One block quote's mark at a line's start: a renderer strips a quote's marks before reading what
# it holds, so a tag split across quoted lines is whole once they go (Codex at b12df9e457). Only
# as many as the quote's depth go: a ">" after them is the content's own, perhaps a tag's end
# (Codex at 52ef451db4), so each depth is read as its own view.
_QUOTE_MARK_RE = re.compile(r"[ \t]*>[ \t]?")


def _quote_views(text):
    """`text` with up to 1, 2, ... leading block-quote marks removed from each line, one view per
    depth, to the deepest any line has."""
    lines = [m.group() for m in _LINE_RE.finditer(text)]

    def depth(line):
        n = 0
        while mark := _QUOTE_MARK_RE.match(line):  # every mark consumes a ">": no cap (Codex at b0a54260f9)
            line, n = line[mark.end():], n + 1
        return n

    def strip(line, k):
        for _ in range(k):
            if not (mark := _QUOTE_MARK_RE.match(line)):
                break
            line = line[mark.end():]
        return line
    return ["".join(strip(line, k) for line in lines) for k in range(1, max(map(depth, lines), default=0) + 1)]


def _loose_link(text, i, open_ok, any_tag=False):
    """The tag at text[i] when a browser reading it as raw HTML finds an href or src attribute
    with a value in it, else None; with `open_ok` (inside a raw HTML block) closed or not. Past a point where renderers may disagree, text may reach the
    page as raw HTML, so link tags there are read this loosely."""
    if not (name := _LOOSE_NAME_RE.match(text, i)):
        return None
    pos, link = name.end(), any_tag  # any_tag: every tag counts, a link attribute or not
    while attr := _LOOSE_ATTR_RE.match(text, pos):
        link = link or (attr.group(1).lower() in ("href", "src") and attr.group(2) is not None)
        pos = attr.end()
    end = re.compile(r"[ \t\n\f\r/]*>").match(text, pos)
    # In a raw HTML block an unterminated tag counts too: whatever the renderer writes next (a
    # </li>) can close it (Codex at 075baf07c5). In a paragraph it is text a renderer escapes.
    return text[i:end.end() if end else pos] if link and (end or open_ok) else None


def _tag(text, i):
    """(end, links) for a complete open or closing tag at text[i], read quote-aware and across
    lines; None when there is none."""
    if close := _CLOSE_TAG_RE.match(text, i):
        return close.end(), False
    if not (name := _TAG_NAME_RE.match(text, i)):
        return None
    pos, link = name.end(), False
    while attr := _TAG_ATTR_RE.match(text, pos):
        link = link or (attr.group(1).lower() in ("href", "src") and attr.group(2) is not None)
        pos = attr.end()
    end = _TAG_END_RE.match(text, pos)
    return (end.end(), link) if end else None


UNRELEASED = "## [Unreleased]"
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def html_link(text):
    """The first HTML tag in Markdown `text` that carries an href or src attribute, or None.

    Read so that nothing a renderer shows as a link is missed (#673), in one pass over the text
    and one over each view of it with a quote's depth of block-quote marks removed from each line,
    as a renderer reads a quote. A tag is
    skipped only inside a backslash escape or a code span that closes on the line it opens, and
    only before any point where renderers may disagree about what follows: a line that may open
    raw HTML (past list or quote marks), a "<" that may begin raw HTML or an autolink and is not
    a plain one-line tag, a "[" that may begin a link, a bare URL, a "|" that may edge a table
    cell, a "$" that may open Pandoc's math, or a backtick run left open on its line. From there on, backticks and
    escapes are text, and a link tag is read as loosely as a browser reads raw HTML. Fragments allow no blank line and run-index cells no newline, so what this
    reads as text more strictly than a renderer would is never needed. scripts/run_index.py keeps
    an identical copy: it is loaded alone, so it cannot import this one (tests/test_changelog.py
    holds them equal).
    """
    return next((found for view in (text, *_quote_views(text)) if (found := _first_link(view))), None)


def dangerous_scheme(text):
    """The first javascript:, vbscript:, data: or file: scheme in `text`, wherever it stands and
    whatever Markdown is around it (a list item, a blockquote, a nested list, `<...>`), or None.

    Read as a renderer and then a browser read a link destination, and more: the text as written,
    then decoded up to three times over, each time with every backslash dropped (CommonMark turns
    `javascript\\:` into `javascript:` in the href; found sweeping PR #718 review round 3),
    percent escapes and then HTML entities decoded (a browser decodes no percent escape in a
    scheme, so that only refuses more). Each view is read with case ignored and ASCII control
    characters (a tab or a line break inside the scheme) dropped, and again with them as spaces,
    so neither joining nor splitting hides one. Over-decoding costs a rewording; a missed scheme
    is a script in a published page. Identical in scripts/changelog.py and scripts/run_index.py."""
    views = [text]
    for _ in range(3):
        views.append(html.unescape(urllib.parse.unquote(views[-1].replace("\\", ""))))
    for view in views:
        lowered = view.lower()
        for folded in (re.sub(r"[\x00-\x1f\x7f]", "", lowered),
                       re.sub(r"[\x00-\x1f\x7f]", " ", lowered)):
            if match := _DANGEROUS_SCHEME_RE.search(folded):
                return match.group()
    return None


def raw_html(text):
    """The first raw HTML in Markdown `text`, or None: any tag, open or closing, with or without
    an href or src, a comment, a processing instruction, a declaration or CDATA, read the way
    html_link reads a link tag (skipped only inside an escape or a one-line code span before any
    point where renderers may disagree). Both writers emit a cell or a fragment verbatim into a
    published page, so a tag with no link in it (`<script>`) reaches it too (2026-10-27 security
    audit, W6-14). Identical in scripts/changelog.py and scripts/run_index.py."""
    return next((found for view in (text, *_quote_views(text))
                 if (found := _first_link(view, any_tag=True))), None)


def _first_link(text, any_tag=False):
    """html_link's one pass over one view of `text` (raw_html's, with `any_tag`)."""
    lines = [m.span() for m in _LINE_RE.finditer(text)]
    starts = [start for start, _end in lines]
    # Backticks and escapes are text from the first line that may open raw HTML, from the first
    # "<" that may begin raw HTML or an autolink and is not a plain one-line tag, from the first
    # "[" (a link or image, whose text, destination or title may hold a backtick), from the first
    # bare URL (GFM links it), the first "|" (GFM splits a table row into cells before reading a
    # span), the first "$" (Pandoc's GFM math, $x$ or $`x`$), and from the first backtick run
    # left open on its line: past any of
    # these, where a span or construct ends depends on the renderer, and a link tag is read as a
    # browser reads raw HTML (_loose_link).
    literal = html = next((start for start, end in lines if _opens_html(text[start:end])), len(text))
    # html_link reads every "|" as a table cell's edge; raw_html only where a table can exist.
    tables = not any_tag or bool(_DELIMITER_ROW_RE.search(text))
    i = 0
    while i < len(text):
        inline = i < literal
        if inline and text[i] == "\\":
            i += 2
        elif inline and text[i] == "[":
            literal, i = i, i + 1  # a link's text, destination or title may hold a backtick (Codex at d16ff6e5cc)
        elif inline and (_BARE_URL_RE.match(text, i) or text[i] == "$" or text[i] == "|" and tables):
            literal, i = i, i + 1  # a bare URL, a table cell's edge, or Pandoc's $math$ (Codex at 737bef7213, b897354b7b)
        elif inline and text[i] == "`":
            line_end = lines[bisect.bisect_right(starts, i) - 1][1]
            run = len(text[i:line_end]) - len(text[i:line_end].lstrip("`"))
            close = re.compile(f"(?<!`){'`' * run}(?!`)").search(text, i + run, line_end)
            if close and not (tables and "|" in text[i + run:close.start()]):
                i = close.end()
            else:  # left open, or holding a "|" that may split it into table cells (Codex at 0527c08900)
                literal, i = i, i + run
        elif text[i] == "<":
            if any_tag and (auto := _AUTOLINK_RE.match(text, i)):
                literal, i = min(literal, i), auto.end()  # a link, not raw HTML; past it, read loosely
                continue
            tag = _tag(text, i)
            if tag and (tag[1] or any_tag):
                return text[i:tag[0]]
            if any_tag and (other := _RAW_OTHER_RE.match(text, i)):
                return other.group()
            if not inline and (loose := _loose_link(text, i, open_ok=i >= html, any_tag=any_tag)):
                return loose
            if inline and tag and not _UNCLEAR_RE.search(text, i + 1, tag[0]):
                i = tag[0]  # a whole one-line tag holding no backtick and no "<": skipping it hides nothing
            elif inline and _MAY_OPEN_RE.match(text, i):
                literal = i  # read this same "<" again as raw HTML (Codex at 5f1eb56a73), then on
            else:
                i += 1
        else:
            i += 1
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
    elif raw := raw_html(text):
        errors.append(f"{where}: raw HTML ({raw[:40]!r}) would reach CHANGELOG.md verbatim; put "
                      "it in a code span or escape the '<'")
    if bad := dangerous_scheme(text):
        errors.append(f"{where}: {bad!r}: a javascript:, vbscript:, data: or file: scheme is "
                      "refused anywhere in a fragment, which CHANGELOG.md publishes")
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
