import hashlib
import json
from pathlib import Path

RD = Path("/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013/docs/runs/2026-10-13-ship-it-mdtoc")
REL = "docs/runs/2026-10-13-ship-it-mdtoc"
HEAD = "47ef84f2f0463c191b83182b77ddf3f0c641ec51"

m = json.loads((RD / "manifest-s5.json").read_text())
for c in m["commands"]:
    a = c.get("artifact") or ""
    if a.startswith("/"):
        c["artifact"] = REL + a[len(str(RD)):]
m["intent"] = {
    "goal": "Close integrated-review F1-F4: Markdown line-ending model, BOM pinned at byte 0, relative indent",
    "ruled_out": "Double-BOM stripping (byte-0-only rule); mixed-EOL normalization beyond first-seen-terminator for inserted lines",
    "why": "The integrated FAIL showed real inputs (Windows BOM, classic CR) breaking idempotence and corrupting heading structure — the tool's core promise is byte-safety outside the TOC region",
}
m["negative_control"] = {
    "tool": "hand",
    "result": ("hand mutant (drop bare CR from the _EOL terminator set in mdtoc/toc.py at 47ef84f) turned the suite "
               "RED: 3 failures in the CR-only guards — mutant killed"),
    "artifact": f"{REL}/prove/s5-nc.txt",
    "command": "python3 -m unittest discover",
    "criterion_ids": ["AC-1"],
}
m["review"] = {"artifact": f"{REL}/reviews/s5-record.md", "reviewed_sha": HEAD}
m["reviewer_mode"] = "same-vendor-fresh"

pin = [
    "prove/s5-tests.txt", "prove/s5-prove.txt", "prove/s5-nc.txt", "prove/s5-nc-run.txt",
    "reviews/s5.md", "reviews/s5-record.md",
    "deliveries/s5-worker-done.json", "deliveries/s5-review-done.json",
    "prove/s5-verifier.txt",
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
(RD / "manifest-s5.json").write_text(json.dumps(m, indent=2) + "\n")
print("manifest-s5.json finalized:", len(m["commands"]), "commands,", len(m["artifacts"]), "artifacts, head", HEAD[:8])
