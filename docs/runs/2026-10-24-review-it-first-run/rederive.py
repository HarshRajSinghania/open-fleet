"""Re-derive the #596 binding contract's criteria from the committed run directory (stdlib only)."""
import hashlib, json, re, sys
from pathlib import Path

R = Path(sys.argv[1])
CATALOG = "b96d47e3354564e1593d34182a817ae04e54545d"
STEPS = ["prereqs", "target", "preflight", "create", "dispatch", "guard", "delivery", "result", "evidence", "verify", "release"]
ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"{'PASS' if cond else 'FAIL'} {label}{(': ' + detail) if detail else ''}")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


for rel in ("mac-ro/receipt.json", "mac-rw/receipt.json", "clean-host/receipt-ro.json", "clean-host/receipt-rw.json"):
    r = json.loads((R / rel).read_text())
    f = r["facts"]
    check(f"LR-1 {rel} GO live at the catalog commit, clean",
          r["verdict"] == "GO" and r["tier"] == "live-unreviewed" and r["route"]["worker"] == "live"
          and r["host"]["catalog_commit"] == CATALOG and r["host"]["catalog_dirty"] is False,
          f"{r['route']['provider']}/{r['route']['backend']} PROFILE={r['route']['profile']} {f['harness']['version']}")
    check(f"LR-1 {rel} every step ok, verify OK",
          [s["step"] for s in r["steps"]] == STEPS and all(s["ok"] for s in r["steps"])
          and f["verify"]["rc"] == 0 and any("verify: OK" in x for x in f["verify"]["out"]),
          f"elapsed {r['elapsed_s']} s, usage {f.get('harness_usage')}")

wrapper = R / "isolation" / "claude-wrapper.py"
check("LR-2 isolation wrapper retained", wrapper.is_file(), f"sha256 {sha(wrapper)}")
for prof in ("ro", "rw"):
    d = R / f"mac-{prof}"
    r = json.loads((d / "receipt.json").read_text())
    check(f"LR-2 mac-{prof} ran the wrapper", r["facts"]["harness"]["path"].endswith("/of-live/bin/claude"))
    events = [json.loads(ln) for ln in (d / "transcript.jsonl").read_text().splitlines() if ln.strip()]
    init = next(e for e in events if e.get("type") == "system" and e.get("subtype") == "init")
    res = next(e for e in events if e.get("type") == "result")
    check(f"LR-2 mac-{prof} transcript names model and cost",
          init.get("model") == "claude-opus-5-5" and init.get("claude_code_version") == "2.1.304"
          and isinstance(res.get("total_cost_usd"), float),
          f"model {init.get('model')}, permissionMode {init.get('permissionMode')}, turns {res.get('num_turns')}, "
          f"USD {res.get('total_cost_usd')}, tools without Write/Edit: {not {'Write', 'Edit'} & set(init.get('tools') or [])}")
    m = json.loads((d / "manifest.json").read_text())
    art = {a["path"].rsplit("/", 1)[-1]: a["sha256"] for a in m["artifacts"]}
    contract_digest = "sha256:" + sha(d / "contract.md")
    check(f"LR-2 mac-{prof} retained report and contract match its own manifest",
          art.get("report.md") == sha(d / "report.md") and m["contract"]["digest"] == contract_digest)
    head = re.match(r"FIRST-RUN-REPORT (FR-NONCE:[0-9a-f]{16}) ([0-9a-f]{40})", (d / "report.md").read_text())
    receipt_line = (d / "change.diff").read_text().splitlines()[-1]
    check(f"LR-2 mac-{prof} report opens with the frozen header and quotes the read receipt",
          bool(head) and head.group(1) == r["facts"]["nonce"] and head.group(2) == r["facts"]["reviewed"]["head_sha"]
          and receipt_line in (d / "report.md").read_text())

for name in ("inner.sh", "user.sh", "clean-host-596.sh"):
    text = (R / "clean-host" / name).read_text()
    creds = set(re.findall(r"[A-Z_]*(?:TOKEN|KEY|SECRET|PASSWORD)[A-Z_]*", text))
    check(f"LR-3 clean-host/{name} names only CLAUDE_CODE_OAUTH_TOKEN", creds <= {"CLAUDE_CODE_OAUTH_TOKEN"}, str(sorted(creds)))
log = (R / "clean-host" / "clean-host.log").read_text()
check("LR-3 clean host: fresh ubuntu:24.04, installer 2.1.304, fresh clone at the catalog commit, both GO",
      "Ubuntu 24.04" in log and "2.1.304 (Claude Code)" in log and f"catalog {CATALOG}" in log
      and log.count("verdict=GO") == 2, log.strip().splitlines()[-1])

ro1 = json.loads((R / "first-attempt" / "ro.receipt.json").read_text())
rw1 = json.loads((R / "first-attempt" / "rw.receipt.json").read_text())
check("LR-4 first attempt: ro GO, rw NO-GO at result on the assignment defect",
      ro1["verdict"] == "GO" and rw1["verdict"] == "NO-GO" and rw1["failure"]["step"] == "result"
      and "report does not open with" in rw1["failure"]["detail"], rw1["failure"]["detail"][:120])

o = R / "orca-ro-attempt"
wait = json.loads((o / "terminal-wait.json").read_text())["result"]["wait"]
err = (o / "spawn.stderr").read_text()
check("LR-5 Orca attempt: launched the current row, refused before any inject",
      (o / "launch.txt").read_text().strip() == "LAUNCH=claude --permission-mode plan --disallowedTools=Edit,Write,MultiEdit,NotebookEdit"
      and wait.get("blockedReason") == "agent-trust-workspace" and wait.get("satisfied") is False
      and "step=wait-tui-idle" in err and "Yes, I trust this folder" in (o / "worker-screen.txt").read_text(),
      f"orca {(o / 'orca-version.txt').read_text().strip()}, claude {(o / 'claude-version.txt').read_text().strip()}")
print("REDERIVE=" + ("OK" if ok else "FAILED"))
sys.exit(0 if ok else 1)
