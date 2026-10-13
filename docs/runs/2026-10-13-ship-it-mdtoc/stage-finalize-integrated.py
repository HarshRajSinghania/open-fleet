import hashlib
import json
from pathlib import Path

RD = Path("/Users/ravindra/projects/orca-fleet-ship-mdtoc-20261013/docs/runs/2026-10-13-ship-it-mdtoc")
REL = "docs/runs/2026-10-13-ship-it-mdtoc"
HEAD = "046d1f8d0ff63b7193bc06e0c373ba60d9e06849"

m = json.loads((RD / "manifest-integrated.json").read_text())
m["claim"] = ("Integrated: ravidsrk/mdtoc built from frozen SPEC.md to BUILT on fleet/ship-mdtoc-20261013 "
              "@046d1f8d (F0+S1+S2+S3+S4+ S5 seam fixes after integrated FAIL; re-review PASS)")
m["head_sha"] = HEAD
for c in m["commands"]:
    a = c.get("artifact") or ""
    if a.startswith("/"):
        c["artifact"] = REL + a[len(str(RD)):]
m["intent"] = {
    "goal": "Prove the assembled product meets the whole frozen spec at one bound SHA (the run's BUILT terminal)",
    "ruled_out": "Release/packaging (no-gh lane ends at BUILT); the recorded known limits (inline-code markers, setext, reference links, non-atomic writes)",
    "why": "Slice verdicts prove parts; only an integrated pass over the merge product catches seam defects — it caught CR-only/BOM breakage the slices missed",
}
m["negative_control"] = {
    "tool": "hand",
    "result": ("hand mutant (disable _outside_fences fence-awareness in mdtoc/toc.py at 046d1f8d) turned the "
               "suite RED: 19 failures + 1 error — mutant killed"),
    "artifact": f"{REL}/prove/int-nc-fixed.txt",
    "command": "python3 -m unittest discover",
    "criterion_ids": ["AC-3"],
}
m["review"] = {"artifact": f"{REL}/reviews/integrated-record.md", "reviewed_sha": HEAD}
m["reviewer_mode"] = "same-vendor-fresh"

pin = [
    "prove/int-tests.txt", "prove/int-battery.txt", "prove/int-prove.txt", "prove/int-nc.txt", "prove/int-nc-run.txt",
    "prove/int-tests-fixed.txt", "prove/int-battery-fixed.txt", "prove/int-prove-fixed.txt",
    "prove/int-nc-fixed.txt", "prove/int-nc-run-fixed.txt",
    "prove/integrated-probe.py",
    "reviews/integrated.md", "reviews/integrated-r2.md", "reviews/integrated-record.md",
    "deliveries/int-review-done.json", "deliveries/int-rereview-done.json",
    "prove/int-verifier.txt", "prove/int-verifier-rerecord.txt",
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
(RD / "manifest-integrated.json").write_text(json.dumps(m, indent=2) + "\n")
print("manifest-integrated.json finalized:", len(m["commands"]), "commands,", len(m["artifacts"]), "artifacts, head", HEAD[:8])
