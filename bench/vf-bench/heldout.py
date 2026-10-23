#!/usr/bin/env python3
"""heldout.py — VF-Bench's held-out protocol: validation and the leakage check (#601).

The development corpus (`traps/*.json`) is public on purpose, so a verifier can be fitted to it.
The held-out split is a set of cases an independent holder keeps OUTSIDE this repository and
evaluates a pinned verifier against. `heldout-protocol.json` predeclares the splits, their
version digests, the planned release dates, the leakage checks and the holder role. This script
never reads held-out content from the repository; it only proves there is none:

  validate              the committed protocol is complete, its development pins equal gate.py's
                        and the corpus's, and the holder role is filled honestly or not at all.
  digest CASE_DIR       holder side: publish DIGESTS of the held-out cases (raw and canonical-JSON
                        sha256, and the sha256 of the split's canary GUID), never their content.
                        Refuses a case that does not carry the canary.
  check --digests FILE  the leakage check: no committed blob at REV (or anywhere in history with
                        --all-history) is a held-out case — verbatim, reformatted, embedded as an
                        object in a larger JSON document — or carries the held-out canary.

Exit 0: valid / clean. Exit 1: invalid protocol, a leak, or a case without its canary. Exit 2:
usage (unreadable digests, unknown revision).
"""
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROTOCOL = HERE / "heldout-protocol.json"
PROTOCOL_ID = "vf-bench-heldout@1"
DIGESTS_KIND = "vf-bench-heldout-digests"
GUID_RE = re.compile(rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
GUID_TEXT_RE = re.compile(GUID_RE.pattern.decode("ascii"))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A role is filled by a person or left empty; these are what an empty role looks like in disguise.
PLACEHOLDERS = {"", "tbd", "tba", "n/a", "na", "none", "null", "unknown", "someone", "anyone",
                "nobody", "john doe", "jane doe", "evaluation maintainer", "holder"}
JSON_PARSE_LIMIT = 20 * 1024 * 1024


class UsageError(Exception):
    pass


def canonical(obj):
    """The canonical-JSON bytes of a case: sorted keys, no whitespace, UTF-8. A reformatted copy
    of a case (indentation, key order, escapes) hashes the same; a changed one does not."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------------------------

def _gate():
    spec = importlib.util.spec_from_file_location("vfbench_gate_heldout", HERE / "gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def validate(protocol, gate=None, traps_dir=None):
    """Every problem with a protocol document, as strings (empty = valid)."""
    gate = gate or _gate()
    traps_dir = Path(traps_dir) if traps_dir else HERE / "traps"
    errors = []
    if protocol.get("protocol") != PROTOCOL_ID:
        errors.append(f"protocol is {protocol.get('protocol')!r}, not {PROTOCOL_ID!r}")
    splits = protocol.get("splits") or {}
    dev, held = splits.get("development") or {}, splits.get("heldout") or {}
    if not dev or not held:
        errors.append("the protocol must declare both a development and a heldout split")
    traps = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(traps_dir.glob("*.json"))]
    expect = {
        "version": gate.EXPECTED_VERSION,
        "canary_guid": gate.EXPECTED_CANARY_GUID,
        "corpus_sha256": gate.EXPECTED_CORPUS_SHA256,
        "cases": len(traps),
        "traps": sum(1 for t in traps if t.get("sound_expected") == "RED"),
        "valid_controls": sum(1 for t in traps if t.get("sound_expected") == "GREEN"),
        "committed": True,
    }
    for key, want in expect.items():
        if dev and dev.get(key) != want:
            errors.append(f"development split {key} is {dev.get(key)!r}; the shipped corpus and "
                          f"gate.py say {want!r} — a corpus change updates the protocol in the same PR")
    if dev and gate.corpus_digest(traps_dir) != dev.get("corpus_sha256"):
        errors.append("development split corpus_sha256 is not the digest of traps/*.json")
    if held:
        if held.get("committed") is not False:
            errors.append("the heldout split must declare committed: false — held-out content is "
                          "never committed beside the solver before its evaluation")
        published = held.get("published_digests")
        if published is not None:
            path = ROOT / str(published)
            if not path.is_file():
                errors.append(f"heldout published_digests names {published}, which does not exist")
            else:
                try:
                    load_digests(path)
                except UsageError as exc:
                    errors.append(f"heldout published_digests: {exc}")
    temporal = protocol.get("temporal") or {}
    if not str(temporal.get("rule") or "").strip():
        errors.append("the protocol must state its temporal rule")
    dates = protocol.get("release_dates") or {}
    if "planned" not in str(dates.get("label") or "").lower():
        errors.append("release_dates must be labelled as planned")
    milestones = dates.get("milestones") or []
    if not milestones:
        errors.append("release_dates must name at least one milestone")
    for m in milestones:
        name = m.get("milestone") or "?"
        if not DATE_RE.match(str(m.get("date") or "")):
            errors.append(f"milestone {name!r} has no YYYY-MM-DD date")
        if m.get("status") not in ("planned", "done"):
            errors.append(f"milestone {name!r} status is {m.get('status')!r}, not planned or done")
        if m.get("status") == "done" and not str(m.get("evidence") or "").strip():
            errors.append(f"milestone {name!r} is marked done without evidence")
    checks = protocol.get("leakage_checks") or []
    ids = {c.get("id") for c in checks}
    for need in ("digest-scan", "canary-scan", "history-scan", "temporal"):
        if need not in ids:
            errors.append(f"leakage check {need!r} is not declared")
    for c in checks:
        if not str(c.get("detects") or "").strip():
            errors.append(f"leakage check {c.get('id')!r} does not say what it detects")
        command = str(c.get("command") or "")
        if "heldout.py" in command and not str(c.get("limits") or "").strip():
            errors.append(f"leakage check {c.get('id')!r} runs a scan but states no limits: a "
                          "check may promise only what it catches (PR #645 review)")
        if "heldout.py" in command and not (HERE / "heldout.py").is_file():
            errors.append(f"leakage check {c.get('id')!r} names a command that does not exist")
    holder = protocol.get("holder") or {}
    assigned, state = holder.get("assigned"), holder.get("state")
    if not str(holder.get("role") or "").strip():
        errors.append("the holder role is not described")
    if assigned is None:
        if state != "unfilled":
            errors.append(f"no holder is assigned, so the role's state must be 'unfilled', not {state!r}")
    elif not isinstance(assigned, str) or assigned.strip().lower() in PLACEHOLDERS:
        errors.append(f"holder.assigned is {assigned!r}: a role nobody holds stays null, never a "
                      "placeholder name")
    elif state != "assigned":
        errors.append(f"a holder is named, so the role's state must be 'assigned', not {state!r}")
    return errors


# ---------------------------------------------------------------------------------------------
# digest (holder side)
# ---------------------------------------------------------------------------------------------

def digest_cases(case_dir, canary):
    """(digests document, problems). Each case must carry the split's canary GUID, so any copy of
    it — in any format, in any file — is findable without publishing the case itself."""
    files = sorted(Path(case_dir).glob("*.json"))
    if not files:
        raise UsageError(f"{case_dir} holds no *.json cases")
    problems, entries = [], []
    for f in files:
        raw = f.read_bytes()
        try:
            obj = json.loads(raw)
        except ValueError:
            problems.append(f"{f.name}: not JSON")
            continue
        if canary.encode("utf-8") not in raw:
            problems.append(f"{f.name}: does not carry the split's canary GUID")
        entries.append({"raw_sha256": sha256(raw), "canonical_sha256": sha256(canonical(obj))})
    doc = {"kind": DIGESTS_KIND, "protocol": PROTOCOL_ID,
           "canary_sha256": sha256(canary.encode("utf-8")),
           "cases": sorted(entries, key=lambda e: e["raw_sha256"])}
    return doc, problems


def load_digests(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"cannot read digests {path}: {exc}") from None
    hexd = re.compile(r"^[0-9a-f]{64}$")
    ok = (isinstance(doc, dict) and doc.get("kind") == DIGESTS_KIND
          and doc.get("protocol") == PROTOCOL_ID and isinstance(doc.get("cases"), list)
          and doc["cases"] and hexd.match(str(doc.get("canary_sha256") or ""))
          and all(isinstance(c, dict) and hexd.match(str(c.get("raw_sha256") or ""))
                  and hexd.match(str(c.get("canonical_sha256") or "")) for c in doc["cases"]))
    if not ok:
        raise UsageError(f"{path} is not a {DIGESTS_KIND} document for {PROTOCOL_ID}")
    return doc


# ---------------------------------------------------------------------------------------------
# check (the leakage scan)
# ---------------------------------------------------------------------------------------------

def _git(repo, *args, data=None):
    r = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True)
    if r.returncode != 0:
        raise UsageError(f"git {' '.join(args)}: {r.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return r.stdout


def committed_blobs(repo, rev="HEAD", all_history=False):
    """[(blob sha, path)] committed at REV, or reachable from any ref with all_history."""
    if all_history:
        listing = _git(repo, "rev-list", "--objects", "--all").decode("utf-8", "replace")
        pairs = [(ln.split(" ", 1)[0], ln.split(" ", 1)[1] if " " in ln else "")
                 for ln in listing.splitlines() if ln]
        kinds = _git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                     data="".join(f"{s}\n" for s, _ in pairs).encode()).decode().split("\n")
        blobs = {ln.split()[0] for ln in kinds if ln.endswith(" blob")}
        seen, out = set(), []
        for sha, path in pairs:
            if sha in blobs and sha not in seen:
                seen.add(sha)
                out.append((sha, path))
        return out
    _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    out = []
    for entry in _git(repo, "ls-tree", "-r", "-z", "--full-tree", rev).split(b"\0"):
        if not entry:
            continue
        meta, path = entry.split(b"\t", 1)
        mode, kind, sha = meta.decode().split()
        if kind == "blob":
            out.append((sha, path.decode("utf-8", "replace")))
    return out


def read_blobs(repo, shas):
    """{sha: bytes} through one `git cat-file --batch`."""
    if not shas:
        return {}
    raw = _git(repo, "cat-file", "--batch", data="".join(f"{s}\n" for s in shas).encode())
    out, pos = {}, 0
    for _ in shas:
        nl = raw.index(b"\n", pos)
        sha, _kind, size = raw[pos:nl].decode().split()
        start = nl + 1
        out[sha] = raw[start:start + int(size)]
        pos = start + int(size) + 1
    return out


def _objects(node, depth=0):
    if isinstance(node, dict):
        yield node, depth
        for v in node.values():
            yield from _objects(v, depth + 1)
    elif isinstance(node, list):
        for v in node:
            yield from _objects(v, depth + 1)


def decoded_text(blob):
    """The blob as text, decoded the way json.loads decodes bytes (RFC 8259 / 7159): a BOM, or the
    null-byte pattern an ASCII first character leaves, picks UTF-8, UTF-16 or UTF-32, either byte
    order (PR #645 review). None when it does not decode: binary content keeps its raw checks."""
    try:
        return blob.decode(json.detect_encoding(blob))
    except (UnicodeDecodeError, LookupError):
        return None


def scan(blob, digests):
    """The ways one blob leaks a held-out case: (kind, digest prefix). The canary and the
    canonical digest are checked on the DECODED text, so a case re-saved as UTF-16 or behind a BOM
    is still the case. Text is decoded; containers are not: a compressed, base64- or hex-encoded
    copy is outside this scan, and heldout-protocol.json states that limit beside each check."""
    raw_set = {c["raw_sha256"] for c in digests["cases"]}
    canon_set = {c["canonical_sha256"] for c in digests["cases"]}
    hits = []
    if sha256(blob) in raw_set:
        hits.append(("verbatim", sha256(blob)[:16]))
    text = decoded_text(blob)
    guids = {g.decode("ascii").lower() for g in GUID_RE.findall(blob)}
    guids |= {g.lower() for g in GUID_TEXT_RE.findall(text)} if text else set()
    if any(sha256(g.encode("ascii")) == digests["canary_sha256"] for g in guids):
        hits.append(("canary", digests["canary_sha256"][:16]))
    if text is not None and len(blob) <= JSON_PARSE_LIMIT and text.lstrip()[:1] in ("{", "["):
        try:
            doc = json.loads(text)
        except ValueError:
            doc = None
        for node, depth in _objects(doc) if doc is not None else ():
            h = sha256(canonical(node))
            if h in canon_set:
                hits.append(("canonical" if depth == 0 else "embedded", h[:16]))
    return sorted(set(hits))


def check(repo, digests, rev="HEAD", all_history=False):
    """(leaks, blobs scanned): every committed blob that IS, or carries, a held-out case."""
    blobs = committed_blobs(repo, rev, all_history)
    contents = read_blobs(repo, [s for s, _ in blobs])
    leaks = []
    for sha, path in blobs:
        for kind, prefix in scan(contents[sha], digests):
            leaks.append({"path": path, "blob": sha, "kind": kind, "digest": prefix})
    return leaks, len(blobs)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_val = sub.add_parser("validate", help="the committed protocol is complete and pinned")
    p_val.add_argument("--protocol", default=str(PROTOCOL))
    p_dig = sub.add_parser("digest", help="holder side: digests of held-out cases, never content")
    p_dig.add_argument("case_dir")
    p_dig.add_argument("--canary", required=True, help="the held-out split's canary GUID")
    p_dig.add_argument("--out", required=True)
    p_chk = sub.add_parser("check", help="no committed blob is or carries a held-out case")
    p_chk.add_argument("--digests", required=True)
    p_chk.add_argument("--repo", default=str(ROOT))
    p_chk.add_argument("--rev", default="HEAD")
    p_chk.add_argument("--all-history", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "validate":
            try:
                protocol = json.loads(Path(a.protocol).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise UsageError(f"cannot read {a.protocol}: {exc}") from None
            errors = validate(protocol)
            for e in errors:
                print(f"INVALID: {e}")
            if errors:
                return 1
            splits, holder = protocol["splits"], protocol["holder"]
            published = splits["heldout"].get("published_digests")
            print(f"held-out protocol {protocol['protocol']} valid: development split pinned to "
                  f"{splits['development']['corpus_sha256'][:12]}…; held-out digests "
                  f"{'published' if published else 'not yet published'}; "
                  f"holder {holder.get('assigned') or 'UNFILLED'}")
            return 0
        if a.cmd == "digest":
            if not GUID_RE.fullmatch(a.canary.encode()):
                raise UsageError("--canary is not a GUID")
            doc, problems = digest_cases(a.case_dir, a.canary.lower())
            for p in problems:
                print(f"REFUSED: {p}")
            if problems:
                return 1
            Path(a.out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
            print(f"{len(doc['cases'])} case digest(s) written to {a.out}; no case content included")
            return 0
        digests = load_digests(a.digests)
        leaks, scanned = check(a.repo, digests, a.rev, a.all_history)
        where = "every blob reachable from any ref" if a.all_history else f"the tree at {a.rev}"
        for leak in leaks:
            print(f"LEAK {leak['kind']}: {leak['path'] or leak['blob']} "
                  f"(blob {leak['blob'][:12]}, held-out digest {leak['digest']}…)")
        if leaks:
            print(f"{len(leaks)} leak(s) in {where}: held-out content is committed beside the solver")
            return 1
        print(f"clean: {scanned} committed blob(s) in {where} checked against "
              f"{len(digests['cases'])} held-out case digest(s) and the held-out canary")
        return 0
    except UsageError as exc:
        print(f"heldout: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
