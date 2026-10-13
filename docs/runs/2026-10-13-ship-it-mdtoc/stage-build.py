#!/usr/bin/env python3
"""Create a build task from a spec file and spawn its builder (custom-argv lane).

Usage (inside VM): stage-build.py <slice-key> <spec-file> <worktree-path> <title>
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
    spec = Path(spec_file).read_text()
    t = cli("orchestration", "task-create", "--spec", spec,
            "--run", s["run_id"], "--from", s["coord"])
    tid = (((t.get("result") or {}).get("task") or {}).get("id"))
    if not tid:
        sys.exit(f"task-create failed: {t}")
    s["tasks"][key] = tid
    STATE.write_text(json.dumps(s, indent=1))
    env = dict(os.environ, SP="/home/ravindra/ship527-scratch", PROFILE="rw",
               ORCA_COORD_ALLOW_AUTONOMOUS_WRITE="1", ORCA_COORD_ALLOW_CMD_OVERRIDE="1",
               WORKER_CMD="claude --dangerously-skip-permissions",
               CLAUDE_CODE_OAUTH_TOKEN=(Path.home() / ".claude-oauth-token").read_text().strip())
    p = subprocess.run(["bash", "runtime/scripts/spawn_worker.sh", "--run", s["run_id"],
                        "--from", s["coord"], tid, f"path:{wt}", title, "claude"],
                       cwd=str(Path.home() / "orca-fleet"), capture_output=True, text=True, env=env)
    out = p.stdout + p.stderr
    for line in out.splitlines():
        if line.startswith(("HANDLE=", "SPAWN=", "SCRATCH=")):
            print(line)
    print("task", key, tid)


if __name__ == "__main__":
    main()
