import subprocess
import sys
import tempfile
from pathlib import Path

WT = sys.argv[1]
sys.path.insert(0, WT)
from mdtoc.toc import render_toc, update_text  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" :: " + detail if detail else ""))
    if not cond:
        fails.append(name)


def run(*args):
    return subprocess.run([sys.executable, "-m", "mdtoc", *args], cwd=WT, capture_output=True, text=True)


doc = "# Guide\n\n<!-- toc -->\n- [Stale](#stale)\n<!-- /toc -->\n\n## Install\n\n### From source\n\n## Usage\n"
once = update_text(doc)
check("AC-1 stale TOC replaced", "- [Install](#install)" in once and "Stale" not in once)
check("AC-1 second run byte-identical", update_text(once) == once)

toc = render_toc("## Setup\n## Setup\n## Setup\n")
check("AC-2 duplicate suffixes", "(#setup)" in toc and "(#setup-1)" in toc and "(#setup-2)" in toc)
check("AC-2 nested link", render_toc("## [See [inner](http://x)](http://y)\n").strip() == "- [See inner](#see-inner)")
check("AC-2 inline HTML", render_toc("## Hello <em>World</em>\n").strip() == "- [Hello World](#hello-world)")
check("AC-2 autolink", render_toc("## <http://example.com>\n").strip() == "- [http://example.com](#httpexamplecom)")
check("AC-2 combining mark", render_toc("## Café\n").strip() == "- [Café](#café)")

toc = render_toc("## Real\n```\n## Fenced\n```\n")
check("AC-3 fenced heading excluded", "Fenced" not in toc and "Real" in toc)

with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    f = d / "g.md"; f.write_text("# G\n\n## A\n\n##### Deep\n")
    p = run("--check", str(f)); check("AC-4 check missing -> 1", p.returncode == 1)
    p = run(str(f)); check("AC-6 insert after H1", p.returncode == 0 and f.read_text().startswith("# G\n\n<!-- toc -->"))
    check("AC-5 default depth excludes H5", "- [Deep]" not in f.read_text())
    p = run("--check", str(f)); check("AC-4 check current -> 0", p.returncode == 0)
    p = run("--stdout", str(f)); check("AC-4 stdout prints, no write", p.returncode == 0 and p.stdout == f.read_text())
    p = run("--max-depth", "9", str(f)); check("AC-5 invalid depth -> 2", p.returncode == 2)
    p = run(str(f), str(d / "gone.md")); check("AC-7+AC-9 mixed -> 2", p.returncode == 2 and "gone.md" in p.stderr)
    g = d / "h.md"; g.write_text("# H\n## B\n")
    p = run(str(d / "gone.md"), str(g)); check("AC-7 later file updated", p.returncode == 2 and "- [B](#b)" in g.read_text())

# S5 seams (integrated-review F1-F4 repros)
cr1 = update_text("# T\r## A\r")
check("F1 CR-only idempotent, all-CR", update_text(cr1) == cr1 and "\n" not in cr1.replace("\r", ""))
check("F3 exotic separator not a break", render_toc("## A\x0cB\n").strip() == "- [A\x0cB](#ab)")
bom = update_text("﻿# T\n## A\n")
check("F2 BOM byte-0 + after H1", bom.startswith("﻿# T\n\n<!-- toc -->") and update_text(bom) == bom)
check("F2 BOM+CR combined", update_text("﻿# T\r## A\r").startswith("﻿# T\r\r<!-- toc -->"))
check("F4 lone H4 column 0", render_toc("#### Deep\n").startswith("- [Deep]"))

p = subprocess.run([sys.executable, "-m", "unittest", "discover"], cwd=WT, capture_output=True, text=True)
check("AC-8 suite green", p.returncode == 0 and "OK" in p.stderr,
      p.stderr.strip().splitlines()[-2] if p.stderr.strip() else "")

print("RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
