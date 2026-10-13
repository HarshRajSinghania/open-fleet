import json
import os
import subprocess
import sys

HEAD = "47ef84f2f0463c191b83182b77ddf3f0c641ec51"
BASE = "c9a6f683bb497d975e4bcd76b5163689e4da794d"
HOME = os.path.expanduser("~")
RD = "/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013/docs/runs/2026-10-13-ship-it-mdtoc"
MANIFEST = f"{RD}/manifest-s5.json"
EVID = os.path.expanduser("~/orca-fleet/runtime/scripts/evidence-run.py")
SRC = "/Users/ravindra/projects/mdtoc"
FIXED = f"{HOME}/ship527/s5-head"
NC = f"{HOME}/ship527/nc-s5"
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


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
        "unit": "mdtoc-s5-eol-bom-seams",
        "claim": "S5: Markdown line-ending model (CRLF/CR/LF only, first-seen terminator), BOM pinned at byte 0, shallowest-relative TOC indent on fleet/build-s5",
        "base_sha": BASE,
        "head_sha": HEAD,
        "base_branch": "fleet/ship-mdtoc-20261013",
        "contract": {
            "source": "docs/runs/2026-10-13-ship-it-mdtoc/contracts/s5.md@fbb0874c79d09ab3a8e192da742290c518557fb5",
            "digest": "sha256:7a5bf38bc72770452d40cdbcf468220463f2a9d25a91bfd635ea63c694caadc4",
            "criterion_ids": ["AC-1", "AC-6"],
        },
        "criteria": [
            {"id": "AC-1", "text": "idempotent for LF/CRLF/CR-only; only CRLF/CR/LF split lines; first-seen terminator used; relative indent", "addressed": True},
            {"id": "AC-6", "text": "insert after first H1 else top; BOM stays at byte 0, never hides first heading", "addressed": True},
        ],
        "commands": [],
        "toolchain": "CPython 3.12.3 Ubuntu 24.04.5 arm64 (OrbStack); orca-ide 1.4.224; Claude Code 2.1.296 workers",
    }
    open(MANIFEST, "w").write(json.dumps(skeleton, indent=2) + "\n")
    print("manifest skeleton written")

subprocess.run(["rm", "-rf", FIXED, NC], check=True)
run(["git", "clone", "--quiet", SRC, FIXED])
run(["git", "-C", FIXED, "checkout", "--quiet", HEAD])
print("head:", run(["git", "-C", FIXED, "rev-parse", "HEAD"]).stdout.strip())

with open("/tmp/m4.md", "wb") as f:
    f.write(b"\xef\xbb\xbf# Guide\r## Intro\r## Use `x`\r")

evid("tests-s5", f"{RD}/prove/s5-tests.txt", FIXED, 0,
     "python3", "-m", "unittest", "discover")
evid("runtime-prove-s5", f"{RD}/prove/s5-prove.txt", FIXED, 0,
     "python3", "-m", "mdtoc", "--stdout", "/tmp/m4.md")

# hand NC: CR no longer a line terminator -> CR-only guards must go RED
run(["cp", "-a", FIXED, NC])
toc = f"{NC}/mdtoc/toc.py"
src = open(toc).read()
old = '_EOL = re.compile(r"\\r\\n|\\r|\\n")'
assert old in src, "mutant anchor not found"
open(toc, "w").write(src.replace(old, '_EOL = re.compile(r"\\r\\n|\\n")  # NC MUTANT: bare CR not a terminator'))
diff = run(["git", "-C", NC, "diff"]).stdout
evid("neg-control-s5", f"{RD}/prove/s5-nc-run.txt", NC, 1,
     "python3", "-m", "unittest", "discover")
nc_out = open(f"{RD}/prove/s5-nc-run.txt").read()
with open(f"{RD}/prove/s5-nc.txt", "w") as f:
    f.write("hand negative control (coordinator-executed): drop bare CR from the terminator set in _EOL; suite must go RED\n")
    f.write(diff)
    f.write("== unittest under mutant (see s5-nc-run.txt, evidence-bound) ==\n")
    f.write("\n".join(nc_out.splitlines()[-4:]) + "\n")
print("NC tail:", nc_out.splitlines()[-1] if nc_out.splitlines() else "(empty)")
