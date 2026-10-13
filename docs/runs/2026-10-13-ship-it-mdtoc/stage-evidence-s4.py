import json
import os
import subprocess
import sys

HEAD = "4aa77558d1be809ed98acb5ea2847386ef3e9a5d"
BASE = "c574a54731095b063b8e3a155dcedb17e5076a52"
HOME = os.path.expanduser("~")
RD = "/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013/docs/runs/2026-10-13-ship-it-mdtoc"
MANIFEST = f"{RD}/manifest-s4.json"
EVID = os.path.expanduser("~/orca-fleet/runtime/scripts/evidence-run.py")
SRC = "/Users/ravindra/projects/mdtoc"
FIXED = f"{HOME}/ship527/s4-head"
NC = f"{HOME}/ship527/nc-s4"
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
        "unit": "mdtoc-s4-slug-hardening",
        "claim": "S4: GitHub-faithful slugs + rendered-text labels (nested links, inline HTML stripped, combining marks kept) on fleet/build-s4",
        "base_sha": BASE,
        "head_sha": HEAD,
        "base_branch": "fleet/ship-mdtoc-20261013",
        "contract": {
            "source": "docs/runs/2026-10-13-ship-it-mdtoc/contracts/s4.md@95b0d729ee125669a9023b3cce4a51b55fca29e0",
            "digest": "sha256:058443a30f3a4f93a2a996f62ebfe8ab09a24cedf82498ed5fcc11c581113b93",
            "criterion_ids": ["AC-2"],
        },
        "criteria": [{"id": "AC-2", "text": "GitHub anchor slugs; rendered text strips HTML/nested-link markup; combining marks kept; labels = rendered text", "addressed": True}],
        "commands": [],
        "toolchain": "CPython 3.12.3 Ubuntu 24.04.5 arm64 (OrbStack); orca-ide 1.4.224; Claude Code 2.1.296 workers",
    }
    open(MANIFEST, "w").write(json.dumps(skeleton, indent=2) + "\n")
    print("manifest skeleton written")

subprocess.run(["rm", "-rf", FIXED, NC], check=True)
run(["git", "clone", "--quiet", SRC, FIXED])
run(["git", "-C", FIXED, "checkout", "--quiet", HEAD])
print("head:", run(["git", "-C", FIXED, "rev-parse", "HEAD"]).stdout.strip())

open("/tmp/m3.md", "w").write("# Guide\n\n## Hello <em>World</em>\n\n## Café\n\n## [See [inner](http://x)](http://y)\n")

evid("tests-s4-fixed", f"{RD}/prove/s4-tests-fixed.txt", FIXED, 0,
     "python3", "-m", "unittest", "discover")
evid("runtime-prove-s4-fixed", f"{RD}/prove/s4-prove-fixed.txt", FIXED, 0,
     "python3", "-m", "mdtoc", "--stdout", "/tmp/m3.md")

# hand NC: drop combining marks from the slug keep-set -> AC-2 guards must go RED
run(["cp", "-a", FIXED, NC])
toc = f"{NC}/mdtoc/toc.py"
src = open(toc).read()
old = 'unicodedata.category(c)[0] in "LMN"'
assert old in src, "mutant anchor not found"
open(toc, "w").write(src.replace(old, 'unicodedata.category(c)[0] in "LN"  # NC MUTANT: combining marks dropped'))
diff = run(["git", "-C", NC, "diff"]).stdout
evid("neg-control-s4-fixed", f"{RD}/prove/s4-nc-run-fixed.txt", NC, 1,
     "python3", "-m", "unittest", "discover")
nc_out = open(f"{RD}/prove/s4-nc-run-fixed.txt").read()
with open(f"{RD}/prove/s4-nc-fixed.txt", "w") as f:
    f.write("hand negative control (coordinator-executed): remove M* (combining marks) from the slug keep-set; suite must go RED\n")
    f.write(diff)
    f.write("== unittest under mutant (see s4-nc-run.txt, evidence-bound) ==\n")
    f.write("\n".join(nc_out.splitlines()[-4:]) + "\n")
print("NC tail:", nc_out.splitlines()[-1] if nc_out.splitlines() else "(empty)")
