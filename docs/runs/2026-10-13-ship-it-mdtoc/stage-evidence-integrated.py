import json
import os
import subprocess
import sys

HEAD = "c9a6f683bb497d975e4bcd76b5163689e4da794d"
BASE = "0b9f660d93e64cf57e8245b0f1eb6eb0010ae158"
HOME = os.path.expanduser("~")
RD = "/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013/docs/runs/2026-10-13-ship-it-mdtoc"
MANIFEST = f"{RD}/manifest-integrated.json"
EVID = os.path.expanduser("~/orca-fleet/runtime/scripts/evidence-run.py")
SRC = "/Users/ravindra/projects/mdtoc"
FIXED = f"{HOME}/ship527/int-head"
NC = f"{HOME}/ship527/nc-int"
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

CRIT = [
    ("AC-1", "insert/update between markers, idempotent"),
    ("AC-2", "GitHub anchor slugs incl. duplicate suffixes"),
    ("AC-3", "headings in fenced code ignored"),
    ("AC-4", "--check 1 stale/missing, 0 current; --stdout prints, never writes"),
    ("AC-5", "default depth H2-H4; --max-depth 1..6"),
    ("AC-6", "no markers: insert after first H1, else top"),
    ("AC-7", "multiple files; per-file errors don't stop others; exit aggregates"),
    ("AC-8", "unittest suite covers slugging/fences/update/check; green"),
    ("AC-9", "missing or non-UTF-8 file: stderr message, exit 2"),
]


def run(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(f"FAILED {cmd} rc={p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


def evid(label, artifact, cwd, want_exit, *cmd):
    p = run(["python3", EVID, "--label", label, "--manifest", MANIFEST,
             "--artifact", artifact, "--cwd", cwd, "--", *cmd], check=False)
    assert p.returncode == want_exit, f"{label}: expected wrapped exit {want_exit}, got {p.returncode}\n{p.stderr}"
    print(label, f"recorded (wrapped exit {want_exit})")


if not os.path.exists(MANIFEST):
    skeleton = {
        "unit": "mdtoc-ship-integrated",
        "claim": "Integrated: ravidsrk/mdtoc built from frozen SPEC.md to BUILT on fleet/ship-mdtoc-20261013 (F0+S1+S2+S3+S4)",
        "base_sha": BASE,
        "head_sha": HEAD,
        "base_branch": "fleet/ship-mdtoc-20261013",
        "contract": {
            "source": "docs/runs/2026-10-13-ship-it-mdtoc/contracts/integrated.md@faf90eb293702af50e8e9310c26cab90f3cac16a",
            "digest": "sha256:01b5aea7cd817b4170207ca627ceaa8db3732866eea0581fe69d865d22f1ad4e",
            "criterion_ids": [c for c, _ in CRIT],
        },
        "criteria": [{"id": c, "text": t, "addressed": True} for c, t in CRIT],
        "commands": [],
        "toolchain": "CPython 3.12.3 Ubuntu 24.04.5 arm64 (OrbStack); orca-ide 1.4.224; Claude Code 2.1.296 workers",
    }
    open(MANIFEST, "w").write(json.dumps(skeleton, indent=2) + "\n")
    print("manifest skeleton written")

subprocess.run(["rm", "-rf", FIXED, NC], check=True)
run(["git", "clone", "--quiet", SRC, FIXED])
run(["git", "-C", FIXED, "checkout", "--quiet", HEAD])
print("head:", run(["git", "-C", FIXED, "rev-parse", "HEAD"]).stdout.strip())

open("/tmp/int.md", "w").write(
    "# Handbook\n\n```md\n<!-- toc -->\n<!-- /toc -->\n```\n\n<!-- toc -->\n<!-- /toc -->\n\n"
    "## Getting <em>Started</em>\n\n## Café\n\n### From source\n\n## Getting Started\n")

evid("tests-integrated", f"{RD}/prove/int-tests.txt", FIXED, 0,
     "python3", "-m", "unittest", "discover")
evid("integrated-battery", f"{RD}/prove/int-battery.txt", FIXED, 0,
     "python3", f"{RD}/prove/integrated-probe.py", FIXED)
evid("runtime-prove-integrated", f"{RD}/prove/int-prove.txt", FIXED, 0,
     "python3", "-m", "mdtoc", "--stdout", "/tmp/int.md")

run(["cp", "-a", FIXED, NC])
toc = f"{NC}/mdtoc/toc.py"
src = open(toc).read()
old = '    """Yield (line_index, line) for lines that are not fenced code or fence delimiters."""'
assert old in src, "mutant anchor not found"
mutant = old + "\n    yield from enumerate(text.splitlines())  # NC MUTANT: fence-awareness off\n    return"
open(toc, "w").write(src.replace(old, mutant))
diff = run(["git", "-C", NC, "diff"]).stdout
evid("neg-control-integrated", f"{RD}/prove/int-nc-run.txt", NC, 1,
     "python3", "-m", "unittest", "discover")
nc_out = open(f"{RD}/prove/int-nc-run.txt").read()
with open(f"{RD}/prove/int-nc.txt", "w") as f:
    f.write("hand negative control (coordinator-executed): disable fence-awareness in _outside_fences; suite must go RED\n")
    f.write(diff)
    f.write("== unittest under mutant (see int-nc-run.txt, evidence-bound) ==\n")
    f.write("\n".join(nc_out.splitlines()[-4:]) + "\n")
print("NC tail:", nc_out.splitlines()[-1] if nc_out.splitlines() else "(empty)")
