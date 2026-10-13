#!/usr/bin/env python3
"""Coordinator driver — ship-it mdtoc external run (#515), stage A: run + F0 task."""
import json
import subprocess
import sys
from pathlib import Path

STATE = Path.home() / "ship527" / "state.json"
WT = "path:/Users/ravindra/projects/mdtoc"
RUN_DIR = ("/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013"
           "/docs/runs/2026-10-13-ship-it-mdtoc")

F0_SPEC = f"""TASK pack: matt (tdd). Slice F0 — foundation scaffold for mdtoc.
Repo: ravidsrk/mdtoc (your dispatched worktree/branch off fleet/ship-mdtoc-20261013).
Frozen spec: SPEC.md in repo root (read it). Slice contract: {RUN_DIR}/slice-contracts.md (F0).

Deliver, TDD-style (failing test first where a claim is testable):
- FC-1: package `mdtoc` (mdtoc/__init__.py with __version__, mdtoc/__main__.py,
  mdtoc/cli.py using argparse: positional files (nargs+), --check, --stdout,
  --max-depth int). `python3 -m mdtoc --help` exits 0. main() may for now only
  parse args and validate that each named file exists and is UTF-8, exiting 0
  (later slices add behavior; keep the seam clean, no dead speculative code).
- FC-2: tests/ with unittest smoke tests (help exits 0 via subprocess; package
  imports; main([]) usage error exit code). `python3 -m unittest discover` green.
- FC-3: README Usage section stub naming the CLI surface (flags above).

Python >=3.11 stdlib only. Commit your work on your branch (small commits ok).
Do NOT push (no credentials in this VM; the coordinator lands locally) and do
not touch SPEC.md. Send worker_done exactly once per your preamble, naming
your branch, head SHA, the test command you ran and its result, and
--files-modified with every file you changed."""


def run(*a):
    p = subprocess.run(["orca-ide", *a, "--json"], capture_output=True, text=True)
    print("$ orca-ide", " ".join(a)[:100], "exit", p.returncode)
    try:
        return json.loads(p.stdout)
    except Exception:
        print((p.stdout or p.stderr)[:500])
        return {}


def main():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    r = run("terminal", "create", "--worktree", WT, "--title", "SHIP-COORD-LINUX")
    coord = (((r.get("result") or {}).get("terminal") or {}).get("handle"))
    if not coord:
        sys.exit("coordinator terminal failed")
    r = run("orchestration", "run-create", "--objective",
            "ship-it external (#515): build mdtoc to BUILT on fleet/ship-mdtoc-20261013",
            "--from", coord)
    run_id = (((r.get("result") or {}).get("run") or {}).get("id"))
    if not run_id:
        sys.exit("run-create failed")
    t = run("orchestration", "task-create", "--spec", F0_SPEC, "--run", run_id, "--from", coord)
    tid = (((t.get("result") or {}).get("task") or {}).get("id"))
    STATE.write_text(json.dumps({"coord": coord, "run_id": run_id,
                                   "tasks": {"F0": tid}}, indent=1))
    print("coord", coord, "run", run_id, "F0", tid)


if __name__ == "__main__":
    main()
