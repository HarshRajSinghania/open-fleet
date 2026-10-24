#!/usr/bin/env python3
"""The run-archive index as one row file per run, rendered into docs/runs/README.md at the cut.

docs/runs/README.md's table took one hand-written row per run, and its "N reports read yes"
summary was retyped with each one, so two PRs that each filed a run edited the same lines and
conflicted (and the hand-kept counts drifted: the "no" breakdown named three pin-it rows when the
table held ten). A run's row is now docs/runs/index/<run>.json, which only the PR filing that run
touches. This script renders the table and the yes-summary from those files into the generated
block of docs/runs/README.md. The release cut runs it (docs/ops.md, Release cut), so between
releases the block is a dated snapshot that says so, and a run filed since then is listed by its
row file until the next cut.

  python3 scripts/run_index.py check             every row file well formed, one per dated report,
                                                 and the README block consistent with itself
  python3 scripts/run_index.py check --current   ... and the README block is today's rendering
  python3 scripts/run_index.py print             the rendering, to read the index between cuts
  python3 scripts/run_index.py write --as-of DATE    rewrite the README block (the release cut)

Row file docs/runs/index/<key>.json, where <key> is the report's file stem or directory name:
  {"date": "2026-10-24", "report": "2026-10-24-<mission>-<what>.md" (or "<dir>/"),
   "mission": "[<mission>](<report>)", "target": "...", "ran_as": "self-run",
   "binds": "yes — ..." | "no — ...", "outcome": "...",
   "summary": "<the yes-list line>"   (a "yes" row needs one; a "no" row has none),
   "order": 2                          (optional: ties within a date, ascending)}
Cells are the Markdown the table shows, relative to docs/runs/; no cell holds a `|` or a newline.

Exit: 0 every check holds, 1 a check failed, 2 the input could not be read.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CELLS = ("mission", "target", "ran_as", "binds", "outcome")
REQUIRED = ("date", "report") + CELLS
OPTIONAL = ("summary", "order")
_LINK_RE = re.compile(r"\]\((?!https?:|mailto:|#)([^)\s]+)\)")  # relative Markdown links
# Raw HTML read as CommonMark reads it: a COMPLETE open tag, quote-aware, carrying an attribute
# named exactly href or src (Codex at 54fe725bee: `data-href` and an unclosed `x<a` were refused).
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


def _regions(text):
    """`text` split into line runs, each ("html" | "fence" | "text", start, end). An HTML block's
    tags are real and its backticks text; a fenced block is literal; the rest is inline Markdown.
    A line inside an HTML block opens no fence (Greptile at 1fad2a56e8), so HTML is checked first.
    A fence ends at its closing fence or at the first later line indented less than it, where the
    list item holding it ends, so no tag after that item is hidden."""
    out, pos, state, para = [], 0, None, False
    for line in text.splitlines(keepends=True):
        start, pos = pos, pos + len(line)
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
        para = bool(rest)
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

BEGIN = "<!-- BEGIN GENERATED: run-index — scripts/run_index.py -->"
END = "<!-- END GENERATED: run-index -->"
BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
STAMP_RE = re.compile(r"as of (\d{4}-\d{2}-\d{2})\b")
HEADER = ("| Date       | Mission     | Target                        | Ran as       | Binds? | Outcome |\n"
          "|------------|-------------|-------------------------------|--------------|--------|---------|")


def html_link(text):
    """The first HTML tag in Markdown `text` that carries an href or src attribute, or None: in a
    raw HTML block, or in inline Markdown outside a code span and a backslash escape; a fenced
    block is literal. An identical copy of scripts/changelog.py's html_link (this script is loaded
    alone; tests/test_changelog.py holds the two equal)."""
    for kind, start, end in _regions(text):
        if kind != "fence" and (found := _scan(text, start, end, inline=kind == "text")):
            return found
    return None


def runs_dir(root=ROOT):
    return Path(root) / "docs" / "runs"


def dated_reports(root=ROOT):
    """Every dated run report: a top-level docs/runs/2*.md, or a docs/runs/2*/ with a README.

    The same set tests/test_docs_navigation.py holds the index to (#35), named the way a row
    links it: `<file>.md` or `<dir>/`.
    """
    d = runs_dir(root)
    files = [f.name for f in sorted(d.glob("2*.md")) if f.is_file()]
    dirs = [p.name + "/" for p in sorted(d.glob("2*")) if p.is_dir() and (p / "README.md").is_file()]
    return files + dirs


def row_key(report):
    return report[:-1] if report.endswith("/") else report[:-3] if report.endswith(".md") else report


def row_errors(name, data, root=ROOT):
    """Why one row file cannot render as an honest table row ([] when it can)."""
    where = f"docs/runs/index/{name}"
    if not isinstance(data, dict):
        return [f"{where}: a row file is one JSON object"]
    errors = []
    missing = [k for k in REQUIRED if not isinstance(data.get(k), str) or not data[k].strip()]
    if missing:
        errors.append(f"{where}: missing or empty {missing}")
    unknown = sorted(set(data) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        errors.append(f"{where}: unknown keys {unknown}")
    if missing:
        return errors
    try:
        if date.fromisoformat(data["date"]).isoformat() != data["date"]:
            raise ValueError
    except ValueError:
        errors.append(f"{where}: date {data['date']!r} is not YYYY-MM-DD")
    report = data["report"]
    if name != row_key(report) + ".json":
        errors.append(f"{where}: name the file after its report, {row_key(report)}.json")
    target = runs_dir(root) / report
    if "/" in report.rstrip("/") or not (target / "README.md" if report.endswith("/")
                                         else target).is_file():
        errors.append(f"{where}: report {report!r} is not a run report under docs/runs/")
    if f"({report})" not in data["mission"]:
        errors.append(f"{where}: the mission cell does not link ({report})")
    for cell in CELLS + ("summary",):
        value = data.get(cell)
        if isinstance(value, str) and ("|" in value or "\n" in value):
            errors.append(f"{where}: {cell} holds a '|' or a newline, which breaks the table")
    for cell in CELLS + ("summary",):  # the README is not re-rendered until the cut (PR #670)
        value = data.get(cell)
        if isinstance(value, str) and html_link(value):
            errors.append(f"{where}: {cell} holds an HTML link; write it as a Markdown link "
                          "[text](path), which this check resolves")
        for href in _LINK_RE.findall(value) if isinstance(value, str) else ():
            path = href.split("#", 1)[0]
            if path and not (runs_dir(root) / path).exists():
                errors.append(f"{where}: {cell} link ({href}) does not resolve from docs/runs/")
    binds = data["binds"]
    if not (binds == "yes" or binds.startswith("yes ") or binds.startswith("no ")
            or binds == "no"):
        errors.append(f"{where}: binds opens with 'yes' or 'no' — it is what moves a tier")
    summary = data.get("summary")
    if binds.startswith("yes") and not (isinstance(summary, str) and summary.strip()):
        errors.append(f"{where}: a row that binds needs the summary line the yes-list prints")
    if binds.startswith("no") and summary is not None:
        errors.append(f"{where}: only a row that binds has a summary line")
    order = data.get("order")
    if order is not None and (not isinstance(order, int) or isinstance(order, bool) or order < 0):
        errors.append(f"{where}: order is a non-negative integer")
    return errors


def load_rows(root=ROOT):
    """(rows sorted for the table, errors). Unreadable files are errors, never skipped."""
    rows, errors = [], []
    index = runs_dir(root) / "index"
    for path in sorted(index.glob("*")) if index.is_dir() else []:
        if path.suffix != ".json" or not path.is_file():
            errors.append(f"docs/runs/index/{path.name}: only <run>.json row files live here")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
            errors.append(f"docs/runs/index/{path.name}: unreadable ({err})")
            continue
        problems = row_errors(path.name, data, root)
        errors += problems
        if not problems:
            rows.append(data)
    rows.sort(key=lambda r: (r["date"], r.get("order", 0), r["report"]))
    return rows, errors


def check_rows(root=ROOT):
    """Row-file errors plus completeness: exactly one row per dated run report."""
    rows, errors = load_rows(root)
    named = {}
    for r in rows:
        named.setdefault(r["report"], 0)
        named[r["report"]] += 1
    for report in dated_reports(root):
        if report not in named:
            errors.append(f"docs/runs/{report} has no row: add docs/runs/index/{row_key(report)}.json")
    for report, n in sorted(named.items()):
        if n > 1:
            errors.append(f"docs/runs/{report} has {n} rows")
    return errors


def render(rows, as_of):
    """The generated block: stamp, yes-summary, then the table."""
    yes = [r for r in rows if r["binds"].startswith("yes")]
    lines = [BEGIN,
             f"_Generated by `python3 scripts/run_index.py` from one row file per run in "
             f"[`index/`](index/), as of {as_of}. A run filed after that date has its row file "
             f"there and joins this table at the next release cut._",
             "",
             f"{len(yes)} of the {len(rows)} reports in the archive read **yes**:"]
    lines += [f"- {r['summary']}{'.' if i == len(yes) - 1 else ';'}" for i, r in enumerate(yes)]
    lines += ["",
              "Every other row reads **no**, and its `Binds?` cell says why.",
              "",
              HEADER]
    lines += [f"| {r['date']} | {r['mission']} | {r['target']} | {r['ran_as']} | {r['binds']} | "
              f"{r['outcome']} |" for r in rows]
    lines.append(END)
    return "\n".join(lines)


def readme_block(root=ROOT):
    """(README text, generated block match); (None, None) when the archive has no README."""
    path = runs_dir(root) / "README.md"
    if not path.is_file():
        return None, None
    text = path.read_text(encoding="utf-8")
    return text, BLOCK_RE.search(text)


COUNT_RE = re.compile(r"(?m)^(\d+) of the (\d+) reports in the archive read \*\*yes\*\*:$")


def check_snapshot(root=ROOT):
    """Errors when the README block contradicts itself, which only a hand edit can do.

    Between cuts the block is a dated snapshot, so it may lack rows filed since; it may never
    carry a count its own table does not show, a row twice, or a row for a report that is gone.
    """
    text, found = readme_block(root)
    if text is None:
        return ["docs/runs/README.md is missing — the run archive has no index page"]
    if not found:
        return ["docs/runs/README.md has no generated run-index block (its markers are gone)"]
    block = found.group(0)
    where = "docs/runs/README.md's run index"
    errors = []
    if not STAMP_RE.search(block):
        errors.append(f"{where} carries no 'as of' date")
    table = [ln for ln in block.split("\n") if ln.startswith("| 2")]
    cells = [[c.strip() for c in ln.strip("|").split(" | ")] for ln in table]
    yes = [c for c in cells if len(c) == 6 and c[4].startswith("yes")]
    bullets = [ln for ln in block.split("\n") if ln.startswith("- ")]
    count = COUNT_RE.search(block)
    if not count:
        errors.append(f"{where} has no 'N of the M reports ... read **yes**' line")
    elif (int(count.group(1)), int(count.group(2))) != (len(yes), len(table)) or len(bullets) != len(yes):
        errors.append(f"{where} says {count.group(1)} of {count.group(2)} read yes, but its table "
                      f"shows {len(yes)} of {len(table)} and its list {len(bullets)} — the count "
                      "is generated, never typed: run_index.py write at the cut")
    linked = [re.findall(r"\]\(([^)]+)\)", c[1])[:1] for c in cells]
    reports = [x[0] for x in linked if x]
    for report in sorted({r for r in reports if reports.count(r) > 1}):
        errors.append(f"{where} lists {report} twice")
    present = set(dated_reports(root))
    for report in sorted(set(reports) - present):
        errors.append(f"{where} lists {report}, which is not a run report under docs/runs/")
    return errors


def check_current(root=ROOT):
    """Errors unless the README block equals a fresh rendering at the block's own stamp."""
    rows, errors = load_rows(root)
    text, found = readme_block(root)
    if text is None:
        return errors + ["docs/runs/README.md is missing — the run archive has no index page"]
    if not found:
        return errors + ["docs/runs/README.md has no generated run-index block"]
    stamp = STAMP_RE.search(found.group(0))
    if not stamp:
        return errors + ["docs/runs/README.md's run-index block carries no 'as of' date"]
    if found.group(0) != render(rows, stamp.group(1)):
        errors.append("docs/runs/README.md's run index is not the rendering of docs/runs/index/ "
                      "— run python3 scripts/run_index.py write --as-of <the cut's date>")
    return errors


def write(as_of, root=ROOT):
    """Rewrite the README block from the row files. Raises ValueError on any row error."""
    errors = check_rows(root)
    if errors:
        raise ValueError("; ".join(errors))
    rows, _ = load_rows(root)
    text, found = readme_block(root)
    if not found:
        raise ValueError("docs/runs/README.md has no generated run-index block to fill")
    new = text[:found.start()] + render(rows, as_of) + text[found.end():]
    if new != text:
        (runs_dir(root) / "README.md").write_text(new, encoding="utf-8")
    return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="run_index.py",
                                     description="Render docs/runs/README.md's index from row files.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="row files well formed, one per dated report")
    c.add_argument("--current", action="store_true",
                   help="also require the README block to be today's rendering (the cut)")
    sub.add_parser("print", help="print the rendering without writing it")
    w = sub.add_parser("write", help="rewrite the README block (the release cut runs this)")
    w.add_argument("--as-of", required=True, help="the date the block says it was generated")
    args = parser.parse_args(argv)
    root = ROOT  # read at call time, so a test can point the CLI at a fixture in-process
    try:
        if args.cmd == "print":
            rows, errors = load_rows(root)
            for e in errors:
                print(f"FAIL {e}", file=sys.stderr)
            print(render(rows, date.today().isoformat()))
            return 1 if errors else 0
        if args.cmd == "write":
            if date.fromisoformat(args.as_of).isoformat() != args.as_of:
                raise ValueError(f"--as-of {args.as_of!r} is not YYYY-MM-DD")
            n = write(args.as_of, root)
            print(f"docs/runs/README.md: run index rendered from {n} row files, as of {args.as_of}")
            return 0
        errors = check_rows(root) + check_snapshot(root)
        if args.current:
            errors += check_current(root)
    except (OSError, ValueError) as err:
        print(f"run_index.py: {err}", file=sys.stderr)
        return 2
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        return 1
    print(f"run index: {len(dated_reports(root))} reports, one row each"
          + ("; the README block is current" if args.current else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
