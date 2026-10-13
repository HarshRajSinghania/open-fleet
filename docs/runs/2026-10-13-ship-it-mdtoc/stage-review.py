#!/usr/bin/env python3
"""Spawn a build-blind reviewer (PROFILE=ro) from a spec file. VM-side.

Usage: stage-review.py <slice-key> <spec-file> <worktree-path> <title>
"""
import json
import os
import subprocess
import sys
from pathlib import Path

STATE = Path.home() / "ship527" / "state.json"


def cli(*a):
    p = subprocess.run(["orca-ide", *a, "--json"], capture_output=True, text=True)
    return json.loads(p.stdout or "{}")


def main():
    key, spec_file, wt, title = sys.argv[1:5]
    s = json.load(open(STATE))
    t = cli("orchestration", "task-create", "--spec", Path(spec_file).read_text(),
            "--run", s["run_id"], "--from", s["coord"])
    tid = (((t.get("result") or {}).get("task") or {}).get("id"))
    if not tid:
        sys.exit(f"task-create failed: {t}")
    s.setdefault("reviews", {})[key] = tid
    STATE.write_text(json.dumps(s, indent=1))
    env = dict(os.environ, SP="/home/ravindra/ship527-scratch", PROFILE="ro",
               CLAUDE_CODE_OAUTH_TOKEN=(Path.home() / ".claude-oauth-token").read_text().strip())
    p = subprocess.run(["bash", "runtime/scripts/spawn_worker.sh", "--run", s["run_id"],
                        "--from", s["coord"], tid, f"path:{wt}", title, "claude"],
                       cwd=str(Path.home() / "orca-fleet"), capture_output=True, text=True, env=env)
    for line in (p.stdout + p.stderr).splitlines():
        if line.startswith(("HANDLE=", "SPAWN=", "SCRATCH=")):
            print(line)
    print("review task", key, tid)


if __name__ == "__main__":
    main()
