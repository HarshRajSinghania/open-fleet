import os
import subprocess
import sys

HEAD = "a960241d781231af4d1bf30ffba27b9887e363d1"
HOME = os.path.expanduser("~")
RD = "/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013/docs/runs/2026-10-13-ship-it-mdtoc"
MANIFEST = f"{RD}/manifest-s2.json"
EVID = os.path.expanduser("~/orca-fleet/runtime/scripts/evidence-run.py")
SRC = "/Users/ravindra/projects/mdtoc"
FIXED = f"{HOME}/ship527/s2-fixed"
NC = f"{HOME}/ship527/nc-s2-fixed"
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def run(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(f"FAILED {cmd} rc={p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


def evid(label, artifact, cwd, *cmd):
    p = run(["python3", EVID, "--label", label, "--manifest", MANIFEST,
             "--artifact", artifact, "--cwd", cwd, "--", *cmd], check=False)
    assert p.returncode == 1, f"{label}: expected wrapped-exit 1, got {p.returncode}\n{p.stderr}"
    print(label, "recorded (wrapped exit 1 as expected)")

# hand NC: disable fence-awareness in marker scan -> F1 guards must go RED
run(["cp", "-a", FIXED, NC])
toc = f"{NC}/mdtoc/toc.py"
src = open(toc).read()
old = '    """Yield (line_index, line) for lines that are not fenced code or fence delimiters."""'
assert old in src, "mutant anchor not found"
mutant = old + "\n    yield from enumerate(text.splitlines())  # NC MUTANT: fence-awareness off\n    return"
open(toc, "w").write(src.replace(old, mutant))
diff = run(["git", "-C", NC, "diff"]).stdout
evid("neg-control-s2-fixed", f"{RD}/prove/s2-nc-run-fixed.txt", NC,
     "python3", "-m", "unittest", "discover")
nc_out = open(f"{RD}/prove/s2-nc-run-fixed.txt").read()
with open(f"{RD}/prove/s2-nc-fixed.txt", "w") as f:
    f.write("hand negative control (coordinator-executed): disable fence-awareness in "
            "_outside_fences (marker + heading scan); suite must go RED\n")
    f.write(diff)
    f.write("== unittest under mutant (see s2-nc-run-fixed.txt, evidence-bound) ==\n")
    f.write("\n".join(nc_out.splitlines()[-4:]) + "\n")
print("NC tail:", nc_out.splitlines()[-1] if nc_out.splitlines() else "(empty artifact)")
