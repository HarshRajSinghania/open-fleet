import json
import os
import subprocess
import sys

HEAD = "04a9e8f3c4fb9acdea6e0279b5719c37bdfcd43a"
BASE = "fedebc75210f0944e1d4f39c262717c9f53cd4f4"
HOME = os.path.expanduser("~")
RD = "/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013/docs/runs/2026-10-13-ship-it-mdtoc"
MANIFEST = f"{RD}/manifest-s3.json"
EVID = os.path.expanduser("~/orca-fleet/runtime/scripts/evidence-run.py")
SRC = "/Users/ravindra/projects/mdtoc"
FIXED = f"{HOME}/ship527/s3-head"
NC = f"{HOME}/ship527/nc-s3"
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
        "unit": "mdtoc-s3-multifile-errors",
        "claim": "S3: multi-file invocation with per-file independence, aggregated exit codes, clean missing/non-UTF-8 errors, README usage docs on fleet/build-s3",
        "base_sha": BASE,
        "head_sha": HEAD,
        "base_branch": "fleet/ship-mdtoc-20261013",
        "contract": {
            "source": "docs/runs/2026-10-13-ship-it-mdtoc/contracts/s3.md@ece804243577d26fc33222ef9c4f1b333be4c29f",
            "digest": "sha256:4df480a3c647e715e5d0f4c8b47130ba81f29ed2efb9409ec819493ad1990bfb",
            "criterion_ids": ["AC-7", "AC-9"],
        },
        "criteria": [
            {"id": "AC-7", "text": "multiple files per invocation; per-file errors don't abort; exit aggregates", "addressed": True},
            {"id": "AC-9", "text": "missing or non-UTF-8 file -> stderr message, exit 2", "addressed": True},
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

open("/tmp/m1.md", "w").write("# One\n\n## Alpha\n")
open("/tmp/m2.md", "w").write("# Two\n\n## Beta\n")

evid("tests-s3", f"{RD}/prove/s3-tests.txt", FIXED, 0,
     "python3", "-m", "unittest", "discover")
evid("runtime-prove-s3", f"{RD}/prove/s3-prove.txt", FIXED, 0,
     "python3", "-m", "mdtoc", "--stdout", "/tmp/m1.md", "/tmp/m2.md")

# hand NC: abort on first file error -> AC-7 independence guards must go RED
run(["cp", "-a", FIXED, NC])
cli = f"{NC}/mdtoc/cli.py"
src = open(cli).read()
old = '            print(f"mdtoc: {name}: no such file", file=sys.stderr)\n            status = 2'
assert old in src, "mutant anchor not found"
open(cli, "w").write(src.replace(old, '            print(f"mdtoc: {name}: no such file", file=sys.stderr)\n            return 2  # NC MUTANT: abort on first error'))
diff = run(["git", "-C", NC, "diff"]).stdout
evid("neg-control-s3", f"{RD}/prove/s3-nc-run.txt", NC, 1,
     "python3", "-m", "unittest", "discover")
nc_out = open(f"{RD}/prove/s3-nc-run.txt").read()
with open(f"{RD}/prove/s3-nc.txt", "w") as f:
    f.write("hand negative control (coordinator-executed): return on first per-file error in cli.main; suite must go RED\n")
    f.write(diff)
    f.write("== unittest under mutant (see s3-nc-run.txt, evidence-bound) ==\n")
    f.write("\n".join(nc_out.splitlines()[-4:]) + "\n")
print("NC tail:", nc_out.splitlines()[-1] if nc_out.splitlines() else "(empty)")
