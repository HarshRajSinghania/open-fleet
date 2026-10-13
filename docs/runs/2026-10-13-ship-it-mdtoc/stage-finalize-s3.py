import hashlib
import json
from pathlib import Path

RD = Path("/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013/docs/runs/2026-10-13-ship-it-mdtoc")
REL = "docs/runs/2026-10-13-ship-it-mdtoc"
HEAD = "04a9e8f3c4fb9acdea6e0279b5719c37bdfcd43a"

m = json.loads((RD / "manifest-s3.json").read_text())
for c in m["commands"]:
    a = c.get("artifact") or ""
    if a.startswith("/"):
        c["artifact"] = REL + a[len(str(RD)):]
m["intent"] = {
    "goal": "Multi-file invocation with per-file independence + aggregated exit codes (AC-7), clean missing/non-UTF-8 errors (AC-9), README usage docs",
    "ruled_out": "Duplicate-FILE deduplication (processed twice, recorded as known limit); atomic writes",
    "why": "Batch use over a docs tree is the realistic invocation; one bad file must never block the rest, and the exit code must still say so",
}
m["negative_control"] = {
    "tool": "hand",
    "result": ("hand mutant (return on first per-file error in cli.main at 04a9e8f) turned the suite RED: "
               "2 failures in the multi-file independence guards — mutant killed"),
    "artifact": f"{REL}/prove/s3-nc.txt",
    "command": "python3 -m unittest discover",
    "criterion_ids": ["AC-7"],
}
m["review"] = {"artifact": f"{REL}/reviews/s3-record.md", "reviewed_sha": HEAD}
m["reviewer_mode"] = "same-vendor-fresh"

pin = [
    "prove/s3-tests.txt", "prove/s3-prove.txt", "prove/s3-nc.txt", "prove/s3-nc-run.txt",
    "reviews/s3.md", "reviews/s3-record.md",
    "deliveries/s3-worker-done.json", "deliveries/s3-review-done.json",
    "prove/s3-verifier.txt",
]
pin = [p for p in pin if (RD / p).exists()]
m["artifacts"] = [
    {"path": f"{REL}/{p}", "sha256": hashlib.sha256((RD / p).read_bytes()).hexdigest()}
    for p in pin
]
cmd_artifacts = {c["artifact"] for c in m["commands"] if c.get("artifact")}
pinned = {a["path"] for a in m["artifacts"]}
missing = cmd_artifacts - pinned
assert not missing, f"unpinned command artifacts: {missing}"
(RD / "manifest-s3.json").write_text(json.dumps(m, indent=2) + "\n")
print("manifest-s3.json finalized:", len(m["commands"]), "commands,", len(m["artifacts"]), "artifacts, head", HEAD[:8])
