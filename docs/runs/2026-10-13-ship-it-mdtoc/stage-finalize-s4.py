import hashlib
import json
from pathlib import Path

RD = Path("/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013/docs/runs/2026-10-13-ship-it-mdtoc")
REL = "docs/runs/2026-10-13-ship-it-mdtoc"
HEAD = "4aa77558d1be809ed98acb5ea2847386ef3e9a5d"

m = json.loads((RD / "manifest-s4.json").read_text())
m["claim"] = ("S4: GitHub-faithful slugs + rendered-text labels (nested links resolved, inline HTML stripped, "
              "autolinks kept as text, combining marks kept) on fleet/build-s4 @4aa7755 "
              "(after round-1 PASS-with-MEDIUM + fix round + round-2 clean PASS)")
m["head_sha"] = HEAD
for c in m["commands"]:
    a = c.get("artifact") or ""
    if a.startswith("/"):
        c["artifact"] = REL + a[len(str(RD)):]
m["intent"] = {
    "goal": "Close the three carried GitHub-slug deviations (nested links, inline HTML, decomposed accents) and make labels derive from rendered text",
    "ruled_out": "Reference-style link resolution (no definition lookup); balanced-paren destinations; sentinel-collision hardening beyond documentation",
    "why": "AC-2 defines slugs by reference to GitHub; inputs that leaked raw markup or dropped combining marks produced links GitHub itself would not resolve to the rendered anchor",
}
m["negative_control"] = {
    "tool": "hand",
    "result": ("hand mutant (drop M* combining marks from the slug keep-set in mdtoc/toc.py at 4aa7755) turned the "
               "suite RED: 1 failure in the decomposed-accent guard — mutant killed"),
    "artifact": f"{REL}/prove/s4-nc-fixed.txt",
    "command": "python3 -m unittest discover",
    "criterion_ids": ["AC-2"],
}
m["review"] = {"artifact": f"{REL}/reviews/s4-record.md", "reviewed_sha": HEAD}
m["reviewer_mode"] = "same-vendor-fresh"

pin = [
    "prove/s4-tests.txt", "prove/s4-prove.txt", "prove/s4-nc.txt", "prove/s4-nc-run.txt",
    "prove/s4-tests-fixed.txt", "prove/s4-prove-fixed.txt", "prove/s4-nc-fixed.txt", "prove/s4-nc-run-fixed.txt",
    "reviews/s4.md", "reviews/s4-r2.md", "reviews/s4-record.md",
    "deliveries/s4-worker-done.json", "deliveries/s4-fix-done.json",
    "deliveries/s4-review-done.json", "deliveries/s4-rereview-done.json",
    "prove/s4-verifier.txt",
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
(RD / "manifest-s4.json").write_text(json.dumps(m, indent=2) + "\n")
print("manifest-s4.json finalized:", len(m["commands"]), "commands,", len(m["artifacts"]), "artifacts, head", HEAD[:8])
