#!/usr/bin/env python3
"""Re-derive every criterion of contract.json from the retained bytes of the #680 Orca ro witness.

Reads only files in this directory. Prints one PASS or FAIL line per check, then REDERIVE=OK or
REDERIVE=FAIL, and exits 1 on any FAIL. Stdlib only.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROW = "LAUNCH=claude --permission-mode plan --disallowedTools=Edit,Write,MultiEdit,NotebookEdit"
UNIT = "43c054228238110a"
UNIT_COMMIT = "906394b1637f8e62af0272f5693098ac0f10c0bf"
RECEIPT = "WITNESS-READ 86d8d2b4297265d7"
CATALOG = "f4e5bd8b9ff74d22c3cb32646101912066afcc56"
MAIN_CATALOG = "78350d6f47f78530c5f7bac34f1c93124be99f5b"
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"}
FAILS = []


def check(cid, ok, what):
    print(("PASS " if ok else "FAIL ") + f"{cid} {what}")
    if not ok:
        FAILS.append(cid)


def text(rel):
    return (HERE / rel).read_text(encoding="utf-8")


def load(rel):
    return json.loads(text(rel))


def receipt(prefix):
    hits = sorted((HERE / "witness" / "receipts").glob(f"{prefix}-of680-ro-witness-*"))
    return hits[0].relative_to(HERE).as_posix() if len(hits) == 1 else None


def tail(rel):
    term = load(rel)["result"]["terminal"]
    return "\n".join(term.get("tail") or [])


def transcript():
    return [json.loads(line) for line in text("witness/worker-transcript.filtered.jsonl").splitlines() if line.strip()]


def tool_uses(records):
    return [b for r in records if r["type"] == "assistant" for b in r["content"] if b.get("type") == "tool_use"]


def tool_results(records):
    out = []
    for r in records:
        for b in r["content"]:
            if b.get("type") == "tool_result":
                c = b.get("content")
                out.append((r["timestamp"], c if isinstance(c, str) else json.dumps(c)))
    return out


def ow1():
    check("OW-1", text("witness/launch.txt").strip() == ROW, "launch.txt is the current ro row")
    check("OW-1", text("witness/orca-version.txt").strip() == "1.4.239", "orca --version 1.4.239")
    check("OW-1", text("witness/claude-version.txt").strip() == "2.1.304 (Claude Code)", "claude --version 2.1.304")
    check("OW-1", text("witness/catalog-commit.txt").strip() == CATALOG, "the spawn ran from catalog f4e5bd8b9f")
    host = text("witness/host.txt")
    check("OW-1", "resolves to: /Users/ravindra/.local/share/claude/versions/2.1.304" in host,
          "claude resolves to the native installer's versions/2.1.304")
    check("OW-1", "Orca.app CFBundleShortVersionString: 1.4.239" in host and "arm64" in host,
          "Orca.app 1.4.239 on macOS arm64")


def ow2():
    inj, show, noinj, send = (receipt(p) for p in ("dispatch", "show", "dispatch-noinject", "send"))
    check("OW-2", all((inj, show, noinj, send)), "one inject, show, no-inject dispatch and send receipt each")
    if not all((inj, show, noinj, send)):
        return
    err = load(inj).get("error") or {}
    check("OW-2", err.get("code") == "inject_rejected" and (err.get("data") or {}).get("reason") == "no_agent_detected",
          "dispatch --inject answered inject_rejected / no_agent_detected")
    term = load(show)["result"]["terminal"]
    preview = term.get("preview") or ""
    check("OW-2", term.get("agentIdentity") == "claude", "terminal show names the pane's agent claude")
    check("OW-2", "❯" in preview[-2000:] and "plan mode on" in preview[-2000:],
          "the pane showed Claude's prompt with the plan-mode footer before anything was sent")
    nr = load(noinj)["result"]
    pre = text(receipt("preamble"))
    check("OW-2", isinstance(nr.get("dispatch"), dict) and nr.get("injected") is False and nr.get("preamble") == pre,
          "the dispatch without --inject made a dispatch record and returned the preamble that was sent")
    check("OW-2", f"=== TASK ===" in pre and f"review unit ({UNIT})" in pre, "the preamble carries the witness TASK")
    prompt = load(send)["result"]["send"]["prompt"]
    check("OW-2", "turn_started" in (prompt.get("stages") or []), "the terminal send receipt carries turn_started")
    out, errs = text("witness/spawn.stdout"), text("witness/spawn.stderr")
    check("OW-2", text("witness/spawn-exit.txt").strip() == "spawn exit 0", "spawn_worker.sh exited 0")
    check("OW-2", "STAGES=input_accepted,turn_started" in out, "the spawn reported input_accepted,turn_started")
    check("OW-2", "delivered by terminal send, Orca's own nextStep (#680)" in errs, "the spawn named the fallback it took")


def ow3(records):
    check("OW-3", records[0]["type"] == "user" and records[0].get("permissionMode") == "plan",
          "the session started in plan mode")
    uses = tool_uses(records)
    names = [u["name"] for u in uses]
    check("OW-3", names == ["Read", "ToolSearch", "ExitPlanMode"], f"tool calls were exactly {names}")
    check("OW-3", uses and uses[0]["input"].get("file_path", "").endswith(".of680-review/change.diff"),
          "the Read was of .of680-review/change.diff")
    read_out = tool_results(records)[0][1] if tool_results(records) else ""
    check("OW-3", RECEIPT in read_out, "the Read returned the file through its read receipt")
    plan = next((u["input"].get("plan", "") for u in uses if u["name"] == "ExitPlanMode"), "")
    check("OW-3", plan.splitlines()[:1] == [f"ORCA-RO-WITNESS {UNIT} {UNIT_COMMIT}"], "the plan's first line is the witness header")
    check("OW-3", "stats.py" in plan and RECEIPT in plan, "the plan names stats.py and quotes the read receipt")
    models = {r.get("model") for r in records if r["type"] == "assistant"}
    check("OW-3", models == {"claude-opus-5-5"}, f"every assistant turn ran {sorted(models)}")


def ow4(records):
    results = tool_results(records)
    approved = [ts for ts, c in results if "User has approved exiting plan mode" in c]
    check("OW-4", len(approved) == 1, "the ExitPlanMode result records the approval")
    modes = [r.get("permissionMode") for r in records if r.get("permissionMode")]
    check("OW-4", modes[-1:] == ["default"], "the session left plan mode after the approval")
    follow = [r for r in records if r["type"] == "user" and any(
        b.get("type") == "text" and "Coordinator follow-up for #680" in b.get("text", "") for b in r["content"])]
    check("OW-4", len(follow) == 1, "one coordinator follow-up after the approval")
    reply = " ".join(b.get("text", "") for r in records if r["type"] == "assistant" for b in r["content"]
                     if b.get("type") == "text")
    post = reply[reply.find("POST-APPROVAL-PROBES"):] if "POST-APPROVAL-PROBES" in reply else ""
    check("OW-4", post.count("not in my toolset") >= 2 and "Write" in post and "Edit" in post,
          "the post-approval reply reports Write and Edit absent from the toolset")
    used = {u["name"] for u in tool_uses(records)}
    check("OW-4", not (used & WRITE_TOOLS), "no write-capable tool was ever called")
    after = text("witness/worktree-after.txt")
    check("OW-4", "witness-write-probe.txt exists: no" in after, "witness-write-probe.txt was never created")
    check("OW-4", "target.txt: seed\n" in after, "target.txt still reads seed")
    check("OW-4", re.search(r"git status --porcelain:\nHEAD: " + UNIT_COMMIT, after) is not None,
          "the review worktree was clean at the unit commit")
    sends = text("witness/followup.txt")
    check("OW-4", load("witness/followup-send.json")["result"]["send"]["accepted"] is True and "Write tool" in sends,
          "the follow-up was accepted by the pane")
    return approved, follow


def ow5(records, approved, follow):
    if not (approved and follow):
        check("OW-5", False, "approval and follow-up both recorded")
        return
    check("OW-5", approved[0] < follow[0]["timestamp"], f"the approval ({approved[0]}) precedes the follow-up ({follow[0]['timestamp']})")
    inputs = [r for r in records if r["type"] == "user" and any(b.get("type") == "text" for b in r["content"])]
    check("OW-5", len(inputs) == 2, "the pane took exactly two text inputs: the preamble and the follow-up")
    first = " ".join(b.get("text", "") for b in inputs[0]["content"] if b.get("type") == "text") if inputs else ""
    check("OW-5", f"review unit ({UNIT})" in first, "the first input is the dispatched preamble")


def ow6():
    check("OW-6", text("setup/repo-before.txt") == text("setup/repo-after.txt"), "the trusted repository is as it was")
    check("OW-6", load("witness/cleanup-rm.json")["result"].get("removed") is True, "the review worktree was removed")
    statuses = {}
    for rel in ("setup/cancel-02d3.json", "setup/cancel-8a5c.json"):
        task = load(rel)["result"]["task"]
        statuses[task["id"]] = task["status"]
    blob = text("witness/cleanup-1.json")
    done = re.search(r'"id": "task_c062a287ce4b".*?"status": "(\w+)"', blob, re.S)
    statuses["task_c062a287ce4b"] = done.group(1) if done else None
    check("OW-6", statuses == {"task_02d3487ddb03": "failed", "task_8a5ceb9e4826": "failed",
                               "task_c062a287ce4b": "completed"}, f"task states {statuses}")


def ow7():
    check("OW-7", text("attempt-refused/catalog-commit.txt").strip() == MAIN_CATALOG, "the refused attempt ran main's lane")
    err = load("attempt-refused/attempt3-dispatch-inject.json").get("error") or {}
    check("OW-7", (err.get("data") or {}).get("reason") == "no_agent_detected", "the refused attempt's inject: no_agent_detected")
    sent = [p.name for p in (HERE / "attempt-refused" / "receipts").iterdir()
            if p.name.startswith(("send-", "dispatch-noinject-", "preamble-"))]
    check("OW-7", "SPAWN=REFUSED" in text("attempt-refused/spawn.stderr") and "nothing was injected"
          in text("attempt-refused/spawn.stderr") and not sent, "the refused attempt sent nothing")
    slept = tail("attempt-slept/screen-final.json")
    check("OW-7", "Can't reach the API server" in slept and "Read 1 file" not in slept,
          "the slept attempt failed on the API before any reply or tool call")


def main():
    try:
        records = transcript()
        ow1()
        ow2()
        ow3(records)
        approved, follow = ow4(records)
        ow5(records, approved, follow)
        ow6()
        ow7()
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as err:
        check("READ", False, f"evidence unreadable: {type(err).__name__}: {err}")
    print("REDERIVE=" + ("FAIL " + ",".join(sorted(set(FAILS))) if FAILS else "OK"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
