#!/usr/bin/env python3
"""Re-derive every figure the #605 live-run report states from the retained bytes alone.

The report (docs/runs/2026-10-24-hint-replay-605-live.md) is prose; this is the check behind it. It
reads only this directory and the corpus the run used, recomputes the per-call charges, the totals,
the per-arm outcome, cost and turns, and what each arm's packet carried, and compares them with
what results.json and the spend ledger say. Any disagreement is a FAIL and exit 1. Read-only and
stdlib-only; it calls no model and runs no worker.

    python3 docs/runs/2026-10-24-hint-replay-605-live/rederive.py
"""
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
ARMS = ("off", "unchecked", "checked")
EXPECTED_STDERR = ("⚠ Permission mode forced to default — CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is set "
                   "(allowed_non_write_users hardening). Declare allowedTools explicitly, or set "
                   "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0 to opt out.\n")
FAILURES = []


def check(what, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + what + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append(what)


def main():
    results = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    ledger = [json.loads(ln) for ln in (HERE / "results.spend.jsonl").read_text(encoding="utf-8").splitlines()
              if ln.strip()]
    corpus_bytes = (ROOT / "tests" / "fixtures" / "hint-replay.json").read_bytes()
    corpus = json.loads(corpus_bytes)
    rows, cost = results["results"], results["cost"]
    run_dir = HERE / "results.calls" / results["run_id"]

    # The run as declared.
    check("schema hint-replay-live/v2, tier live", (results["schema"], results["tier"]) == ("hint-replay-live/v2", "live"))
    check("complete, not stopped", results["complete"] is True and results["stopped"] is None)
    check("18 planned calls, 3 attempts, 18 rows", (results["planned_runs"], results["attempts"], len(rows)) == (18, 3, 18))
    check("corpus is tests/fixtures/hint-replay.json as committed here",
          hashlib.sha256(corpus_bytes).hexdigest() == results["corpus"]["sha256"])
    check("cap USD 40, reservation USD 2, limit --max-budget-usd 1.60 on every call",
          (cost["cap_usd"], cost["reserve_per_call_usd"], cost["limit_flag"], cost["limit_usd"]) == (40.0, 2.0, "--max-budget-usd", 1.6)
          and results["agent_cmd"][-2:] == ["--max-budget-usd", "1.60"])

    # The ledger: every call started at its reservation, settled at its measured cost, none open.
    starts = {r["cell"]: r for r in ledger if r["event"] == "start"}
    settles = {r["cell"]: r for r in ledger if r["event"] == "settle"}
    check("ledger: one run, 18 starts at USD 2, 18 settles, no open call",
          {r["run"] for r in ledger} == {results["run_id"]} and len(starts) == len(settles) == 18
          and set(starts) == set(settles) and all(r["reserve_usd"] == 2.0 for r in starts.values()))

    pitfalls = {s["id"]: re.compile(s["live_task"]["pitfall"]) for s in corpus["scenarios"] if s.get("live_task")}
    per_arm = {arm: {"runs": 0, "passed": 0, "repeated_failures": 0, "cost": [], "turns": [], "ms": [], "out_tokens": []}
               for arm in ARMS}
    charged_total = 0.0
    for row in rows:
        call, arm = row["call"], row["arm"]
        d = run_dir / call
        agent = json.loads((d / "agent.stdout").read_text(encoding="utf-8"))
        packet = (d / "packet.md").read_text(encoding="utf-8")
        oracle = (d / "oracle.txt").read_text(encoding="utf-8")
        measured = round(agent["total_cost_usd"], 6)
        settle = settles[call]
        check(f"{call}: charge re-derives (stdout {measured} = results {row['charged_usd']} = ledger {settle['charged_usd']})",
              measured == row["cost_usd"] == row["charged_usd"] == settle["charged_usd"] == settle["measured_usd"]
              and row["measured"] and row["settled"] and not settle["killed"] and not row["orphans"])
        check(f"{call}: worker succeeded on claude-opus-5-5, exit 0, no permission denial",
              agent["subtype"] == "success" and agent["is_error"] is False and row["agent_exit"] == 0
              and list(agent["modelUsage"]) == ["claude-opus-5-5"] == row["models"]
              and not agent.get("permission_denials"))
        repeated = row["oracle_exit"] != 0 and bool(pitfalls[row["scenario"]].search(oracle))
        check(f"{call}: oracle exit {row['oracle_exit']}, repeated failure {row['repeated_failure']} re-derives",
              repeated == row["repeated_failure"] and (row["oracle_exit"] == 0) == oracle.rstrip().endswith("OK"))
        check(f"{call}: stderr is the permission-mode notice only",
              (d / "agent.stderr").read_text(encoding="utf-8") == EXPECTED_STDERR)
        hinted = "EPISODIC_HINT:" in packet
        if arm == "off":
            shape = not hinted
        elif arm == "unchecked":
            shape = hinted and "mode=historical" in packet and "SHOWN=1" in packet
        elif row["scenario"] == "stale-advice-trap":
            shape = hinted and "mode=current" in packet and "STALE=1" in packet and "SHOWN=0" in packet
        else:
            shape = hinted and "mode=current" in packet and "CURRENT=1" in packet and "SHOWN=1" in packet
        check(f"{call}: packet carries the {arm} arm's hint selection", shape)
        acc = per_arm[arm]
        acc["runs"] += 1
        acc["passed"] += row["oracle_exit"] == 0
        acc["repeated_failures"] += row["repeated_failure"]
        acc["cost"].append(measured)
        acc["turns"].append(agent["num_turns"])
        acc["ms"].append(agent["duration_ms"])
        acc["out_tokens"].append(agent["usage"]["output_tokens"])
        charged_total += settle["charged_usd"]

    check("total re-derives: sum of settled charges = spent = counted against the cap",
          round(charged_total, 6) == cost["spent_usd"] == cost["counted_against_cap_usd"] and cost["prior_spent_usd"] == 0.0)
    check("spend within the cap", cost["spent_usd"] <= cost["cap_usd"])
    check("18 measured, 0 unmeasured", len(cost["measured_calls"]) == 18 and cost["unmeasured_calls"] == [])
    for arm in ARMS:
        acc = per_arm[arm]
        check(f"arm {arm}: runs/passed/repeated failures re-derive",
              {k: acc[k] for k in ("runs", "passed", "repeated_failures")} == results["arms"][arm])

    print()
    print("| arm | runs | passed | repeated failures | cost USD (sum) | cost USD (mean) | turns | mean turns | mean s | mean output tokens |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for arm in ARMS:
        acc = per_arm[arm]
        print(f"| {arm} | {acc['runs']} | {acc['passed']} | {acc['repeated_failures']} | {sum(acc['cost']):.6f} | "
              f"{statistics.mean(acc['cost']):.6f} | {', '.join(map(str, acc['turns']))} | "
              f"{statistics.mean(acc['turns']):.2f} | {statistics.mean(acc['ms']) / 1000:.1f} | "
              f"{statistics.mean(acc['out_tokens']):.0f} |")
    print(f"\ntotal USD {round(charged_total, 6)} of a USD {cost['cap_usd']} cap; {len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
