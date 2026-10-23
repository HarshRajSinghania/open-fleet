#!/usr/bin/env python3
"""An append-only lifecycle event record, and the wave metrics derived from it (#603).

attention-budget.md's WIP-curve protocol asks every mutating run for one row per dispatch wave —
verified-CLOSED throughput, verification latency, rework, freshness — and until now a coordinator
typed those numbers from memory. This record is what they are derived from instead: one JSON
object per observed lifecycle transition, appended to ``.orca/events.jsonl`` (mode 0600), and a
``report`` that recomputes the wave rows from it, byte-for-byte the same on the same record.

Status, stated first: local evidence tooling, not a telemetry service — no network, no daemon.
The observation sources that already exist are READ, never modified: the local-state DB
(``ingest-state``: launches, worker_done mail, deaths), verify.py's ``--transcript-out`` verdict
(``ingest-transcript``) and a Claude worker's stream-json result line (``ingest-usage``). Waves,
reviews, closes and parks have no machine output yet, so the coordinator records them with
``emit``. R04 (#597) launch-intent and R06 (#599) merge-queue receipts are later sources.

Record (keys sorted on the line)::

    {"v": 1, "event_id", "kind", "run", "task", "dispatch", "epoch", "producer",
     "observed_at", "clock", "basis", "source": {"ref", "sha256"}, "data", "prev"}

* **Binding.** ``run``/``task``/``dispatch`` reuse the runtime's own ids; ``source`` names the
  artifact or store row the observation came from. ``event_id`` is the producer's idempotency key
  (content-derived when omitted): a re-delivery is skipped at append and collapsed at read, so a
  duplicate never double-counts; the same id saying something different is a CONFLICT and
  contests every metric it touches. Who recorded it (``epoch``) and — unless ``basis`` is
  ``occurred`` — when it was recorded are not what it says, so a re-ingest is a duplicate.
* **Clocks.** ``observed_at`` is ISO-8601 with an offset, read on the ``clock`` it names. An
  interval is computed only between two events on the SAME clock; ``basis`` says what the time
  means — ``occurred`` (the store's own time of the fact), ``observed`` (seen live), or
  ``recovered`` (rebuilt after a crash, so the time is when it was rebuilt) — and an interval
  with a recovered end is unavailable. A negative interval is a clock that stepped back: it is
  unavailable, never clamped to zero.
* **Resume.** ``epoch`` is the coordinator epoch the event was recorded under: ``run.start``
  declares 1, each ``coordinator.resume`` declares the next. In record order, an event below the
  declared epoch is a fenced (stale) writer's and one above it is undeclared; both are excluded
  and the metrics they would have touched are unavailable, not guessed.
* **Derivation is order-free.** A unit's outcome comes from the SET of its observations, and its
  intervals are bound by head SHA (the worker_done at the head the verdict passed), so the same
  observations appended in any order derive the same rows.
* **Tamper-evident.** ``prev`` chains each line to the raw line before it, as egress.py does; an
  edit, reorder or truncation fails ``verify``/``report`` closed. A rewrite from scratch chains
  to its own genesis — anchor the head off the writer and pass ``--expect-head``/``--expect-ancestor``.

Subcommands
    emit               append one coordinator-observed event
    ingest-state       read a local-state DB (strictly read-only) for one run
    ingest-transcript  record a verify.py --transcript-out verdict
    ingest-usage       record model usage from a Claude stream-json log
    verify             recompute the chain, print the head
    report             derive the per-wave WIP-curve rows (``--json`` for everything)
    check              compare a run report's WIP-curve rows against the record

Exit codes
    0  ok
    1  report: a metric is unavailable · check: a row disagrees · emit: a conflict was
       recorded · ingest: nothing to record
    2  usage — a missing or malformed argument, or an event the schema refuses
    3  fail-closed — the record is unwritable, unreadable, tampered or schema-invalid
"""
import argparse
import fcntl
import importlib.util
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _sibling(name, filename):
    """A sibling script loaded by path, the way verify.py loads dispatch-sign.py."""
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# One timestamp shape and one sha256 helper (egress.py), one list of credential shapes
# (decisions.py) — reused, not copied, so the three ledgers cannot drift apart.
_egress = _sibling("egress", "egress.py")
_decisions = _sibling("decisions", "decisions.py")
sha256_hex = _egress.sha256_hex

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_USAGE = 2
EXIT_FAIL_CLOSED = 3

DEFAULT_LOG = ".orca/events.jsonl"
PRIMARY_LOG_ENV = "OPEN_FLEET_EVENTS_LOG"
LOG_ENV = "ORCA_EVENTS_LOG"
RECORD_VERSION = 1
REPORT_SCHEMA = "open-fleet.events-report/1"
FIELDS = ("v", "event_id", "kind", "run", "task", "dispatch", "epoch", "producer",
          "observed_at", "clock", "basis", "source", "data")
BASES = ("occurred", "observed", "recovered")
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+=-]{0,199}")
SHA_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
MONEY_RE = re.compile(r"\d+(?:\.\d+)?")
URL_CREDENTIAL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s@:]+:[^/\s@]+@")
MAX_TEXT_BYTES = 512
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
                "cache_creation_input_tokens")
USAGE_FIELDS = TOKEN_FIELDS + ("cost_usd",)

# kind -> (task required, dispatch required, {data key: (type, required)}). Closed: a key not
# listed is refused, so nothing free-form (a payload, a transcript) can ride into the record.
_R, _O = True, False
KINDS = {
    "run.start": (False, False, {"coordinator": ("id", _R)}),
    "coordinator.resume": (False, False, {"coordinator": ("id", _R)}),
    "wave.open": (False, False, {"wave": ("pos", _R), "builders": ("count", _R),
                                 "reviewers": ("count", _R), "tasks": ("ids", _R)}),
    "wave.close": (False, False, {"wave": ("pos", _R)}),
    "dispatch.launched": (True, True, {"agent": ("id", _O)}),
    "dispatch.died": (True, True, {}),
    "task.done": (True, True, {"head_sha": ("sha", _O)}),
    "review.started": (True, False, {"head_sha": ("sha", _R)}),
    "review.verdict": (True, False, {"verdict": ("verdict", _R), "reviewed_sha": ("sha", _R),
                                     "reviewed_wtree": ("sha", _O)}),
    "review.voided": (True, False, {"reviewed_sha": ("sha", _R), "head_sha": ("sha", _R)}),
    "verify.verdict": (True, False, {"exit": ("count", _R), "head_sha": ("sha", _O)}),
    "unit.closed": (True, False, {"head_sha": ("sha", _R), "head_wtree": ("sha", _O)}),
    "unit.parked": (True, False, {"park_class": ("id", _R), "head_sha": ("sha", _O)}),
    "unit.suspect": (True, False, {}),
    "model.usage": (False, False, {"model": ("id", _O),
                                   **{f: ("count", _O) for f in TOKEN_FIELDS},
                                   "cost_usd": ("money", _O), "provenance": ("text", _R)}),
}
DECLARES_EPOCH = ("run.start", "coordinator.resume")
VERDICTS = ("approve", "changes")
# What a unit has to have reached before each wave metric is final (see derive_unit).
CLOSED_OR_PARKED = ("verified-closed", "closed-unverified", "parked")
LEFT_DISPATCHED = CLOSED_OR_PARKED + ("verified",)
ROW_METRICS = ("throughput", "latency_median", "latency_max", "rework", "freshness")
UNAVAILABLE = "unavailable"


class EventsError(Exception):
    """Fail-closed: the record is unwritable, unreadable, tampered or schema-invalid (exit 3)."""


class UsageError(Exception):
    """A missing or malformed argument, or an event the schema refuses (exit 2)."""


def log_path(explicit=None):
    if explicit:
        return Path(explicit)
    for var in (PRIMARY_LOG_ENV, LOG_ENV):
        if os.environ.get(var):
            return Path(os.environ[var])
    return Path(DEFAULT_LOG)


def secret_hits(text):
    """Names of the credential shapes in text — never the matched text itself."""
    hits = set(_decisions.secret_hits(text))
    if URL_CREDENTIAL_RE.search(text):
        hits.add("url-credential")
    return sorted(hits)


def redact(value):
    """Every string in a report, credential shapes replaced by their name (#603: logs written
    by hand or by an older producer reach the report too; emit refuses them up front)."""
    if isinstance(value, dict):
        return {redact(k): redact(v) for k, v in value.items()}  # a model name is a key
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    for name, pattern in _decisions.SECRET_SHAPES:
        value = pattern.sub(f"[REDACTED:{name}]", value)
    return URL_CREDENTIAL_RE.sub("[REDACTED:url-credential]@", value)


# ---------------------------------------------------------------------------- schema

def _text(value, name, pattern=None, limit=MAX_TEXT_BYTES, strict=True):
    """A one-line string. `strict` (writing) refuses a credential shape; reading does not —
    the record already holds it, so the report redacts it instead of failing the run."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value.encode("utf-8")) > limit:
        raise ValueError(f"{name} exceeds {limit} bytes")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{name} may not carry a control character (one event, one line)")
    hits = secret_hits(value) if strict else []
    if hits:
        raise ValueError(f"{name} carries a credential shape ({', '.join(hits)}); the record is "
                         "permanent, so the event is refused")
    if pattern is not None and not pattern.fullmatch(value):
        raise ValueError(f"{name} {value!r} is not an identifier ({pattern.pattern})")
    return value


def _int(value, name, low):
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise ValueError(f"{name} must be an integer >= {low}")
    return value


def _typed(kind_type, value, name, strict=True):
    if kind_type == "id":
        return _text(value, name, ID_RE, strict=strict)
    if kind_type == "text":
        return _text(value, name, None, 256, strict=strict)
    if kind_type == "pos":
        return _int(value, name, 1)
    if kind_type == "count":
        return _int(value, name, 0)
    if kind_type == "sha":
        if not isinstance(value, str) or not SHA_RE.fullmatch(value):
            raise ValueError(f"{name} must be a full lowercase commit/tree id")
        return value
    if kind_type == "verdict":
        if value not in VERDICTS:
            raise ValueError(f"{name} must be one of {list(VERDICTS)}")
        return value
    if kind_type == "money":
        if not isinstance(value, str) or not MONEY_RE.fullmatch(value):
            raise ValueError(f"{name} must be a non-negative decimal string like '0.42'")
        return value
    if kind_type == "ids":
        if not isinstance(value, list) or not value:
            raise ValueError(f"{name} must be a non-empty list of ids")
        if len(set(value)) != len(value):
            raise ValueError(f"{name} names an id twice")
        return sorted(_text(v, name, ID_RE, strict=strict) for v in value)
    raise ValueError(f"unknown field type {kind_type}")


def normalize(event, strict=True):
    """The event in canonical form, or ValueError. Optional data keys absent and null are one
    value (null), so a re-delivery that omits them is still the same event."""
    if not isinstance(event, dict):
        raise ValueError("an event is a JSON object")
    unknown = sorted(set(event) - set(FIELDS))
    if unknown:
        raise ValueError(f"unknown field(s) {unknown}")
    if event.get("v") != RECORD_VERSION:
        raise ValueError(f"v must be {RECORD_VERSION}")
    kind = event.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} is not one of {sorted(KINDS)}")
    task_req, dispatch_req, spec = KINDS[kind]
    out = {"v": RECORD_VERSION, "kind": kind,
           "event_id": _text(event.get("event_id"), "event_id", ID_RE, strict=strict),
           "run": _text(event.get("run"), "run", ID_RE, strict=strict)}
    for key, required in (("task", task_req), ("dispatch", dispatch_req)):
        value = event.get(key)
        if value is None and required:
            raise ValueError(f"{kind} binds a {key}")
        out[key] = None if value is None else _text(value, key, ID_RE, strict=strict)
    out["epoch"] = _int(event.get("epoch"), "epoch", 1)
    out["producer"] = _text(event.get("producer"), "producer", ID_RE, strict=strict)
    out["clock"] = _text(event.get("clock"), "clock", ID_RE, strict=strict)
    if event.get("basis") not in BASES:
        raise ValueError(f"basis must be one of {list(BASES)}")
    out["basis"] = event["basis"]
    out["observed_at"] = _egress.valid_ts(event.get("observed_at"))
    source = event.get("source")
    if not isinstance(source, dict) or set(source) != {"ref", "sha256"}:
        raise ValueError("source must be {ref, sha256}")
    digest = source["sha256"]
    if digest is not None and not (isinstance(digest, str) and HEX64_RE.fullmatch(digest)):
        raise ValueError("source.sha256 must be 64 lowercase hex characters or null")
    out["source"] = {"ref": _text(source["ref"], "source.ref", strict=strict), "sha256": digest}
    data = event.get("data")
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    extra = sorted(set(data) - set(spec))
    if extra:
        raise ValueError(f"{kind} data carries unknown key(s) {extra}")
    out["data"] = {}
    for key, (kind_type, required) in sorted(spec.items()):
        value = data.get(key)
        if value is None:
            if required:
                raise ValueError(f"{kind} data requires {key}")
            out["data"][key] = None
        else:
            out["data"][key] = _typed(kind_type, value, f"data.{key}", strict)
    return out


def _canonical(fields):
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def identity(event):
    """What an observation SAYS — the bytes a re-delivery is compared by (PR #638 review, P1).

    Recording metadata is left out: `epoch` names the coordinator that recorded it, and a
    resumed coordinator re-ingesting the same DB rows is not contesting them; `observed_at`
    is when it was recorded unless `basis` is `occurred` (the store's own time of the fact),
    so re-ingesting an unchanged stream later is a duplicate, not a conflict."""
    said = {k: event[k] for k in FIELDS if k not in ("epoch", "observed_at", "basis")}
    said["occurred_at"] = event["observed_at"] if event["basis"] == "occurred" else None
    return _canonical(said)


def content_id(event):
    """A deterministic event_id for a producer that supplies none: the same observation
    re-emitted — by any coordinator epoch — gets the same id, so it dedups. Its time stays in
    the id: without an id, the time is all that tells two genuinely repeated facts apart."""
    return "content:" + sha256_hex(_canonical({k: event[k] for k in FIELDS
                                               if k not in ("epoch", "event_id")}))


def build_event(kind, run, *, epoch, producer, clock, observed_at, basis="observed",
                source_ref, source_sha256=None, task=None, dispatch=None, data=None,
                event_id=None):
    event = {"v": RECORD_VERSION, "kind": kind, "run": run, "task": task, "dispatch": dispatch,
             "epoch": epoch, "producer": producer, "clock": clock, "basis": basis,
             "observed_at": observed_at, "data": data or {},
             "source": {"ref": source_ref, "sha256": source_sha256}, "event_id": event_id or "x"}
    event = normalize(event)
    if event_id is None:
        event["event_id"] = content_id(event)
    return event


# ---------------------------------------------------------------------------- the record

def append_events(path, events):
    """Append each event the record does not already hold. [(event_id, status)], status
    appended | duplicate (same id, same body: skipped) | conflict (same id, different body:
    recorded — dropping an observation is not this tool's call — and contested at report)."""
    try:
        path.parent.mkdir(mode=stat.S_IRWXU, parents=True, exist_ok=True)
        with open(path, "a+", encoding="utf-8",
                  opener=lambda name, flags: os.open(name, flags, stat.S_IRUSR | stat.S_IWUSR)) as fh:
            # Every cooperating writer holds this lock from the read through the flush, so the
            # dedup map and the chain tail are the record as it stands.
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            fh.seek(0)
            lines = [ln for ln in fh.read().split("\n") if ln]
            known = {}
            for raw in lines:
                try:
                    rec = json.loads(raw)
                    known.setdefault(rec["event_id"], identity({k: rec.get(k) for k in FIELDS}))
                except (ValueError, TypeError, KeyError):
                    continue  # verify/report fail such a line closed; it cannot dedup anything
            previous = lines[-1] if lines else None
            out = []
            for event in events:
                seen = known.get(event["event_id"])
                if seen == identity(event):
                    out.append((event["event_id"], "duplicate"))
                    continue
                record = dict(event, prev="" if previous is None else sha256_hex(previous))
                raw = json.dumps(record, sort_keys=True, separators=(",", ":"))
                fh.write(raw + "\n")
                previous = raw
                known.setdefault(event["event_id"], identity(event))
                out.append((event["event_id"], "appended" if seen is None else "conflict"))
            fh.flush()
    except UnicodeDecodeError as err:
        raise EventsError(f"{path} is not valid UTF-8: {err}") from err
    except OSError as err:
        raise EventsError(f"event could not be written to {path}: {err}") from err
    return out


def _instant(observed_at):
    return datetime.fromisoformat(observed_at).astimezone(timezone.utc)


def read_log(path):
    """(events, file sha256, head digest). Fails closed on anything that is not an intact
    chain of schema-valid events: a report over a damaged record would be a guess."""
    try:
        data = path.read_bytes()
    except FileNotFoundError as err:
        raise EventsError(f"{path}: no event record") from err
    except OSError as err:
        raise EventsError(f"{path} is unreadable: {err}") from err
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as err:
        raise EventsError(f"{path} is not valid UTF-8: {err}") from err
    events, previous = [], None
    for lineno, raw in enumerate([ln for ln in text.split("\n") if ln], 1):
        try:
            record = json.loads(raw)
        except ValueError:
            record = None
        if not isinstance(record, dict) or not isinstance(record.get("prev"), str):
            raise EventsError(f"{path}:{lineno}: unparseable line or missing prev")
        expected = "" if previous is None else sha256_hex(previous)
        if record["prev"] != expected:
            raise EventsError(f"{path}:{lineno}: prev does not match the previous raw line — the "
                              "record was edited, reordered or truncated")
        try:
            event = normalize({k: v for k, v in record.items() if k != "prev"}, strict=False)
        except ValueError as err:
            raise EventsError(f"{path}:{lineno}: {err}") from err
        event.update(_pos=lineno, _digest=sha256_hex(raw), _at=_instant(event["observed_at"]))
        events.append(event)
        previous = raw
    return events, sha256_hex(data), ("" if previous is None else sha256_hex(previous))


def check_anchor(events, head, expect_head=None, expect_ancestor=None):
    """None, or why the record does not match a head kept off the writer (#312's rule)."""
    if expect_ancestor is not None:
        want = expect_ancestor.strip().lower()
        if want and want not in {e["_digest"] for e in events}:
            return (f"the anchored head {want} is not in this record — a rewritten or truncated "
                    "record loses the anchored line")
    if expect_head is not None and expect_head.strip().lower() != head:
        return (f"the record's head is {head or '(empty)'}, not the anchored "
                f"{expect_head.strip().lower() or '(empty)'}")
    return None


# ---------------------------------------------------------------------------- derivation

def _na(reasons):
    return {"value": None, UNAVAILABLE: sorted(set(reasons))}


def _decimal(frac, places=2):
    with localcontext() as ctx:
        ctx.prec = 60
        value = Decimal(frac.numerator) / Decimal(frac.denominator)
        return str(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN))


def _minutes(seconds):
    return _decimal(seconds / 60) + "m"


def _median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _short(sha):
    return sha[:12] if sha else "(unnamed head)"


def interval(start, end, what):
    """(seconds, None) or (None, why). Same clock, no recovered endpoint, never negative."""
    if start["clock"] != end["clock"]:
        return None, (f"{what}: {start['kind']} and {end['kind']} are on different clocks "
                      f"({start['clock']}, {end['clock']}); no common clock, no interval")
    for event in (start, end):
        if event["basis"] == "recovered":
            return None, (f"{what}: {event['kind']} was recovered after a coordinator resume, so "
                          "its time is when it was rebuilt, not when it happened")
    delta = end["_at"] - start["_at"]
    seconds = Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 10**6)
    if seconds < 0:
        return None, (f"{what}: negative on clock {start['clock']} ({_decimal(seconds)}s) — the "
                      "clock stepped back or the events are misattributed; never clamped to 0")
    return seconds, None


def first(events, what):
    """The first observation of one fact seen more than once: (event, None) or (None, why)."""
    if len(events) == 1:
        return events[0], None
    if len({e["clock"] for e in events}) > 1:
        return None, (f"{what}: {len(events)} observations on different clocks; none is "
                      "provably first")
    return min(events, key=lambda e: (e["_at"], e["_pos"])), None


def _scope(event):
    if event["kind"] in DECLARES_EPOCH:
        return ("run",)
    if event["kind"] in ("wave.open", "wave.close"):
        return ("wave", event["data"]["wave"])
    if event["kind"] == "model.usage":
        return ("usage",)
    return ("unit", event["task"])


def screen(events):
    """Dedup, then fence, in record order. Returns (kept, duplicates, conflicts, fenced, epochs,
    taints) where taints maps a scope to the reasons its metrics are unavailable."""
    by_id, kept, duplicates, conflicts, taints = {}, [], 0, [], {}

    def taint(event, why):
        taints.setdefault(_scope(event), []).append(why)

    for event in events:
        seen = by_id.get(event["event_id"])
        if seen is None:
            by_id[event["event_id"]] = event
            kept.append(event)
        elif identity(seen) == identity(event):
            duplicates += 1
        else:
            conflicts.append({"event_id": event["event_id"], "kept": seen["_digest"],
                              "conflicting": event["_digest"]})
            why = (f"event_id {event['event_id']} delivered twice with different bodies "
                   "(contested observation)")
            taint(seen, why)
            taint(event, why)
    declared, screened, fenced, epochs = 0, [], [], []
    for event in kept:
        if event["kind"] in DECLARES_EPOCH:
            if event["epoch"] <= declared:
                why = (f"{event['kind']} declares epoch {event['epoch']} after epoch {declared} "
                       "was declared — a stale or duplicate coordinator")
                fenced.append({"digest": event["_digest"], "epoch": event["epoch"],
                               "declared": declared, "reason": why})
                taint(event, why)
                continue
            declared = event["epoch"]
            epochs.append({"epoch": event["epoch"], "kind": event["kind"],
                           "coordinator": event["data"]["coordinator"],
                           "clock": event["clock"], "digest": event["_digest"]})
            screened.append(event)
            continue
        if event["epoch"] != declared:
            if event["epoch"] < declared:
                why = (f"{event['kind']} recorded under epoch {event['epoch']} after epoch "
                       f"{declared} was declared — a fenced coordinator's write")
            else:
                why = (f"{event['kind']} recorded under epoch {event['epoch']}, which no "
                       "run.start or coordinator.resume declared before it")
            fenced.append({"digest": event["_digest"], "epoch": event["epoch"],
                           "declared": declared, "reason": why})
            taint(event, why)
            continue
        screened.append(event)
    return screened, duplicates, conflicts, fenced, epochs, taints


def derive_unit(task, wave, events):
    """One planned unit's outcome and per-unit measurements, from the set of its events."""
    by = {kind: [] for kind in KINDS}
    for event in events:
        by[event["kind"]].append(event)
    contested = []
    launched = {e["dispatch"] for e in by["dispatch.launched"]}
    seen = launched | {e["dispatch"] for e in by["task.done"] + by["dispatch.died"]}
    passes = [e for e in by["verify.verdict"] if e["data"]["exit"] == 0]
    closes = by["unit.closed"]
    close_heads = sorted({e["data"]["head_sha"] for e in closes})
    if len(close_heads) > 1:
        contested.append(f"unit {task}: closed at {len(close_heads)} different heads")
    close_head = close_heads[0] if len(close_heads) == 1 else None
    close_trees = {e["data"]["head_wtree"] for e in closes if e["data"]["head_wtree"]}
    if len(close_trees) > 1:
        contested.append(f"unit {task}: closed with {len(close_trees)} different trees")
    close_tree = close_trees.pop() if len(close_trees) == 1 else None
    if closes:
        verified = close_head is not None and any(p["data"]["head_sha"] == close_head for p in passes)
        outcome = "verified-closed" if verified else "closed-unverified"
    elif by["unit.parked"]:
        outcome = "parked"
    elif passes:
        outcome = "verified"
    elif by["task.done"]:
        outcome = "completed"
    else:
        outcome = "open"

    # Verification latency: the worker_done at a head, to the first passing verdict AT THAT HEAD
    # (or to the park) — bound by SHA, so record order never picks the endpoints. A conductor's
    # content-identical rebase re-verifies a head no worker reported, so the close head is not
    # the binding: the head a worker reported done and a verdict passed is.
    latency = {"seconds": None, "unavailable": None, "excluded": None}
    head, ends = None, []
    if outcome in ("verified-closed", "verified"):
        done_heads = {d["data"]["head_sha"] for d in by["task.done"] if d["data"]["head_sha"]}
        heads = sorted({p["data"]["head_sha"] for p in passes} & done_heads)
        if len(heads) == 1:
            head = heads[0]
            ends = [p for p in passes if p["data"]["head_sha"] == head]
        elif not by["task.done"]:
            latency["unavailable"] = f"unit {task}: verified without an observed worker_done"
        else:
            latency["unavailable"] = (f"unit {task}: a passing verdict at {len(heads)} head(s) a "
                                      "worker reported done; which pair is its latency is ambiguous")
    elif outcome == "parked":
        ends = by["unit.parked"]
        park_heads = {p["data"]["head_sha"] for p in ends}
        head = park_heads.pop() if len(park_heads) == 1 else None
    else:
        latency["unavailable"] = f"unit {task}: no verified-or-parked observation ({outcome})"
    if ends and not latency["unavailable"]:
        dones = by["task.done"]
        starts = [d for d in dones if d["data"]["head_sha"] == head] if head else dones
        if not starts and outcome == "parked" and not dones:
            latency["excluded"] = f"unit {task}: parked with no worker_done, so it has no latency"
        elif not starts:
            latency["unavailable"] = f"unit {task}: no worker_done observed at {_short(head)}"
        elif len({d["data"]["head_sha"] for d in starts}) > 1:
            latency["unavailable"] = (f"unit {task}: worker_done at several heads and the park "
                                      "names none; which one it ends is ambiguous")
        else:
            start, why = first(starts, f"unit {task} worker_done")
            end, why_end = first(ends, f"unit {task} {ends[0]['kind']}")
            if why or why_end:
                latency["unavailable"] = why or why_end
            else:
                latency["seconds"], latency["unavailable"] = interval(start, end, f"unit {task} latency")

    # Review queue: worker_done at a head -> the review of that head starting.
    queue = []
    started = {}
    for event in by["review.started"]:
        started.setdefault(event["data"]["head_sha"], []).append(event)
    for sha in sorted(started):
        dones = [d for d in by["task.done"] if d["data"]["head_sha"] == sha]
        if not dones:
            queue.append((None, f"unit {task}: review started at {_short(sha)} with no "
                                "worker_done observed at that head"))
            continue
        start, why = first(dones, f"unit {task} worker_done")
        end, why_end = first(started[sha], f"unit {task} review.started")
        queue.append((None, why or why_end) if (why or why_end)
                     else interval(start, end, f"unit {task} review queue"))

    # Freshness: approving reviews voided by a head that moved (reviewed-sha-freshness.md: the
    # SHA check is the default; equal trees on both sides are the one equivalence class).
    approvals = [r for r in by["review.verdict"] if r["data"]["verdict"] == "approve"]
    voided = {v["data"]["reviewed_sha"] for v in by["review.voided"]}
    if close_head:
        for review in approvals:
            tree = review["data"]["reviewed_wtree"]
            if review["data"]["reviewed_sha"] != close_head and not (tree and tree == close_tree):
                voided.add(review["data"]["reviewed_sha"])

    return {
        "task": task, "wave": wave, "outcome": outcome,
        "task_completed": bool(by["task.done"]),
        "park_classes": sorted({p["data"]["park_class"] for p in by["unit.parked"]}),
        "dispatches": sorted(seen), "unlaunched": sorted(seen - launched),
        "bounced": bool(by["unit.suspect"]) or any(v["data"]["exit"] == 2
                                                    for v in by["verify.verdict"]),
        "approvals": len(approvals), "voided_reviews": sorted(voided),
        "latency": latency, "queue": queue, "contested": contested,
        "revisions": {"closed_at": close_head, "closed_tree": close_tree,
                      "verified_at": sorted({p["data"]["head_sha"] for p in passes
                                             if p["data"]["head_sha"]}),
                      "done_at": sorted({d["data"]["head_sha"] for d in by["task.done"]
                                         if d["data"]["head_sha"]}),
                      "reviewed": sorted({r["data"]["reviewed_sha"] for r in by["review.verdict"]})},
        "events": [{"kind": e["kind"], "digest": e["_digest"], "source": e["source"]}
                   for e in sorted(events, key=lambda e: e["_pos"])],
    }


def wave_metrics(k, opened, closed, units):
    """Each WIP-curve metric of one wave, or the reasons the record cannot support it."""
    metrics = {}
    reasons = []
    wall = None
    if opened is None:
        reasons.append(f"wave {k}: wave.open not observed")
    if closed is None:
        reasons.append(f"wave {k}: wave.close not observed, so the wall-clock is unknown")
    if opened is not None and closed is not None:
        wall, why = interval(opened, closed, f"wave {k} wall-clock")
        if why:
            reasons.append(why)
        elif wall == 0:
            reasons.append(f"wave {k}: zero wall-clock")
    if not units:
        reasons.append(f"wave {k}: no planned unit")
    pending = [u["task"] for u in units if u["outcome"] not in CLOSED_OR_PARKED]
    if pending:
        reasons.append(f"wave {k}: {pending} not observed CLOSED or parked — a pending or "
                       "unrecorded close would change the count")
    closed_n = sum(u["outcome"] == "verified-closed" for u in units)
    metrics["throughput"] = _na(reasons) if reasons else {
        "value": _decimal(Fraction(closed_n * 3600) / wall) + "/h",
        "verified_closed": closed_n, "wall_clock_s": str(wall)}

    lat, lat_reasons = [], []
    for unit in units:
        latency = unit["latency"]
        if latency["excluded"]:
            continue
        if latency["seconds"] is None:
            lat_reasons.append(latency["unavailable"])
        else:
            lat.append(latency["seconds"])
    if not lat and not lat_reasons:
        lat_reasons.append(f"wave {k}: no unit reached verified-or-parked after an observed "
                           "worker_done")
    if lat_reasons:
        metrics["latency_median"] = metrics["latency_max"] = _na(lat_reasons)
    else:
        metrics["latency_median"] = {"value": _minutes(_median(lat)), "units": len(lat)}
        metrics["latency_max"] = {"value": _minutes(max(lat)), "units": len(lat)}

    open_units = [u["task"] for u in units if u["outcome"] not in LEFT_DISPATCHED]
    if not units:
        metrics["rework"] = _na([f"wave {k}: no planned unit"])
    elif open_units:
        metrics["rework"] = _na([f"wave {k}: {open_units} not yet verified or parked — a later "
                                 "bounce could still land"])
    else:
        bounced = sum(u["bounced"] for u in units)
        metrics["rework"] = {"value": f"{bounced}/{len(units)}", "bounced": bounced,
                             "units": len(units)}

    if not units:
        fresh_reasons = [f"wave {k}: no planned unit"]
    elif pending:
        fresh_reasons = [f"wave {k}: {pending} not closed or parked; a review is voided at "
                         "merge, which has not happened yet"]
    else:
        fresh_reasons = [f"unit {u['task']}: closed with no approving review observed, so its "
                         "freshness cannot be judged" for u in units
                         if u["outcome"] in ("verified-closed", "closed-unverified")
                         and not u["approvals"]]
    metrics["freshness"] = _na(fresh_reasons) if fresh_reasons else {
        "value": str(sum(len(u["voided_reviews"]) for u in units))}

    queue = [pair for u in units for pair in u["queue"]]
    queue_reasons = [why for secs, why in queue if secs is None]
    if not queue:
        queue_reasons = [f"wave {k}: no review.started observed"]
    if queue_reasons:
        metrics["review_queue_median"] = metrics["review_queue_max"] = _na(queue_reasons)
    else:
        values = [secs for secs, _ in queue]
        metrics["review_queue_median"] = {"value": _minutes(_median(values)), "reviews": len(values)}
        metrics["review_queue_max"] = {"value": _minutes(max(values)), "reviews": len(values)}

    retry_reasons = [f"unit {u['task']}: no dispatch observed" for u in units if not u["dispatches"]]
    retry_reasons += [f"unit {u['task']}: dispatch(es) {u['unlaunched']} reported without an "
                      "observed launch" for u in units if u["unlaunched"]]
    if not units:
        retry_reasons = [f"wave {k}: no planned unit"]
    metrics["retries"] = _na(retry_reasons) if retry_reasons else {
        "value": str(sum(len(u["dispatches"]) - 1 for u in units))}
    return metrics


def _zero(field):
    return Decimal(0) if field == "cost_usd" else 0


def usage_summary(events, dispatches, tainted):
    """Observed model usage. A field any observation left unreported is null, with the
    observations' own provenance — never zero, never a partial sum presented as a total."""
    models = {}
    for event in events:
        name = event["data"]["model"] or "(unreported)"
        agg = models.setdefault(name, {"observations": 0, "provenance": set(),
                                       "fields": {f: [_zero(f), 0] for f in USAGE_FIELDS}})
        agg["observations"] += 1
        agg["provenance"].add(event["data"]["provenance"])
        for field in USAGE_FIELDS:
            value = event["data"][field]
            if value is None:
                agg["fields"][field][1] += 1
            else:
                agg["fields"][field][0] += Decimal(value) if field == "cost_usd" else value
    out_models = {}
    totals = {f: [_zero(f), []] for f in USAGE_FIELDS}
    for name in sorted(models):
        agg = models[name]
        entry = {"observations": agg["observations"], "provenance": sorted(agg["provenance"])}
        for field in USAGE_FIELDS:
            known, unknown = agg["fields"][field]
            shown = format(known, "f") if field == "cost_usd" else known
            if unknown:
                # A sum over zero reports is not a 0: with nothing reported it stays null too.
                partial = shown if unknown < agg["observations"] else None
                entry[field] = {"value": None, "known_sum": partial,
                                UNAVAILABLE: f"{unknown} of {agg['observations']} observation(s) "
                                             "did not report it"}
                totals[field][1].append(f"model {name}: {unknown} observation(s) did not report it")
            else:
                entry[field] = {"value": shown}
            totals[field][0] += known
        out_models[name] = entry
    covered = {e["dispatch"] for e in events if e["dispatch"]}
    unobserved = sorted(set(dispatches) - covered)
    run_total = {}
    for field in USAGE_FIELDS:
        reasons = list(totals[field][1])
        if unobserved:
            reasons.append(f"{len(unobserved)} dispatch(es) have no usage observation")
        if not events:
            reasons.append("no model.usage observed")
        reasons += tainted
        known = totals[field][0]
        run_total[field] = _na(reasons) if reasons else {
            "value": format(known, "f") if field == "cost_usd" else known}
    return {"models": out_models, "unobserved_dispatches": unobserved, "run_total": run_total}


def _row_text(k, opened, metrics):
    data = opened["data"] if opened else {}
    builders = data.get("builders", UNAVAILABLE)
    reviewers = data.get("reviewers", UNAVAILABLE)
    cell = {m: metrics[m]["value"] or UNAVAILABLE for m in ROW_METRICS}
    return (f"| `wave={k}` | `builders={builders} reviewers={reviewers}` | "
            f"`throughput={cell['throughput']}` | `latency_median={cell['latency_median']} "
            f"latency_max={cell['latency_max']}` | `rework={cell['rework']}` | "
            f"`freshness={cell['freshness']}` |")


def place(event, ks, boundary):
    """(wave, None) or (None, why): which of the waves planning a task this event belongs to.

    PR #638 review (P1): a unit parked in wave 1 and re-planned, retried and closed in wave 2
    is two measurements, not one wave-1 close. Each event belongs to the latest planning wave
    whose wave.open it does not precede — compared on one clock, never by record order. An
    event no window can hold (another clock, a recovered time, an unknown wave.open) is not
    guessed into one: the unit is unavailable in every wave that plans it."""
    if len(ks) == 1:
        return ks[0], None
    what = f"unit {event['task']}: {event['kind']} cannot be placed in wave {ks[0]}..{ks[-1]}"
    if event["basis"] == "recovered":
        return None, f"{what} — its time is when it was rebuilt, not when it happened"
    placed = ks[0]
    for k in ks[1:]:
        opened = boundary.get(k)
        if opened is None:
            return None, f"{what} — wave {k}'s wave.open is not observed on one clock"
        if opened["clock"] != event["clock"]:
            return None, (f"{what} — it is on clock {event['clock']}, wave {k}'s wave.open on "
                          f"{opened['clock']}")
        if event["_at"] >= opened["_at"]:
            placed = k
    return placed, None


def derive(events, run=None, file_sha="", head=""):
    """The whole report for one run of the record. Deterministic: no clock, no environment,
    no path — the same events derive the same bytes."""
    runs = sorted({e["run"] for e in events})
    if run is None:
        if len(runs) != 1:
            raise UsageError(f"the record holds {len(runs)} run(s) {runs}; pass --run")
        run = runs[0]
    mine = [e for e in events if e["run"] == run]
    if not mine:
        raise UsageError(f"the record holds no event for run {run!r} (runs: {runs})")
    kept, duplicates, conflicts, fenced, epochs, taints = screen(mine)
    if not epochs:
        taints.setdefault(("run",), []).append("no run.start observed, so no coordinator "
                                               "epoch was ever declared")
    opens, closes = {}, {}
    for event in kept:
        if event["kind"] == "wave.open":
            opens.setdefault(event["data"]["wave"], []).append(event)
        elif event["kind"] == "wave.close":
            closes.setdefault(event["data"]["wave"], []).append(event)
    plan = {}  # task -> every wave whose plan lists it, ascending
    for k in sorted(opens):
        plans = {json.dumps(e["data"], sort_keys=True) for e in opens[k]}
        if len(plans) > 1:
            taints.setdefault(("wave", k), []).append(f"wave {k} opened with {len(plans)} "
                                                      "different plans")
        for task in opens[k][0]["data"]["tasks"]:
            plan.setdefault(task, []).append(k)
    carried = [{"task": t, "waves": ks} for t, ks in sorted(plan.items()) if len(ks) > 1]
    lifecycle = {}
    for event in kept:
        if event["task"] is not None and event["kind"] != "model.usage":
            lifecycle.setdefault(event["task"], []).append(event)
    boundary = {k: first(opens[k], f"wave {k} wave.open")[0] for k in opens}
    units = {}  # (task, wave) -> that wave's own measurement of the unit
    for task, ks in sorted(plan.items()):
        parts = {k: [] for k in ks}
        for event in lifecycle.get(task, []):
            k, why = place(event, ks, boundary)
            if why:
                taints.setdefault(("unit", task), []).append(why)
            else:
                parts[k].append(event)
        for k in ks:  # a planned unit never observed is open, not missing
            units[(task, k)] = derive_unit(task, k, parts[k])
    unplanned = [{"task": t, "events": len(evs)} for t, evs in sorted(lifecycle.items())
                 if t not in plan]
    waves = []
    for k in range(1, max(list(opens) + list(closes), default=0) + 1):
        wave_units = [units[key] for key in sorted(units) if key[1] == k]
        opened, why_open = first(opens[k], f"wave {k} wave.open") if k in opens else (None, None)
        closed, why_close = first(closes[k], f"wave {k} wave.close") if k in closes else (None, None)
        metrics = wave_metrics(k, opened, closed, wave_units)
        if why_open or why_close:
            metrics["throughput"] = _na([why_open or why_close])
        reasons = list(taints.get(("run",), [])) + list(taints.get(("wave", k), []))
        for unit in wave_units:
            reasons += taints.get(("unit", unit["task"]), []) + unit["contested"]
        if reasons:
            metrics = {name: _na(reasons) for name in metrics}
        outcomes = {name: sum(u["outcome"] == name for u in wave_units)
                    for name in ("verified-closed", "closed-unverified", "parked", "verified",
                                 "completed", "open")}
        outcomes["task_completed"] = sum(u["task_completed"] for u in wave_units)
        waves.append({
            "wave": k,
            "builders": opened["data"]["builders"] if opened else None,
            "reviewers": opened["data"]["reviewers"] if opened else None,
            "row": _row_text(k, opened, metrics),
            "metrics": metrics, "outcomes": outcomes,
            "units": [_unit_view(u) for u in wave_units],
        })
    dispatches = sorted({e["dispatch"] for e in kept if e["dispatch"]
                         and e["kind"] in ("dispatch.launched", "task.done", "dispatch.died")})
    usage = usage_summary([e for e in kept if e["kind"] == "model.usage"], dispatches,
                          taints.get(("usage",), []) + taints.get(("run",), []))
    report = {
        "schema": REPORT_SCHEMA, "run": run,
        "record": {"log_sha256": file_sha, "head": head, "lines": len(events),
                   "run_events": len(kept), "duplicates": duplicates,
                   "conflicts": len(conflicts), "fenced": len(fenced),
                   "other_run_events": len(events) - len(mine)},
        "epochs": epochs, "conflicts": conflicts, "fenced": fenced,
        "waves": waves, "unplanned": unplanned, "carried": carried, "usage": usage,
    }
    report["complete"] = bool(waves) and all(
        w["metrics"][m]["value"] is not None for w in waves for m in ROW_METRICS)
    return redact(report)


def _unit_view(unit):
    latency = unit["latency"]
    if latency["seconds"] is not None:
        shown = {"value": _minutes(latency["seconds"]), "seconds": str(latency["seconds"])}
    elif latency["excluded"]:
        shown = {"value": None, "excluded": latency["excluded"]}
    else:
        shown = _na([latency["unavailable"]])
    return {"task": unit["task"], "outcome": unit["outcome"],
            "task_completed": unit["task_completed"], "park_classes": unit["park_classes"],
            "dispatches": unit["dispatches"], "bounced": unit["bounced"],
            "voided_reviews": unit["voided_reviews"], "latency": shown,
            "revisions": unit["revisions"], "events": unit["events"]}


def render_markdown(report):
    lines = ["| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | "
             "Freshness violations |", "|---|---|---|---|---|---|"]
    lines += [w["row"] for w in report["waves"]]
    rec = report["record"]
    lines += ["", f"Derived by `events.py report` for run `{report['run']}` from "
                  f"{rec['run_events']} admitted event(s) of {rec['lines']} line(s) "
                  f"({rec['duplicates']} duplicate(s) collapsed, "
                  f"{rec['conflicts']} conflict(s), {rec['fenced']} fenced) — record sha256 "
                  f"`{rec['log_sha256']}`, head `{rec['head'] or '(empty)'}`."]
    missing = [(w["wave"], m, why) for w in report["waves"] for m in ROW_METRICS
               if w["metrics"][m]["value"] is None for why in w["metrics"][m][UNAVAILABLE]]
    if not report["waves"]:
        lines += ["", "No wave.open observed: the record carries no WIP-curve row."]
    if missing:
        lines += ["", "Unavailable — the record does not support a measured value, and none was "
                      "estimated:"]
        lines += [f"- wave {k} `{m}`: {why}" for k, m, why in missing]
    return "\n".join(lines) + "\n"


def derived_cells(report):
    """{wave: {key: value}} in run_report.py's WIP_ROW_KEYS vocabulary."""
    out = {}
    for wave in report["waves"]:
        cells = {"wave": str(wave["wave"]),
                 "builders": UNAVAILABLE if wave["builders"] is None else str(wave["builders"]),
                 "reviewers": UNAVAILABLE if wave["reviewers"] is None else str(wave["reviewers"])}
        for metric in ROW_METRICS:
            cells[metric] = wave["metrics"][metric]["value"] or UNAVAILABLE
        out[wave["wave"]] = cells
    return out


# ---------------------------------------------------------------------------- commands

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_sha(path_text):
    try:
        return sha256_hex(Path(path_text).read_bytes())
    except OSError as err:
        raise UsageError(f"{path_text} is unreadable: {err}") from err


def _record(args, events):
    """Validate-then-append; prints one status line per event. Conflicts exit 1."""
    results = append_events(log_path(args.log), events)
    for event_id, status in results:
        print(f"{status} {event_id}")
    if any(status == "conflict" for _id, status in results):
        print("events: an event_id was re-used with a different body; the report will mark the "
              "observations it touches contested", file=sys.stderr)
        return EXIT_INCOMPLETE
    return EXIT_OK


def _build(args, kind, **kw):
    try:
        return build_event(kind, args.run, epoch=args.epoch, producer=kw.pop("producer"),
                           clock=args.clock, **kw)
    except ValueError as err:
        raise UsageError(str(err)) from err


def cmd_emit(args):
    try:
        data = json.loads(args.data) if args.data else {}
    except ValueError as err:
        raise UsageError(f"--data is not JSON: {err}") from err
    digest = args.source_sha256
    if args.source_file:
        digest = _file_sha(args.source_file)
    event = _build(args, args.kind, producer=args.producer, task=args.task,
                   dispatch=args.dispatch, basis=args.basis,
                   observed_at=args.observed_at or _now(), source_ref=args.source_ref,
                   source_sha256=digest, data=data, event_id=args.event_id)
    return _record(args, [event])


def _db_time(value):
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec="microseconds")


def cmd_ingest_state(args):
    """Launches, worker_done mail and deaths of one run, read from the local-state DB through
    watchdog.py's strictly read-only connection. Ids are the rows' own, so re-ingesting the same
    DB records nothing new."""
    import sqlite3
    db = Path(args.db)
    if not db.is_file():
        raise UsageError(f"--db {db} is not a file")
    watchdog = _sibling("watchdog", "watchdog.py")
    try:
        conn = watchdog._ro_connect(db)
        try:
            rows = conn.execute("SELECT * FROM dispatches WHERE run_id = ? "
                                "ORDER BY created_at, dispatch_id", (args.run,)).fetchall()
            mail = conn.execute("SELECT id, sender, attrs_json, created_at FROM messages "
                                "WHERE run_id = ? AND msg_type = 'worker_done' "
                                "ORDER BY created_at, id", (args.run,)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as err:
        raise EventsError(f"{db} is not a readable local-state DB: {err}") from err
    events, by_id, by_handle, skipped = [], {}, {}, []
    common = {"producer": "local_state", "basis": "occurred"}
    for row in rows:
        keys = row.keys()
        by_handle.setdefault(row["terminal_handle"], []).append(row)
        agent = row["agent"] if ID_RE.fullmatch(row["agent"] or "") else None
        events.append(_build(args, "dispatch.launched", task=row["task_id"],
                             dispatch=row["dispatch_id"], observed_at=_db_time(row["created_at"]),
                             source_ref=f"local-state:dispatches/{row['dispatch_id']}",
                             data={"agent": agent},
                             event_id=f"local-state:dispatch:{row['dispatch_id']}", **common))
        if row["state"] == "died":
            events.append(_build(args, "dispatch.died", task=row["task_id"],
                                 dispatch=row["dispatch_id"],
                                 observed_at=_db_time(row["updated_at"]),
                                 source_ref=f"local-state:dispatches/{row['dispatch_id']}",
                                 event_id=f"local-state:died:{row['dispatch_id']}", **common))
        row_head = row["head_sha"] if "head_sha" in keys else None
        by_id[row["dispatch_id"]] = (row, row_head)
    for msg in mail:
        match = by_id.get(msg["sender"])
        handles = by_handle.get(msg["sender"], [])
        if match is None and len(handles) == 1:
            match = by_id[handles[0]["dispatch_id"]]
        if match is None:
            skipped.append(msg["id"])
            continue
        row, row_head = match
        try:
            attrs = json.loads(msg["attrs_json"] or "{}")
        except ValueError:
            attrs = {}
        attrs = attrs if isinstance(attrs, dict) else {}
        head = next((h for h in (attrs.get("headSha"), attrs.get("head_sha"), row_head)
                     if isinstance(h, str) and SHA_RE.fullmatch(h)), None)
        events.append(_build(args, "task.done", task=row["task_id"], dispatch=row["dispatch_id"],
                             observed_at=_db_time(msg["created_at"]),
                             source_ref=f"local-state:messages/{msg['id']}",
                             data={"head_sha": head},
                             event_id=f"local-state:message:{msg['id']}", **common))
    if skipped:
        print(f"events: {len(skipped)} worker_done message(s) name no single dispatch of run "
              f"{args.run} and were not recorded: {skipped}", file=sys.stderr)
    if not events:
        print(f"events: the DB holds no dispatch or worker_done for run {args.run}", file=sys.stderr)
        return EXIT_INCOMPLETE
    return _record(args, events)


def cmd_ingest_transcript(args):
    """verify.py's verdict object (or its signed envelope) as a verify.verdict event. The head
    comes from the manifest the verdict judged — and only when its bytes still hash to the
    transcript's manifest_sha256; otherwise the verdict binds no head."""
    path = Path(args.transcript)
    try:
        raw = path.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as err:
        raise UsageError(f"--transcript {path} is not a readable verify.py transcript: {err}") from err
    record = doc.get("record") if isinstance(doc, dict) and "sig_b64" in doc else doc
    if not isinstance(record, dict) or isinstance(record.get("exit"), bool) \
            or not isinstance(record.get("exit"), int) or not isinstance(record.get("timestamp"), str):
        raise UsageError(f"--transcript {path} carries no verify.py verdict (exit, timestamp)")
    head = None
    manifest = args.manifest or record.get("manifest")
    if manifest and isinstance(record.get("manifest_sha256"), str):
        try:
            mbytes = Path(manifest).read_bytes()
        except OSError:
            mbytes = None
        if mbytes is None or sha256_hex(mbytes) != record["manifest_sha256"]:
            print(f"events: {manifest} is absent or not the bytes the verdict judged; the verdict "
                  "is recorded without a head", file=sys.stderr)
        else:
            try:
                candidate = json.loads(mbytes.decode("utf-8")).get("head_sha")
            except (ValueError, AttributeError):
                candidate = None
            head = candidate if isinstance(candidate, str) and SHA_RE.fullmatch(candidate) else None
    digest = sha256_hex(raw)
    event = _build(args, "verify.verdict", producer="verify.py", task=args.task, basis="occurred",
                   observed_at=record["timestamp"], source_ref=args.transcript,
                   source_sha256=digest, data={"exit": record["exit"], "head_sha": head},
                   event_id=f"verify-transcript:{digest}")
    return _record(args, [event])


def _money(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return format(Decimal(str(value)), "f")


def cmd_ingest_usage(args):
    """Model usage from a Claude worker's stream-json log: the `system/init` line's model and
    each `result` line's `usage` and `total_cost_usd`. A field the line does not carry is
    recorded null and named in the provenance; nothing is ever recorded as zero by default."""
    path = Path(args.stream)
    try:
        raw = path.read_bytes()
    except OSError as err:
        raise UsageError(f"--stream {path} is unreadable: {err}") from err
    digest = sha256_hex(raw)
    model, events = None, []
    for lineno, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "system" and obj.get("subtype") == "init" \
                and isinstance(obj.get("model"), str) and ID_RE.fullmatch(obj["model"]):
            model = obj["model"]
        if obj.get("type") != "result":
            continue
        usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
        data = {"model": model}
        for field in TOKEN_FIELDS:
            value = usage.get(field)
            ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
            data[field] = value if ok else None
        data["cost_usd"] = _money(obj.get("total_cost_usd"))
        absent = [f for f in ("model",) + USAGE_FIELDS if data[f] is None]
        data["provenance"] = (f"claude stream-json result line {lineno} of sha256:{digest[:16]}"
                              + (f"; not reported: {', '.join(absent)}" if absent else ""))
        events.append(_build(args, "model.usage", producer="claude-stream-json", task=args.task,
                             dispatch=args.dispatch, observed_at=args.observed_at or _now(),
                             source_ref=args.stream, source_sha256=digest, data=data,
                             event_id=f"claude-stream:{digest}:{lineno}"))
    if not events:
        print(f"events: {path} carries no result line; usage for this dispatch stays unobserved",
              file=sys.stderr)
        return EXIT_INCOMPLETE
    return _record(args, events)


def _anchored(args, events, head):
    why = check_anchor(events, head, args.expect_head, args.expect_ancestor)
    if why:
        raise EventsError(f"TAMPER at {log_path(args.log)} — {why} (#312)")


def cmd_verify(args):
    path = log_path(args.log)
    events, _file, head = read_log(path)
    _anchored(args, events, head)
    note = "" if (args.expect_head or args.expect_ancestor) else (
        " (UNANCHORED: edits are caught, a wholesale rewrite is not — keep this head off the "
        "writer and pass it back as --expect-ancestor or --expect-head)")
    print(f"events: chain intact, {len(events)} event(s) in {path} — head {head or '(empty)'}{note}")
    return EXIT_OK


def cmd_report(args):
    events, file_sha, head = read_log(log_path(args.log))
    _anchored(args, events, head)
    report = derive(events, args.run, file_sha, head)
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render_markdown(report))
    return EXIT_OK if report["complete"] else EXIT_INCOMPLETE


def cmd_check(args):
    """A run report's WIP-curve rows, read by run_report.py's own parser, against the rows this
    record derives. A hand-edited cell, a row for a wave the record never opened, or a measured
    value the record cannot support is a disagreement."""
    events, file_sha, head = read_log(log_path(args.log))
    _anchored(args, events, head)
    report = derive(events, args.run, file_sha, head)
    try:
        text = Path(args.run_report).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise UsageError(f"--run-report {args.run_report} is unreadable: {err}") from err
    run_report = _sibling("run_report", "run_report.py")
    derived = derived_cells(report)
    errors, claimed = [], {}
    for row, cells, doubled in run_report._wip_rows(text):
        if doubled:
            errors.append(f"row {row!r} carries {doubled} more than once")
        claimed.setdefault(cells.get("wave"), []).append(cells)
    for wave, rows in sorted(claimed.items(), key=lambda kv: str(kv[0])):
        if len(rows) > 1:
            errors.append(f"wave {wave}: {len(rows)} rows")
        if not (wave or "").isdigit() or int(wave) not in derived:
            errors.append(f"wave {wave}: the report carries a row for a wave the record never "
                          "opened or closed")
    for k, cells in sorted(derived.items()):
        rows = claimed.get(str(k))
        if not rows:
            errors.append(f"wave {k}: the record derives a row the report does not carry")
            continue
        for key in run_report.WIP_ROW_KEYS:
            want, got = cells[key], rows[0].get(key)
            if want == UNAVAILABLE:
                errors.append(f"wave {k} {key}: the record cannot derive it, yet the report "
                              f"claims {got!r}")
            elif got != want:
                errors.append(f"wave {k} {key}: the report says {got!r}, the record derives {want!r}")
    for line in errors:
        print(f"events: MISMATCH {line}", file=sys.stderr)
    if errors:
        return EXIT_INCOMPLETE
    print(f"events: {len(derived)} WIP-curve row(s) in {args.run_report} match the record "
          f"(sha256 {file_sha}, head {head or '(empty)'})")
    return EXIT_OK


def _ts_arg(value):
    try:
        return _egress.valid_ts(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(str(err)) from err


def _binding(sub, task=False):
    sub.add_argument("--run", required=True, help="the run id (the ledger header's RUN)")
    sub.add_argument("--epoch", required=True, type=int,
                     help="the coordinator epoch recording this: 1, then +1 per coordinator.resume")
    sub.add_argument("--clock", required=True,
                     help="the clock domain the timestamps were read on, e.g. coordinator@host-a")
    if task:
        sub.add_argument("--task", required=True, help="the unit's task id")


def _anchors(sub):
    sub.add_argument("--expect-head", default=None, dest="expect_head", metavar="SHA256",
                     help="the head digest kept OFF the writer; the record must end exactly there")
    sub.add_argument("--expect-ancestor", default=None, dest="expect_ancestor", metavar="SHA256",
                     help="a head digest kept off the writer earlier; it must still be IN the record")


def build_parser():
    p = argparse.ArgumentParser(
        prog="events.py",
        description="Append-only lifecycle event record and the WIP-curve rows derived from it.",
        epilog="exit 0 ok / 1 incomplete or mismatch / 2 usage / 3 fail-closed")
    p.add_argument("--log", default=None,
                   help=f"record path (default ${PRIMARY_LOG_ENV}, ${LOG_ENV} or {DEFAULT_LOG})")
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("emit", help="append one coordinator-observed event")
    e.add_argument("--kind", required=True, choices=sorted(KINDS))
    _binding(e)
    e.add_argument("--task", default=None)
    e.add_argument("--dispatch", default=None)
    e.add_argument("--producer", default="coordinator")
    e.add_argument("--basis", default="observed", choices=BASES)
    e.add_argument("--observed-at", default=None, type=_ts_arg, dest="observed_at",
                   help="ISO-8601 with an offset (default: now, UTC)")
    e.add_argument("--source-ref", required=True, dest="source_ref",
                   help="the artifact or record the observation came from")
    e.add_argument("--source-sha256", default=None, dest="source_sha256")
    e.add_argument("--source-file", default=None, dest="source_file",
                   help="hash this file as the source's sha256")
    e.add_argument("--event-id", default=None, dest="event_id",
                   help="the producer's idempotency key (default: derived from the content)")
    e.add_argument("--data", default=None, help="the kind's data fields as a JSON object")

    s = sub.add_parser("ingest-state", help="record one run's launches/done/deaths from a DB")
    s.add_argument("--db", required=True, help="the local-state runtime.db (opened read-only)")
    _binding(s)

    t = sub.add_parser("ingest-transcript", help="record a verify.py --transcript-out verdict")
    t.add_argument("--transcript", required=True)
    t.add_argument("--manifest", default=None,
                   help="the judged manifest (default: the path the transcript names)")
    _binding(t, task=True)

    u = sub.add_parser("ingest-usage", help="record model usage from a Claude stream-json log")
    u.add_argument("--stream", required=True)
    _binding(u)
    u.add_argument("--task", default=None)
    u.add_argument("--dispatch", default=None)
    u.add_argument("--observed-at", default=None, type=_ts_arg, dest="observed_at")

    v = sub.add_parser("verify", help="recompute the chain and print the head")
    _anchors(v)

    r = sub.add_parser("report", help="derive the WIP-curve rows")
    r.add_argument("--run", default=None, help="required when the record holds several runs")
    r.add_argument("--json", action="store_true", help="the whole report as JSON")
    _anchors(r)

    c = sub.add_parser("check", help="compare a run report's WIP-curve rows to the record")
    c.add_argument("--run-report", required=True, dest="run_report")
    c.add_argument("--run", default=None)
    _anchors(c)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {"emit": cmd_emit, "ingest-state": cmd_ingest_state,
                "ingest-transcript": cmd_ingest_transcript, "ingest-usage": cmd_ingest_usage,
                "verify": cmd_verify, "report": cmd_report, "check": cmd_check}
    try:
        return handlers[args.command](args)
    except UsageError as err:
        print(f"events: usage: {err}", file=sys.stderr)
        return EXIT_USAGE
    except EventsError as err:
        print(f"events: FAIL-CLOSED: {err}", file=sys.stderr)
        return EXIT_FAIL_CLOSED


if __name__ == "__main__":
    sys.exit(main())
