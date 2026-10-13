import hashlib
import json
from pathlib import Path

RD = Path("/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013/docs/runs/2026-10-13-ship-it-mdtoc")
REL = "docs/runs/2026-10-13-ship-it-mdtoc"
HEAD = "a960241d781231af4d1bf30ffba27b9887e363d1"

m = json.loads((RD / "manifest-s2.json").read_text())
m["claim"] = ("S2: in-place TOC update between fence-aware markers (idempotent), exactly-one-pair "
              "marker discipline, no-marker placement, --check/--stdout modes, --max-depth validation "
              "on fleet/build-s2 @a960241 (after round-1 PASS-with-MEDIUMs + fix round + round-2 PASS)")
m["head_sha"] = HEAD
for c in m["commands"]:
    a = c.get("artifact") or ""
    if a.startswith("/"):
        c["artifact"] = REL + a[len(str(RD)):]
m["intent"] = {
    "goal": "In-place TOC update between markers, check/stdout modes, depth limiting (AC-1, AC-4, AC-5, AC-6 placement half)",
    "ruled_out": "Multi-file aggregation and per-file error semantics (S3); inline-code-span marker matching (deferred LOW, fails safe); setext anchors",
    "why": "The update is the user-visible behavior of the tool; marker discipline is what keeps it from corrupting docs that merely show the markers",
}
m["negative_control"] = {
    "tool": "hand",
    "result": ("hand mutant (disable _outside_fences fence-awareness in mdtoc/toc.py at a960241) turned the suite "
               "RED: 10 failures + 1 error incl. fenced-marker and fence-heading guards — mutant killed"),
    "artifact": f"{REL}/prove/s2-nc-fixed.txt",
    "command": "python3 -m unittest discover",
    "criterion_ids": ["AC-1"],
}
m["review"] = {"artifact": f"{REL}/reviews/s2-record.md", "reviewed_sha": HEAD}
m["reviewer_mode"] = "same-vendor-fresh"

pin = [
    "prove/s2-tests.txt", "prove/s2-prove.txt", "prove/s2-nc.txt",
    "prove/s2-tests-fixed.txt", "prove/s2-prove-fixed.txt",
    "prove/s2-nc-fixed.txt", "prove/s2-nc-run-fixed.txt",
    "reviews/s2.md", "reviews/s2-r2.md", "reviews/s2-record.md",
    "deliveries/s2-worker-done.json", "deliveries/s2-fix-done.json",
    "deliveries/s2-review-done.json", "deliveries/s2-rereview-done.json",
    "prove/s2-verifier.txt",
]
m["artifacts"] = [
    {"path": f"{REL}/{p}", "sha256": hashlib.sha256((RD / p).read_bytes()).hexdigest()}
    for p in pin
]
cmd_artifacts = {c["artifact"] for c in m["commands"] if c.get("artifact")}
pinned = {a["path"] for a in m["artifacts"]}
missing = cmd_artifacts - pinned
assert not missing, f"unpinned command artifacts: {missing}"
(RD / "manifest-s2.json").write_text(json.dumps(m, indent=2) + "\n")
print("manifest-s2.json finalized:", len(m["commands"]), "commands,", len(m["artifacts"]), "artifacts, head", HEAD[:8])
