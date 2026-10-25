#!/usr/bin/env python3
"""Re-derive every figure #604 version 2's run report states, from this directory and the
repository alone. Run from the repository root:

    python3 docs/runs/2026-10-25-wip-curve-604-live/rederive.py

Each check prints `ok` or `FAIL` with its criterion (contract.json); exit 0 only when none fails.

One substitution, stated because it bounds what this proves: the report's binding re-runs each
landed task's oracle, which is worker-written code, and outside the container harness that re-run
refuses. Here `rerun_oracle` returns a pass; before it is called, `bind_outcomes` still requires a
bound, passing oracle transcript at that head. The real re-runs are the harness's `verify` launch,
whose receipt and log are in receipts/.
"""
import glob
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMMIT = "bacb5f8dd81df7181790738f7901bbb53f2fa6ec"
PREREG = ROOT / "docs" / "experiments" / "wip-curve-prereg-v2.json"
PREREG_SHA = "c30c2c15890d565af64c126dd456de4a09310c757ad33975a310e170412e1aa8"
MODEL, HARNESS = "claude-sonnet-5-5", "2.1.304 (Claude Code)"
AUTHORISED = Decimal("150")
ODD_RUN, ODD_MODEL = "wip2-b6r2-rep2", "claude-sonnet-5"  # the one broker call off the pin (WC-4)
RUNNER_INPUTS = ("scripts/wip_curve.py", "scripts/_ablation_run.py", "runtime/scripts/events.py",
                 "docs/experiments/wip-curve-prereg-v2.json", "docs/experiments/wip-curve-taskset.json")
failures = []


def check(criterion, ok, what):
    print(f"{'ok  ' if ok else 'FAIL'} {criterion} {what}")
    if not ok:
        failures.append(f"{criterion} {what}")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_bytes(rev, path):
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{path}"], capture_output=True,
                          check=True).stdout


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


spec = importlib.util.spec_from_file_location("wip_curve_rederive", ROOT / "scripts" / "wip_curve.py")
wip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wip)

# ---------------------------------------------------------------- WC-1: the registration and the fixed point
check("WC-1", sha256(PREREG) == PREREG_SHA, f"version 2's registration hashes to {PREREG_SHA[:12]}")
for rel in RUNNER_INPUTS:
    check("WC-1", (ROOT / rel).read_bytes() == git_bytes(COMMIT, rel),
          f"{rel} is byte-identical to the run commit {COMMIT[:10]}'s")
prereg, taskset, _path, _sha, taskset_path = wip.load_prereg(PREREG)
taskset_sha = sha256(taskset_path)
schedule = wip.schedule(prereg, taskset)
runs = {}
for path in sorted(glob.glob(str(HERE / "experiment" / "runs" / "*" / "run.json"))):
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    runs[rec["run_id"]] = rec
check("WC-1", sorted(runs) == sorted(e["run_id"] for e in schedule),
      f"the {len(runs)} retained runs are exactly the {len(schedule)} scheduled wip2-* runs")
for rid, rec in sorted(runs.items()):
    fields = (rec["prereg"]["sha256"], rec["taskset"]["sha256"], rec["tier"], rec["worker"],
              rec["model_pin"], rec["harness"]["version"], rec["status"], rec.get("attempt", 1),
              rec["timeout_scale"])
    want = (PREREG_SHA, taskset_sha, "live-unreviewed", "live", MODEL, HARNESS, "complete", 1, 1.0)
    check("WC-1", fields == want, f"{rid}: registration, live tier, {MODEL}, {HARNESS}, complete, attempt 1")
usage_models = set()
for path in glob.glob(str(HERE / "experiment" / "runs" / "*" / "streams" / "*.jsonl")):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "result":
            usage_models |= set(obj.get("modelUsage") or {})
check("WC-1", usage_models == {MODEL}, f"every model the runs' usage records observe is the pin ({sorted(usage_models)})")
clocks = {rec["clock"] for rec in runs.values()}
check("WC-1", len(clocks) == 1, f"one machine label across all 12 runs ({next(iter(clocks))})")

# ---------------------------------------------------------------- WC-2: the launches
receipts = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sorted(glob.glob(str(HERE / "receipts" / "*.json")))]
launches = [r for r in receipts if "run" in r["arm_args"]]
check("WC-2", len(launches) == 12, f"{len(launches)} run launches, one per scheduled run")
want_args = ["--prereg", "/repo/docs/experiments/wip-curve-prereg-v2.json", "run", "--results",
             "/results/experiment", "--workdir", "/results/sandboxes", "--worker", "live", "--agent",
             "claude", "--model", MODEL, "--cost-cap-usd", "150", "--reservation-usd", "2.00", "--next", "1"]
order = {e["run_id"]: e["position"] for e in schedule}
seen = []
for r in launches:
    log = (HERE / "receipts" / Path(r["log"]).name).read_text(encoding="utf-8", errors="replace")
    line = re.search(r"WIP_RUN=(\S+) STATUS=(\S+) TIER=(\S+)", log)
    seen.append((r["started_at"], line and line.group(1)))
    check("WC-2", r["commit"] == COMMIT and r["arm"] == "wip_curve" and r["arm_args"] == want_args
          and r["per_call_usd"] == 1.6 and r["image"]["from_committed_dockerfile"] is True
          and r["destroyed"]["verified"] is True and r["token_redactions"] == 0 and r["exit_status"] == 0
          and not r["timed_out"] and line and line.group(2) == "complete" and line.group(3) == "live-unreviewed",
          f"{Path(r['log']).stem}: {line and line.group(1)} complete at {COMMIT[:10]}, the documented "
          "command, per-call USD 1.60, destroyed, no token in the output")
started = [rid for _at, rid in sorted(seen)]
check("WC-2", started == sorted(started, key=lambda rid: order.get(rid, 99)),
      "the launches ran the schedule in its registered order")
tail = [r for r in receipts if "run" not in r["arm_args"]]
report_log = next((HERE / "receipts" / Path(r["log"]).name).read_text(encoding="utf-8")
                  for r in tail if "report" in r["arm_args"])
verify_log = next((HERE / "receipts" / Path(r["log"]).name).read_text(encoding="utf-8")
                  for r in tail if "verify" in r["arm_args"])
check("WC-2", all(r["commit"] == COMMIT and r["destroyed"]["verified"] for r in tail) and len(tail) == 2,
      "the report and verify launches ran at the same commit, inside the harness, destroyed")
check("WC-2", "report for 12 run(s) (12 compliant)" in report_log and "recommendation keep" in report_log,
      "the in-harness report: 12 runs, 12 compliant, recommendation keep")
check("WC-2", "the report recomputes from 12 run(s)' bound sources" in verify_log
      and "(0 binding problem(s)" in verify_log,
      "the in-harness verify: recomputed from bound sources, every outcome re-checked against git, 0 binding problems")

# ---------------------------------------------------------------- WC-3: the report re-derives
substituted = []


def substitute(_repo, head, task, _taskset, _what):
    substituted.append((task["id"], head))
    return {"exit": 0, "contained": True}


wip.rerun_oracle = substitute
derived = wip.build_report(HERE / "experiment", PREREG, basis="all")
kept = json.loads((HERE / "report" / "report.json").read_text(encoding="utf-8"))
check("WC-3", derived == kept, f"report.json re-derives from the retained runs, field for field "
      f"({len(substituted)} oracle re-runs substituted, as the docstring states)")
md = (HERE / "report" / "report.md").read_text(encoding="utf-8")
check("WC-3", wip.render_markdown(derived).rstrip("\n") == md.rstrip("\n"),
      "report.md re-renders from the re-derived report (report.json is written with sorted keys)")
check("WC-3", kept["recommendation"]["status"] == "keep" and len(kept["compliant_runs"]) == 12,
      "the decision rule's recommendation is keep, from 12 compliant runs")
minus = [r for r in derived["runs"] if r["compliant"] and r["run_id"] != ODD_RUN]
blocks = {c["id"]: wip.condition_block(c, [r for r in minus if r["condition"] == c["id"]]) for c in prereg["conditions"]}
sensitivity = wip.recommend(prereg, blocks, minus)
b6r2 = blocks["b6r2"]["throughput_per_h"]
check("WC-3", sensitivity["status"] == "keep",
      f"excluding {ODD_RUN}, the decision rule still yields keep (b6r2 over {b6r2['n']} runs: "
      f"{b6r2['mean']}/h [{b6r2['ci95'][0]}, {b6r2['ci95'][1]}] against b3r1's upper bound "
      f"{blocks['b3r1']['throughput_per_h']['ci95'][1]})")
for row in kept["conditions"]:
    print(f"     {row['condition']}: throughput {row['throughput_per_h']['mean']}/h, "
          f"rework {row['rework']['k']}/{row['rework']['n']}, conflicts {row['conflicts']['total']}")

# ---------------------------------------------------------------- WC-4: spend on both ledgers
broker_total = Decimal(0)
for r in sorted(launches + tail, key=lambda r: r["started_at"]):
    events = jsonl(HERE / "receipts" / (Path(r["log"]).stem + ".broker") / "spend.jsonl")
    starts = {e["call"] for e in events if e["event"] == "start"}
    settles = [e for e in events if e["event"] == "settle"]
    # each settle line carries the call's cost_usd and the ledger's running settled_usd
    settled = sum((Decimal(str(e["cost_usd"])) for e in settles), Decimal(0))
    final = Decimal(str(r["broker"]["spend"]["settled_usd"] or 0))
    ok = ({e["call"] for e in settles} == starts and all(e["status"] == 200 for e in settles)
          and abs(settled - final) <= Decimal("0.000002"))  # the running total is rounded to 1e-6
    check("WC-4", ok and r["broker"]["spend"]["unsettled_reserved_usd"] == 0,
          f"{Path(r['log']).stem}: {len(settles)} calls, every one settled 200, USD {settled} settled, "
          f"{sum(1 for e in events if e['event'] == 'refuse')} refused, none left open")
    broker_total += settled
off_pin = []
for r in launches:
    log = (HERE / "receipts" / Path(r["log"]).name).read_text(encoding="utf-8", errors="replace")
    rid = re.search(r"WIP_RUN=(\S+)", log).group(1)
    events = jsonl(HERE / "receipts" / (Path(r["log"]).stem + ".broker") / "spend.jsonl")
    for e in events:
        if e["event"] == "start" and e["model"] != MODEL:
            settle = next(x for x in events if x["event"] == "settle" and x["call"] == e["call"])
            off_pin.append((rid, e["call"], e["model"], {k: v for k, v in settle["usage"].items()
                                                         if isinstance(v, int) and v}))
calls_total = sum(sum(1 for e in jsonl(HERE / "receipts" / (Path(r["log"]).stem + ".broker") / "spend.jsonl")
                      if e["event"] == "start") for r in launches)
check("WC-4", [(rid, model) for rid, _call, model, _u in off_pin] == [(ODD_RUN, ODD_MODEL)],
      f"every broker call is on the pin but one of {calls_total}: {off_pin}")
v1 = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sorted(glob.glob(str(HERE / "version-1" / "receipts" / "*.json")))]
v1_total = sum((Decimal(str((r["broker"]["spend"] or {}).get("settled_usd") or 0)) for r in v1), Decimal(0))
check("WC-4", broker_total + v1_total <= AUTHORISED,
      f"#604's broker spend: version 2 USD {broker_total}, version 1 USD {v1_total}, within the USD 150 authorised")
charged = wip.Budget(HERE / "experiment").calls()  # the append-only ledger, folded by the runner itself
arm_total = sum((Decimal(e["usd"]) for e in charged.values() if e.get("state") == "charged"), Decimal(0))
check("WC-4", all(e.get("state") in ("charged", "released", "run") for e in charged.values()),
      f"the arm's ledger: every call charged or released, none left held ({len(charged)} calls)")
run_cost = sum((Decimal(rec["cost"]["observed_usd"]) for rec in runs.values()), Decimal(0))
check("WC-4", arm_total == run_cost and arm_total <= Decimal("150"),
      f"the arm's charges, USD {arm_total}, equal the runs' observed cost and are within its USD 150 cap")
print(f"     broker settled USD {broker_total} (every API call, at the API's prices); the arm charged "
      f"USD {arm_total} (each call's own total_cost_usd); difference USD {broker_total - arm_total}")

# ---------------------------------------------------------------- WC-5: version 1, superseded
v1_runs = {Path(p).parent.name: Path(p).parent for p in glob.glob(str(HERE / "version-1" / "experiment" / "runs" / "*" / "run.json"))}
check("WC-5", sorted(v1_runs) == ["wip1-b1r1-rep1", "wip1-b3r1-rep1"], "version 1 retained its two live runs")
b1 = json.loads((v1_runs["wip1-b1r1-rep1"] / "run.json").read_text(encoding="utf-8"))
check("WC-5", b1["status"] == "complete", "wip1-b1r1-rep1 completed")
streams = sorted((v1_runs["wip1-b3r1-rep1"] / "streams").glob("*.jsonl"))
check("WC-5", len(streams) == 18 and all(wip.credential_rejected(s) for s in streams),
      "wip1-b3r1-rep1: all 18 of its model calls are the refused-credential shape")
b3 = json.loads((v1_runs["wip1-b3r1-rep1"] / "run.json").read_text(encoding="utf-8"))
check("WC-5", wip.infrastructure_failure(v1_runs["wip1-b3r1-rep1"], b3["status"])
      == "the API refused all 18 of its model calls for the credential",
      "version 2's rule reads it from its bound record as an infrastructure failure")
for r in v1:
    events = jsonl(HERE / "version-1" / "receipts" / (Path(r["log"]).stem + ".broker") / "spend.jsonl")
    statuses = sorted({e["status"] for e in events if e["event"] == "settle"})
    print(f"     version 1 {Path(r['log']).stem}: {sum(1 for e in events if e['event'] == 'settle')} settled "
          f"{statuses}, {sum(1 for e in events if e['event'] == 'refuse')} refused, interrupted={r.get('interrupted')}")

# ---------------------------------------------------------------- WC-6: retention and hygiene
files = [p for p in HERE.rglob("*") if p.is_file() and p.resolve() != Path(__file__).resolve()]
shape = ("sk-" + "ant-").encode()  # built, so this script never matches its own scan
leaks = [p for p in files if shape in p.read_bytes()]
check("WC-6", not leaks, f"no retained file holds a credential shape ({len(files)} files scanned)")
check("WC-6", all(r["token"]["passed"].startswith("a read-only file mount in the broker's container alone") for r in launches + tail),
      "every launch passed the token only as a read-only mount into the broker's container")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
