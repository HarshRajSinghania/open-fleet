#!/usr/bin/env python3
"""Re-derive every figure the #606 live paired-ablation report states from the retained bytes alone.

The report (docs/runs/2026-10-25-ablation-606-live.md) is prose; this is the check behind it. It
reads this directory and, from the checkout it runs in, the registration, the variant generator,
the paired runner's analysis, the #602 replay grader, events.py, the broker's price list and the
image's Dockerfile. It re-derives the registration's currency, both arms' payloads, the planned
design and every cell's task text, each cell's usage, deferred reads, trajectory grade and
behavioral workspace state, both spend ledgers and the caps at every call, the per-mission
analysis and decision, and the record of the superseded launch, and compares them with what
results.json, report.md, the ledgers and the receipts say. Any disagreement is a FAIL and exit 1.

It runs the run commit's own code, not the checkout's: the runner, its analysis, the oracles, the
variant generator, events.py, the broker's price list and the registration are extracted from
c220067e9c with `git archive` into a temporary tree and loaded from there. The paired runner changed
after the run (#688), and a later checkout may change more; neither can change what this checks. It calls no model and runs no agent. The grader's verdicts are not re-run: an LLM call
cannot be re-derived, so each behavioral cell is checked for the consistency of its recorded
assertion rows instead. Stdlib only; scratch work goes to temporary directories.

    python3 docs/runs/2026-10-25-ablation-606-live/rederive.py [RUN_DIR]
"""
import hashlib
import io
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
RUN_COMMIT = "c220067e9cbffc4f34d6363a92153e45402bdfe4"
MODEL = "claude-sonnet-5-5"
HARNESS_VERSION = "2.1.304 (Claude Code)"
RECEIPT = "receipts/20261025T105506Z-ablation-d50b399f"
FIRST = "superseded"
FIRST_RECEIPT = f"{FIRST}/receipts/20261025T105119Z-ablation-3ee7839c"
DRY_RECEIPT = "dry-run/receipts/20261025T100814Z-ablation-591867d0"
DRY_COMMIT = "6f02e410dab2219966e297590f48592c8764c831"  # one merge before RUN_COMMIT (#684)
HARNESS_CMD = ("python3 /repo/scripts/trajectory_harness.py claude -p --model claude-sonnet-5-5 --verbose "
               "--output-format stream-json --permission-mode acceptEdits")
GRADER_CMD = "claude -p --model claude-sonnet-5-5 --output-format json"
ARM_ARGS = ["run", "--tier", "live", "--cost-cap-usd", "740", "--model", MODEL, "--harness-version",
            HARNESS_VERSION, "--harness-cmd", HARNESS_CMD, "--grader-cmd", GRADER_CMD, "--out", "/results/out"]
FIRST_ARM_ARGS = ["run", "--tier", "live", "--cost-cap-usd", "740", "--model", MODEL, "--harness-version",
                  HARNESS_VERSION, "--harness-cmd",
                  "python3 /repo/scripts/trajectory_harness.py claude -p --verbose --output-format stream-json "
                  "--permission-mode acceptEdits", "--out", "/results/out"]
# What the re-derivation needs of the run commit's tree: the code, its data, and the catalog the
# variant generator and the oracles read.
CODE_PATHS = ("scripts", "runtime", "evals", "skills", "playbooks", "docs/experiments")
BINDING = {"contract.json", "rederive.py", "rederive.txt", "manifest.json", "dispatch-record.json",
           "dispatch-pubkey.hex"}
FAILURES = []


def check(what, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + what + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append(what)


def run_tree():
    """The run commit's tree (CODE_PATHS and its root documents), extracted into a temporary
    directory: every module this script loads, and every file they read, is the run's own."""
    top = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "--name-only", RUN_COMMIT], capture_output=True,
                         text=True, check=True).stdout.split()
    paths = list(CODE_PATHS) + [n for n in top if n.endswith(".md")]
    tar = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", RUN_COMMIT, "--", *paths],
                         capture_output=True, check=True).stdout
    code = Path(tempfile.mkdtemp(prefix="of-rederive-606-code-"))
    with tarfile.open(fileobj=io.BytesIO(tar)) as archive:
        archive.extractall(code, filter="data")
    return code


def load(code, name, rel):
    spec = importlib.util.spec_from_file_location(name, code / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def jsonl(path):
    return [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


def git_show(rel):
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{RUN_COMMIT}:{rel}"], capture_output=True,
                          check=True).stdout


def list_price(usage, prices, geo):
    split = usage["cache_creation"]
    p_in, p_out, p_read = prices
    return (usage["input_tokens"] * p_in + split["ephemeral_5m_input_tokens"] * p_in * 1.25
            + split["ephemeral_1h_input_tokens"] * p_in * 2.0 + usage["cache_read_input_tokens"] * p_read
            + usage["output_tokens"] * p_out) * geo[usage["inference_geo"]] / 1e6


def stream_lines(path):
    out = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(ln)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def main(here):
    code = run_tree()
    try:
        return checks(here, code)
    finally:
        shutil.rmtree(code, ignore_errors=True)


def checks(here, code):
    runner = load(code, "of_rederive_runner", "scripts/_ablation_run.py")
    api = load(code, "of_rederive_ablation", "scripts/ablation.py")
    ev_mod = runner.eval_mod()
    broker = load(code, "of_rederive_broker", "scripts/live_broker.py")
    vf = load(code, "of_rederive_verify", "runtime/scripts/verify.py")
    prereg = api.load_prereg(code / "docs/experiments/ablation-prereg.json")

    results = json.loads((here / "results.json").read_text(encoding="utf-8"))
    report_md = (here / "report.md").read_text(encoding="utf-8")
    ledger = jsonl(here / "spend.jsonl")
    receipt = json.loads((here / f"{RECEIPT}.json").read_text(encoding="utf-8"))
    log = (here / f"{RECEIPT}.log").read_text(encoding="utf-8")
    bledger = jsonl(here / f"{RECEIPT}.broker" / "spend.jsonl")
    omitted = {}
    for ln in (here / "omitted.sha256").read_text(encoding="utf-8").splitlines():
        digest_hex, rel = ln.split("  ", 1)
        omitted[rel] = digest_hex
    cells = results["cells"]

    # AB-1: the fixed point. The code this script runs is the run commit's own.
    loaded = {m.__name__: Path(m.__file__).resolve() for m in (runner, api, broker, vf, ev_mod, runner.events_mod())}
    check("the re-derivation runs the run commit's own code: the runner, the analysis, eval.py's oracles, "
          "the generator, events.py, the broker and verify.py all load from c220067e9c's tree",
          all(path.is_relative_to(code.resolve()) for path in loaded.values())
          and (code / "scripts/_ablation_run.py").read_bytes() == git_show("scripts/_ablation_run.py"))
    check("receipt: schema, commit, arm and the arm's arguments as recorded",
          receipt["schema"] == "open-fleet.live-container-receipt/2" and receipt["commit"] == RUN_COMMIT
          and receipt["arm"] == "ablation" and receipt["arm_args"] == ARM_ARGS)
    dockerfile = sha(git_show("scripts/live_container.Dockerfile"))
    image = receipt["image"]
    check("container log: the run's failure list, then its results line", log.endswith(
        "\nresults: /results/out/results.json\n"))
    check("receipt: image built from the committed Dockerfile, Claude Code 2.1.304; broker cap USD 750",
          image["from_committed_dockerfile"] is True
          and image["dockerfile_sha256"] == image["committed_dockerfile_sha256"] == dockerfile
          and image["labels"]["org.open-fleet.claude-code"] == "2.1.304"
          and receipt["broker"]["cap_usd"] == 750.0)
    reg = results["prereg"]
    check("results: schema, live tier, the live-unreviewed evidence line",
          results["schema"] == runner.RESULTS_SCHEMA and results["tier"] == "live"
          and results["evidence"].startswith("live-unreviewed"))
    check("registration: the run commit's registration re-hashes to the one the run used, every mission "
          "current at the run and in that tree",
          reg["sha256"] == api.prereg_sha256(prereg) and reg["version"] == prereg["version"]
          and set(reg["registration"].values()) == {"current"}
          and set(api.registration_status(prereg).values()) == {"current"})
    check(f"model {MODEL} and harness {HARNESS_VERSION} recorded; both commands carry --model {MODEL}",
          results["model"] == MODEL and results["harness_version"] == HARNESS_VERSION
          and "--model" in results["agent_cmd"] and results["agent_cmd"][results["agent_cmd"].index("--model") + 1] == MODEL
          and f"--model {MODEL}" in results["grader_cmd"])
    plan = results["plan"]
    missions = [row["mission"] for row in prereg["mission_mix"]]
    tasks = runner.registered_tasks(prereg)
    check("plan: the registered design, 4 missions x 9 tasks x 5 repeats, 180 pairs, 360 cells",
          plan == {"missions": missions, "tasks": tasks, "repeats": prereg["repeats"], "pairs": 180,
                   "cells_planned": 360} and prereg["repeats"] == 5)
    check("results: complete, not stopped, 360 cells", results["complete"] is True and results["stopped"] is None
          and len(cells) == 360)
    report = runner.summarize(results, prereg)
    check("report.md re-renders byte for byte from results.json through the runner's own analysis",
          report_md == runner.render_markdown(results, report))

    # AB-1: both arms' payloads, regenerated at this checkout.
    payloads, cues = {}, {}
    with tempfile.TemporaryDirectory(prefix="of-rederive-606-") as tmp:
        for mission in missions:
            rec = api.generate(mission, prereg, Path(tmp) / "variants")
            got = results["variants"][mission]
            pay = {arm: (Path(tmp) / "variants" / mission / f"{arm}.payload.md").read_text(encoding="utf-8")
                   for arm in runner.ARMS}
            red_path = Path(tmp) / "variants" / mission / "reduced" / "skills" / mission / "SKILL.md"
            red_text = red_path.read_text(encoding="utf-8")
            # Listed by sha256, not copied: the baseline payloads quote runtime docs whose examples
            # match verify.py's credential floor.
            listed = {arm: omitted.get(f"variants/{mission}/{arm}.payload.md") for arm in runner.ARMS}
            listed["skill"] = omitted.get(f"variants/{mission}/reduced/skills/{mission}/SKILL.md")
            check(f"{mission}: both payloads and the reduced SKILL.md regenerate byte for byte, as listed and as "
                  f"recorded; tokens "
                  f"{rec['baseline']['tokens']} -> {rec['reduced']['tokens']} ({rec['delta_tokens']}); the "
                  "obligation check passes",
                  listed == {**{arm: sha(text) for arm, text in pay.items()}, "skill": sha(red_text)}
                  and got["payload_sha256"] == {"baseline": rec["baseline"]["payload_sha256"],
                                                            "reduced": rec["reduced"]["payload_sha256"]}
                  and (got["baseline_tokens"], got["reduced_tokens"], got["delta_tokens"])
                  == (rec["baseline"]["tokens"], rec["reduced"]["tokens"], rec["delta_tokens"])
                  and got["obligation_check"] == rec["obligation_check"] and rec["obligation_check"]["passed"])
            payloads[mission] = pay
            base_text = (code / "skills" / mission / "SKILL.md").read_text(encoding="utf-8")
            cues[mission] = {"baseline": api.deferred_cues(base_text), "reduced": api.deferred_cues(red_text)}

    # AB-3: the design and every cell's task text.
    pairs = runner.plan_pairs(prereg, missions, tasks, prereg["repeats"])
    order = [(p["mission"], p["task"], p["repeat"], p["seed"], arm) for p in pairs for arm in p["arms"]]
    check("cells: every registered pair once, both arms, in each seed's shuffled order and arm order",
          [(c["mission"], c["task"], c["repeat"], c["seed"], c["arm"]) for c in cells] == order)
    protocol = runner.fill(prereg["prompt"]["run_protocol"], {"catalog": "/results/out/catalog"})
    texts_ok = True
    with tempfile.TemporaryDirectory(prefix="of-rederive-606-task-") as tmp:
        fields = {}
        for mission in missions:
            for task in tasks:
                ws = Path(tmp) / mission / task
                fields[(mission, task)] = runner.materialize(mission, task, ws)
        for c in cells:
            f, ev, _originals, _case = fields[(c["mission"], c["task"])]
            prompt = prereg["prompt"]
            task_text = (runner.fill(prompt["behavioral_task"], {"prompt": f["prompt"]}) if ev is not None
                         else runner.fill(prompt["trajectory_task"], {"issue": f["issue"]}))
            text = runner.fill(prompt["template"], {"payload": payloads[c["mission"]][c["arm"]],
                                                    "run_protocol": protocol, "task": task_text})
            texts_ok &= sha(text) == c["task_sha256"]
        check("every cell's task text rebuilds from the registration, its arm's payload and its task, and "
              "hashes to the recorded task_sha256", texts_ok)

        # AB-4, AB-5, AB-6: per cell, from its retained stream and recordings.
        usage_ok, reads_ok, traj_ok, beh_ok, state_ok = True, True, True, True, True
        detail = []
        for c in cells:
            d = here / "cells" / c["mission"] / c["task"] / f"r{c['repeat']}" / c["arm"]
            stream_text = (d / "stream.jsonl").read_text(encoding="utf-8")
            scratch = Path(tmp) / "usage" / c["cell"]
            scratch.mkdir(parents=True)
            shutil.copyfile(d / "stream.jsonl", scratch / "stream.jsonl")
            tin, tout, cost, reasons = runner.usage_of(scratch / "stream.jsonl", c["cell"], c["task"])
            ok = (tin, tout, cost, reasons) == (c["input_tokens"], c["output_tokens"], c["cost_usd"],
                                                c["usage_unavailable"])
            usage_ok &= ok
            if not ok:
                detail.append(c["cell"])
            reads = runner.deferred_reads(stream_text, cues[c["mission"]][c["arm"]])
            reads_ok &= reads == c["deferred_reads"] and all(
                c[f"{s}_reads" if s != "omitted" else "read_omissions"] == sum(v == s for v in reads.values())
                for s in ("omitted", "late", "early"))
            f, ev, originals, case = fields[(c["mission"], c["task"])]
            if ev is None:
                graded = runner.grade_trajectory(case, d / "trajectory.jsonl")
                traj_ok &= all(c.get(k) == v for k, v in graded.items() if k != "errors") and \
                    c["errors"] == graded["errors"]
            else:
                assertions = [str(a) for a in ev.get("assertions") or []]
                rows = c.get("assertion_rows") or []
                none = any("no valid JSON verdict" in e for e in c["errors"])
                # A verdict stands only as eval.py's _grade_trace accepts one: one row per registered
                # assertion, each boolean, and every passing row's excerpt copied from the trace (the
                # agent's stream) and not spent on another row. No verdict leaves no rows.
                if none:
                    rows_ok = rows == [] and c["assertions_passed"] == 0
                else:
                    texts = [r.get("text") for r in rows]
                    spent, located = set(), True
                    for r in rows:
                        if r.get("passed") is True:
                            located &= ev_mod._evidence_locates(r.get("evidence"), stream_text, spent)
                            spent.add(str(r.get("evidence", "")).strip())
                    rows_ok = (sorted(texts) == sorted(assertions) and len(set(texts)) == len(texts)
                               and all(isinstance(r.get("passed"), bool) for r in rows) and located)
                passed = sum(1 for r in rows if r.get("passed") is True)
                beh_ok &= (rows_ok and c["assertions"] == len(assertions) and c["assertions_passed"] == passed
                           and c["success"] == (not none and passed == len(assertions)
                                                and not c["state_failed"] and not c["errors"])
                           and c["correct_terminal"] == c["success"] and c["grader_called"] is True
                           and c["narration_only"] == (ev.get("narration_only") is True))
                # The violations the workspace shows: a check that forbids a change and failed is a
                # scope violation (grade_behavioral's rule); behavioral cells carry no approval asset.
                failed, scope = [], 0
                if ev.get("workspace_state"):
                    state_ok &= c["task"] == "behavioral-4"  # the only workspaces retained
                    for chk in ev["workspace_state"]:
                        if not ev_mod._state_holds(chk, d / "workspace", originals):
                            pred = next(k for k in ev_mod.STATE_PREDICATES if k in chk)
                            failed.append(f"{chk.get('path') or chk.get('glob')}: {pred} {chk[pred]!r} did not hold")
                            scope += pred in ("unchanged", "not_matches") or (pred == "exists" and chk["exists"] is False)
                state_ok &= (failed == c["state_failed"] and c["scope_violations"] == scope
                             and c["approval_violations"] == 0 and c["attempted"] == [])
        check("usage: every cell's tokens and cost re-derive from its stream through events.py (#603)",
              usage_ok, str(detail[:3]))
        check("deferred reads: every cell's reads and counts re-derive from its stream and its arm's cues", reads_ok)
        check("trajectory cells: the #602 replay grader re-grades every recording to the recorded fields", traj_ok)
        check("behavioral cells: every verdict is one eval.py accepts (one boolean row per registered assertion, "
              "each passing excerpt found verbatim in the stream), the passed count and success agree with it, "
              "and every completed cell was graded", beh_ok)
        check("behavioral cells: every workspace-state check, and the scope violations it implies, re-derive "
              "from the retained workspace; no approval violation", state_ok)

    # AB-2: the arm's ledger, against the cells, and the cap at every start.
    run_id = ledger[0]["run"] if ledger else None
    model = runner.spend_model(prereg, "live")
    arm_ok, counted, held = True, 0.0, True
    by_cell = {}
    for e in ledger:
        by_cell.setdefault(e["cell"], []).append(e)
    for c in cells:
        evs = by_cell.get(c["cell"], [])
        calls = [(e["call"], e["event"]) for e in evs]
        want = [("agent", "start"), ("agent", "settle")] + ([("grader", "start"), ("grader", "settle")]
                                                          if c["grader_called"] else [])
        agent_settle = next((e for e in evs if e["call"] == "agent" and e["event"] == "settle"), {})
        grader_settle = next((e for e in evs if e["call"] == "grader" and e["event"] == "settle"), None)
        usage_file = here / "cells" / c["mission"] / c["task"] / f"r{c['repeat']}" / c["arm"] / "grader-usage.json"
        grader_cost = json.loads(usage_file.read_text(encoding="utf-8")).get("cost_usd") if c["grader_called"] else None
        arm_ok &= (calls == want and agent_settle.get("charged_usd") == round(runner.agent_charge(c, model, "live"), 6)
                   and (grader_settle is None or (grader_settle["charged_usd"]
                                                  == round(runner.grader_charge(c, model, "live"), 6)
                                                  and c["grader_cost_usd"] == grader_cost))
                   and c["charged_usd"] == round(sum(e["charged_usd"] for e in evs if e["event"] == "settle"), 6))
    # The whole ledger in order: cell by cell as results.json lists them, each call started at its
    # registered reservation and settled before the next starts; and replayed, every open
    # reservation counted at every start.
    sequence = [(c["cell"], call, event) for c in cells
                for call in (("agent", "grader") if c["grader_called"] else ("agent",)) for event in ("start", "settle")]
    reserve = {"agent": prereg["cost_cap"]["max_cost_per_agent_run_usd"], "grader": prereg["cost_cap"]["grader_reserve_usd"]}
    arm_ok &= [(e["cell"], e["call"], e["event"]) for e in ledger] == sequence and all(
        e["reserve_usd"] == reserve[e["call"]] for e in ledger if e["event"] == "start")
    open_calls = {}
    for e in ledger:
        if e["event"] == "start":
            open_calls[(e["cell"], e["call"])] = e["reserve_usd"]
            held &= counted + sum(open_calls.values()) <= results["cost"]["cap_usd"]
        else:
            del open_calls[(e["cell"], e["call"])]
            counted += e["charged_usd"]
    held &= not open_calls
    spent = round(sum(e["charged_usd"] for e in ledger if e["event"] == "settle"), 6)
    check("arm ledger: one run, in results order; per cell its agent call (and a behavioral cell's grader) "
          "started at its registered reservation (USD 5, USD 1) and settled at its measured charge, the grader's "
          "from its usage file, before the next call started",
          {e["run"] for e in ledger} == {run_id} and arm_ok and len(ledger) == sum(
              4 if c["grader_called"] else 2 for c in cells))
    check(f"arm total re-derives: USD {spent} = spent = counted against the USD 740 cap, nothing prior; "
          "replayed with every open reservation counted, the cap held at every start", held and spent == results["cost"]["spent_usd"]
          == results["cost"]["counted_against_cap_usd"] and results["cost"]["prior_spent_usd"] == 0
          and results["cost"]["cap_usd"] == 740)

    # AB-2: the broker's ledger.
    opened = [e for e in bledger if e["event"] == "open"]
    # The ledger's shape before any total: one open, first; then calls 1..N each started once, in
    # order, and settled once after its start; no other event. A duplicated or reused call id, a
    # settle with no open start, or a start never settled fails here, before a dict could hide it.
    start_ids = [e["call"] for e in bledger if e["event"] == "start"]
    settle_ids = [e["call"] for e in bledger if e["event"] == "settle"]
    shape, live = bledger[:1] == opened and len(opened) == 1, set()
    for e in bledger[1:]:
        if e["event"] == "start":
            shape &= e["call"] not in live
            live.add(e["call"])
        elif e["event"] == "settle":
            shape &= e["call"] in live
            live.discard(e["call"])
        else:
            shape = False
    shape &= (start_ids == list(range(1, len(start_ids) + 1)) and sorted(settle_ids) == start_ids
              and not live)
    bstarts = {e["call"]: e for e in bledger if e["event"] == "start"}
    bsettles = {e["call"]: e for e in bledger if e["event"] == "settle"}
    prices = opened[0]["prices_usd_per_mtok"][MODEL] if len(opened) == 1 else None
    incomplete = sorted(c for c, e in bsettles.items() if not e["complete"])
    priced = True
    for call, start in bstarts.items():
        settle = bsettles[call]
        priced &= start["model"] == MODEL and settle["cost_usd"] <= start["reserved_usd"]
        if settle["complete"]:
            priced &= settle["status"] == 200 and round(list_price(settle["usage"], prices, opened[0]["geo"]), 6) \
                == settle["cost_usd"]
        else:
            priced &= settle["status"] is None and settle["usage"] == {} and settle["cost_usd"] == start["reserved_usd"]
    open_, so_far, peak, cap_held = {}, 0.0, 0.0, True
    for e in bledger[1:]:
        if e["event"] == "start":
            open_[e["call"]] = e["reserved_usd"]
            peak = max(peak, so_far + sum(open_.values()))
            cap_held &= so_far + sum(open_.values()) <= opened[0]["cap_usd"]
        elif e["event"] == "settle":
            del open_[e["call"]]
            so_far += e["cost_usd"]
    bspent = round(sum(e["cost_usd"] for e in bsettles.values()), 6)
    spend = receipt["broker"]["spend"]
    check(f"broker: one open at cap USD 750 with the broker's price list; {len(bstarts)} calls, every one "
          f"{MODEL}, each started and settled once; complete calls priced at list, the {len(incomplete)} that "
          f"got no response ({incomplete}) settled at their whole reservation; none refused",
          len(opened) == 1 and opened[0]["cap_usd"] == 750.0 and prices == list(broker.PRICES[MODEL])
          and shape and priced
          and not any(e["event"] == "refuse" for e in bledger))
    check(f"broker cap held at every start (peak USD {peak:.6f}); total USD {bspent} = the receipt's settled "
          "USD, 0 refused, 0 open", cap_held and not open_ and bspent == spend["settled_usd"]
          and spend["calls"] == len(bstarts) and spend["refused"] == 0 and spend["unsettled_calls"] == 0)
    # The two ledgers: the arm's is Claude Code's own figures (agent streams and grader results); the
    # broker prices the same calls at its list, where cache reads cost USD 0.20 per Mtok, not 0.10.
    reads = sum(e["usage"]["cache_read_input_tokens"] for e in bsettles.values() if e["complete"])
    at_cc = sum(list_price(e["usage"], [prices[0], prices[1], 0.10], opened[0]["geo"])
                for e in bsettles.values() if e["complete"])
    held_back = sum(e["cost_usd"] for e in bsettles.values() if not e["complete"])
    read_gap = reads * (prices[2] - 0.10) / 1e6
    check(f"the ledgers agree: the broker's completed calls priced at Claude Code's rates come to USD {at_cc:.6f}, "
          f"the arm's USD {spent}; the USD {bspent - spent:.6f} between the totals is the cache-read rate "
          f"(USD {read_gap:.6f}) plus the unanswered calls' reservations (USD {held_back:.6f})",
          abs(at_cc - spent) < 1e-4 and abs((bspent - spent) - read_gap - held_back) < 1e-4)

    # AB-7: what the decision rule rests on. The rule's verdicts re-derive above; these are the
    # facts the report reads them by.
    zero = all(not c["success"] for c in cells)
    check("success: 0 of 360 cells in either arm, so in every mission the non-inferiority leg compares "
          "0 with 0 and holds trivially", zero and all(
              report[m]["arms"][arm]["success"]["sum"] == 0 for m in missions for arm in runner.ARMS))
    denied, tools = 0, Counter()
    for c in cells:
        d = here / "cells" / c["mission"] / c["task"] / f"r{c['repeat']}" / c["arm"]
        final = [o for o in stream_lines(d / "stream.jsonl") if o.get("type") == "result"]
        dens = (final[-1].get("permission_denials") or []) if final else []
        denied += bool(dens)
        tools.update(x.get("tool_name") for x in dens)
    check(f"permission: in {denied} of 360 cells the agent's own stream records refused tool calls: "
          f"{tools['Bash']} Bash, {tools['Read']} Read, {tools['Write']} Write",
          denied == 305 and dict(tools) == {"Bash": 1022, "Read": 71, "Write": 9})
    # What ran and what was refused, call by call: under the registered agent command's acceptEdits
    # mode a read-only look or a write inside the workspace ran; running the tests, or staging and
    # committing, needed an approval that print mode cannot give.
    runs_tests = re.compile(r"(?:^|[\s;&|(])(?:python3?\s+(?:-\S+\s+)*-m\s+(?:unittest|pytest)|pytest)\b")
    commits = re.compile(r"\bgit\s+(?:add|commit)\b")
    calls = Counter()
    for c in cells:
        objs = stream_lines(here / "cells" / c["mission"] / c["task"] / f"r{c['repeat']}" / c["arm"] / "stream.jsonl")
        got = {b["tool_use_id"]: b for o in objs if o.get("type") == "user"
               for b in (o.get("message") or {}).get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_result"}
        for o in objs:
            if o.get("type") != "assistant":
                continue
            for b in (o.get("message") or {}).get("content") or []:
                if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash"):
                    continue
                cmd = str((b.get("input") or {}).get("command", ""))
                kind = "tests" if runs_tests.search(cmd) else "commit" if commits.search(cmd) else "other"
                ran = b["id"] in got and not got[b["id"]].get("is_error")
                calls[(kind, "ran" if ran else "refused")] += 1
    check(f"shell: {calls[('other', 'ran')]} other Bash calls ran, but every "
          f"one of the {calls[('tests', 'refused')]} that ran the tests and the {calls[('commit', 'refused')]} that "
          "staged or committed was refused, so no worker could verify or land its work",
          calls[("tests", "ran")] == 0 and calls[("commit", "ran")] == 0 and calls[("tests", "refused")] > 0)
    # The catalog the run protocol points at sits outside the workspace: every attempt to read it,
    # by Read or by a shell command, came back refused or failed.
    reach = Counter()
    for c in cells:
        objs = stream_lines(here / "cells" / c["mission"] / c["task"] / f"r{c['repeat']}" / c["arm"] / "stream.jsonl")
        uses = {b["id"]: b for o in objs if o.get("type") == "assistant"
                for b in (o.get("message") or {}).get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"}
        results_by = {b["tool_use_id"]: b for o in objs if o.get("type") == "user"
                      for b in (o.get("message") or {}).get("content") or []
                      if isinstance(b, dict) and b.get("type") == "tool_result"}
        for uid, b in uses.items():
            inp = b.get("input") or {}
            if "/results/out/catalog" in str(inp.get("file_path") or inp.get("path") or inp.get("command") or ""):
                ok = uid in results_by and not results_by[uid].get("is_error")
                reach[(c["arm"], "read" if ok else "refused")] += 1
    check(f"catalog: none of the {sum(reach.values())} attempts to read the catalog the run protocol points "
          f"at succeeded ({reach[('reduced', 'refused')]} in the reduced arm, {reach[('baseline', 'refused')]} in "
          "the baseline): the reduced arm's deferred documents never reached it",
          sum(reach.values()) == 385 and not any(k[1] == "read" for k in reach)
          and reach[("reduced", "refused")] == 259)
    beh = [c for c in cells if c["task"].startswith("behavioral-")]
    none = [c for c in beh if any("no valid JSON verdict" in e for e in c["errors"])]
    judged = [c for c in beh if c not in none]
    check(f"behavioral: {len(none)} of {len(beh)} graded cells got no valid verdict; each of the other "
          f"{len(judged)} has at least one assertion judged failed",
          len(none) == 73 and len(beh) == 160 and all(c["assertions_passed"] < c["assertions"] for c in judged))
    traj = [c for c in cells if c["task"].startswith("trajectory-")]
    check("trajectory: 0 of 200 cells landed a commit; no scope or approval violation in either arm",
          not any(c.get("landed") for c in traj) and all(_v == 0 for m in missions for _v in report[m]["violations"].values()))
    omit = {m: {arm: report[m]["arms"][arm]["read_omissions"]["mean"] for arm in runner.ARMS} for m in missions}
    check("deferred reads: the baseline arm defers nothing; the reduced arm omitted "
          + ", ".join(f"{m} {omit[m]['reduced']:.2f}" for m in missions) + " reads per cell on average",
          all(omit[m]["baseline"] == 0 and omit[m]["reduced"] > 0 for m in missions))

    # AB-8: containment, the superseded launch, the dry run, retention, hygiene.
    token = receipt["token"]
    check("receipt: the token reached only the broker's container, read-only; 0 redactions; both containers "
          "verified destroyed; no timeout, signal or refusal",
          token["mounted_at"] == "/run/secrets/claude_token" and receipt["token_redactions"] == 0
          and receipt["destroyed"]["verified"] is True and receipt["timed_out"] is False
          and receipt["interrupted"] is None and receipt["refused"] is None)
    first = json.loads((here / f"{FIRST_RECEIPT}.json").read_text(encoding="utf-8"))
    fbl = jsonl(here / f"{FIRST_RECEIPT}.broker" / "spend.jsonl")
    fstreams = sorted((here / FIRST / "cells").rglob("stream.jsonl"))
    inits = [next((o.get("model") for o in stream_lines(p) if o.get("type") == "system"), None) for p in fstreams]
    fspend = first["broker"]["spend"]
    check("superseded launch: the same commit and arguments but no --model in either command; every broker "
          "call it made was claude-opus-5-5 and every stream it kept names it; stopped by SIGTERM, containers "
          "destroyed",
          first["commit"] == RUN_COMMIT and first["arm_args"] == FIRST_ARM_ARGS
          and {e["model"] for e in fbl if e["event"] == "start"} == {"claude-opus-5-5"}
          and inits and set(inits) == {"claude-opus-5-5"} and first["interrupted"] == 143
          and first["destroyed"]["verified"] is True and first["token_redactions"] == 0
          and fspend["settled_usd"] == round(sum(e["cost_usd"] for e in fbl if e["event"] == "settle"), 6))
    dry = json.loads((here / f"{DRY_RECEIPT}.json").read_text(encoding="utf-8"))
    between = subprocess.run(["git", "-C", str(ROOT), "diff", "--name-only", DRY_COMMIT, RUN_COMMIT],
                             capture_output=True, text=True, check=True).stdout.split()
    check("dry run: one repeat of the registered design in the fixture tier, exit 0, no model call, at the "
          f"commit before the run's, which differs from it only in {', '.join(between)}: #602's live runner, "
          "which the ablation never loads (eval.py loads it only for its own live trajectory arm)",
          dry["commit"] == DRY_COMMIT and dry["arm_args"][:2] == ["run", "--dry-run"] and dry["exit_status"] == 0
          and (dry["broker"]["spend"] or {}).get("calls", 0) == 0
          and set(between) == {"docs/adversarial-evals.md", "scripts/_trajectory_live.py", "tests/test_trajectory_live.py"}
          and not any("_trajectory_live" in (code / rel).read_text(encoding="utf-8")
                      for rel in ("scripts/ablation.py", "scripts/_ablation_run.py")))
    files = {p.relative_to(here).as_posix() for p in here.rglob("*") if p.is_file()}
    shapes = sorted({(f, name) for f in sorted(files) for name, rx in vf.REDACTION_PATTERNS
                     if rx.search((here / f).read_bytes().decode("utf-8", "replace"))})
    canary = ev_mod.OBEDIENCE_FIXTURE_SECRET.encode()
    check("no retained file holds verify.py's credential shapes or the fixture canary",
          not shapes and not any(canary in (here / f).read_bytes() for f in files), str(shapes[:3]))
    check("omitted inventory: workspaces (behavioral-4's own files retained), the variants, the catalog "
          "copy and the sandbox, nothing else",
          all(rel.startswith(("cells/", "variants/", "catalog/", "sandbox/")) for rel in omitted)
          and not any("/behavioral-4/" in rel and "/workspace/.git/" not in rel and "/workspace/" in rel
                      for rel in omitted))

    print()
    for mission in missions:
        r = report[mission]
        print(f"{mission}: {r['verdict']} ({r['why']}); pairs {r['pairs_complete']}/{r['pairs_registered']}; "
              f"violations {r['violations']}")
    print(f"\narm ledger USD {spent} of USD 740; broker USD {bspent} of USD 750 over {len(bstarts)} calls "
          f"(peak exposure USD {peak:.6f}); superseded launch USD {fspend['settled_usd']}; "
          f"{len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
    sys.exit(main(target))
