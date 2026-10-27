#!/usr/bin/env python3
"""live_broker.py — the live harness's credential broker: the one process that holds the
subscription token, alone in its own container beside the arm's (scripts/live_container.py starts
both; docs/guides/live-harness.md is the operator's guide).

The arm's container shares this container's network namespace and nothing else: it reaches the
broker at 127.0.0.1:PORT, never its files, its processes or its environment. The arm's `claude`
(scripts/live_container_bin/claude) sends every model call here with a placeholder credential. The
broker forwards POST /v1/messages and /v1/messages/count_tokens to the API with the token in its
place and refuses every other request. So no process of the arm can read the token, and no model
call it makes, through claude or around it, escapes the cap: a paid call needs the token.

What this is NOT is an egress control (2026-10-27 audit, W5-15). Sharing the namespace shares its
interfaces, the route out included, so any process of the arm can open its own connection to any
host without passing through the broker, and nothing here sees, caps or records it. The broker
refuses requests made TO it; it does not stand between the arm and the network.

Every connection has a socket timeout (HANDLER_TIMEOUT_S) and a body deadline, and at most
MAX_CONNECTIONS are served at once, so a client that connects and sends nothing cannot park the
threads the arm's model calls need (W5-16). count_tokens is free but bounded: FREE_CALLS_MAX
calls and FREE_BYTES_MAX body bytes per broker, a "free" tally every FREE_RECORD_EVERY calls and
the tally on every later event, and a refusal past the bound (W5-17). A fault anywhere in a
request is recorded in the ledger as a "fault" event (the exception type and the frames, never a
message, a request or the token), and a call's settle always runs, settling the whole
reservation when its usage cannot be priced (W5-18): the container keeps no log.

The cap is a reservation ledger. A call starts only when the settled spend, the reservations of
the calls still in flight and its own reservation fit under --cap-usd. Its reservation is its
worst case at its model's highest list price: its body's bytes as input tokens (no token is
shorter than a byte) plus FRAMING_TOKENS for the API's own framing and IMAGE_TOKENS for each
inline image, all priced as 1-hour cache writes, and its max_tokens as output. When it ends, the
reservation is released and the usage the API reported is settled as the API bills it; a call
that ends without a complete usage report settles its whole reservation.

Nothing unpriced runs (Codex at 8585b35789). A body is forwarded only when it is a JSON object
with a priced model and a positive max_tokens, every field is one the broker prices (FIELDS), every
tool is the client's own wherever it is defined (in `tools` or inside the content), and all content is inline and
bounded by its bytes. So an image or
document by URL or file id, a PDF, an advisor or other server-side tool, an MCP server,
server-side compaction, a service tier, and an inference geography other than global or US are
refused: each is billed beyond what the body's bytes bound. A call that names no geography
reserves at the US premium, and every call settles at the geography the API reports.

The ledger (--ledger, appended, mode 0600) is one JSON line per event: open, start, settle and
refuse. It never holds the token, a request or a response. The launcher reads it after both
containers are destroyed, into the receipt.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8787  # scripts/live_container_bin/claude's BROKER names the same port
UPSTREAM = "https://api.anthropic.com"
OAUTH_BETA = "oauth-2025-04-20"  # a subscription token is an OAuth bearer token
# USD per million tokens (input, output, cache read): the Claude API's list prices as of
# 2026-10-06. A cache write is 1.25x input for the 5-minute TTL and 2x for the 1-hour one; fast
# mode is 2x. Haiku 5.5 costs more above 100K prompt tokens (TIERED).
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25), "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50), "claude-opus-4-7": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20), "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
TIERED = {"claude-haiku-5-5": (100_000, (0.50, 2.50, 0.05))}
WRITE_5M, WRITE_1H, FAST = 1.25, 2.0, 2.0
# inference_geo "us" is billed at 1.1x every token category. A request that names none runs in the
# workspace's default geography, which may be US, so it reserves at the worst; a call settles at
# the geography the API reports it ran in (usage.inference_geo), the worst when it reports none
# (Codex at 3c01b90b5e).
GEO = {"global": 1.0, "us": 1.1}
GEO_WORST = max(GEO.values())
IMAGE_TOKENS = 4800  # above the most one image costs on any current model: 4,784 visual tokens at 2576 px
COSTLIEST = "claude-fable-5-1"  # what an iteration naming an unpriced model is charged as
SEARCH_USD = 0.01  # each web search the API reports: refused tools never run one, but any reported is charged
# An Anthropic-defined tool's type carries its version date (web_search_20250305, bash_20250124):
# one anywhere in the content is a tool definition, which only the client's own tools may be.
DATED_TYPE_RE = re.compile(r"_\d{8}$")
# Every request field the broker can price. Any other is refused, so a pricing modifier the
# broker does not know never reaches the API unpriced.
FIELDS = {"model", "messages", "system", "max_tokens", "stream", "tools", "tool_choice", "metadata", "thinking",
          "temperature", "top_p", "top_k", "stop_sequences", "output_config", "context_management", "speed",
          "inference_geo", "service_tier"}
FRAMING_TOKENS = 4096
MAX_BODY = 64 << 20
UPSTREAM_TIMEOUT_S = 900
HANDLER_TIMEOUT_S = 60  # each read or write on a client connection (W5-16)
BODY_DEADLINE_S = 120  # the whole request body, however slowly it trickles
MAX_CONNECTIONS = 32  # served at once: the broker's --pids-limit is 64
FREE_CALLS_MAX, FREE_BYTES_MAX = 5000, 2 << 30  # count_tokens per broker (W5-17)
FREE_RECORD_EVERY = 100  # a "free" tally event every this many count_tokens calls
PRICED_PATH, FREE_PATH = "/v1/messages", "/v1/messages/count_tokens"
DATED_RE = re.compile(r"-\d{8}$")
# What the client sent that never reaches the API: its credential, and hop-by-hop headers.
DROP = {"host", "authorization", "x-api-key", "content-length", "connection", "keep-alive", "proxy-authorization",
        "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade", "accept-encoding", "cookie"}
DROP_BACK = {"content-length", "transfer-encoding", "connection", "keep-alive", "content-encoding", "set-cookie"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def model_key(model):
    """The PRICES key for `model` (a dated id prices as its alias), or None."""
    key = DATED_RE.sub("", model) if isinstance(model, str) else None
    return key if key in PRICES else None


def priced(usage, model, mult=1.0):
    """USD for one call's reported usage, as the API bills it: each cache write at its TTL's rate
    (the 1-hour rate when the report does not split them), at the tier its prompt reached."""
    key = model_key(model)
    tokens = lambda key, doc=usage: max(int(doc.get(key) or 0), 0)
    prompt = tokens("input_tokens") + tokens("cache_creation_input_tokens") + tokens("cache_read_input_tokens")
    inp, out, read = PRICES[key]
    if key in TIERED and prompt > TIERED[key][0]:
        inp, out, read = TIERED[key][1]
    split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    w5, w1 = tokens("ephemeral_5m_input_tokens", split), tokens("ephemeral_1h_input_tokens", split)
    written = tokens("cache_creation_input_tokens")
    write = w5 * WRITE_5M + w1 * WRITE_1H if split and w5 + w1 == written else written * WRITE_1H
    usd = (tokens("input_tokens") * inp + write * inp + tokens("cache_read_input_tokens") * read
           + tokens("output_tokens") * out) / 1e6
    return usd * mult


def settled(usage, model, mult=1.0):
    """USD for a finished call: its usage, or the sum of the iterations the API reported (each at
    its own model's price, an unpriced one at the costliest) when that sum is larger."""
    usd = priced(usage, model, mult)
    iterations = [it for it in usage.get("iterations") or [] if isinstance(it, dict)]
    if iterations:
        named = lambda it: it.get("model") if model_key(it.get("model")) else model if it.get("model") is None else COSTLIEST
        usd = max(usd, sum(priced(it, named(it), mult) for it in iterations))
    searches = (usage.get("server_tool_use") or {}).get("web_search_requests") or 0
    return usd + max(int(searches), 0) * SEARCH_USD


def reservation(body_len, max_tokens, model, mult=1.0, images=0):
    """USD for one call's worst case: every byte of its body an input token written to the 1-hour
    cache, plus the framing and IMAGE_TOKENS for each image, and every token of max_tokens an
    output token, at its model's highest tier."""
    key = model_key(model)
    inp, out, _read = TIERED[key][1] if key in TIERED else PRICES[key]
    usd = ((body_len + FRAMING_TOKENS + images * IMAGE_TOKENS) * inp * WRITE_1H + max_tokens * out) / 1e6
    return usd * mult


def content_problem(node, found):
    """Why some content in `node` is not bounded by its bytes, or None; counts inline images."""
    if isinstance(node, list):
        for item in node:
            if why := content_problem(item, found):
                return why
    elif isinstance(node, dict):
        if "file_id" in node:
            return "content by file id is billed by what the file holds, not by the request's bytes"
        # A tool can be defined inside the content too, not only in `tools` (a system message's
        # tool_addition, Codex at 0116e8ae34): the same rule holds wherever one is defined.
        definitions = node.get("tool_definition")
        for tool in definitions if isinstance(definitions, list) else [definitions] if definitions is not None else []:
            kind = tool.get("type") if isinstance(tool, dict) else "malformed"
            if kind not in (None, "custom"):
                return f"a {kind} tool is not the client's own: it is billed beyond the request's tokens"
        if isinstance(node.get("type"), str) and DATED_TYPE_RE.search(node["type"]):
            return f"a {node['type']} tool is not the client's own: it is billed beyond the request's tokens"
        source = node.get("source")
        if isinstance(source, dict):
            kind, media = source.get("type"), str(source.get("media_type") or "")
            if kind in ("url", "file"):
                return f"content by {kind} is billed by what it fetches, not by the request's bytes"
            if media == "application/pdf":
                return "a PDF is billed per page, which its bytes do not bound"
            if kind == "base64" and media.startswith("image/"):
                found["images"] += 1
        for value in node.values():
            if why := content_problem(value, found):
                return why
    return None


def terms(doc):
    """(why the body cannot be priced or None, its price multiplier, its inline images)."""
    if not isinstance(doc, dict):
        return "the body is not a JSON object", 1.0, 0
    if extra := sorted(set(doc) - FIELDS):
        return f"a field the broker cannot price: {', '.join(extra)}", 1.0, 0
    if model_key(doc.get("model")) is None:
        return f"no price for model {doc.get('model')!r}: the broker runs only {', '.join(sorted(PRICES))}", 1.0, 0
    max_tokens = doc.get("max_tokens")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
        return "the body carries no positive integer max_tokens", 1.0, 0
    for tool in doc.get("tools") or []:
        kind = tool.get("type") if isinstance(tool, dict) else "malformed"
        if kind not in (None, "custom"):
            return f"a {kind} tool is not the client's own: it is billed beyond the request's tokens", 1.0, 0
    if not isinstance(doc.get("context_management") or {}, dict):
        return "context_management is not an object", 1.0, 0
    for edit in (doc.get("context_management") or {}).get("edits") or []:
        kind = edit.get("type") if isinstance(edit, dict) else "malformed"
        if not (isinstance(kind, str) and kind.startswith("clear_")):
            return f"a {kind} context edit runs inference beyond the request's tokens", 1.0, 0
    if doc.get("service_tier", "standard_only") != "standard_only":
        return f"service tier {doc['service_tier']!r} is not priced", 1.0, 0
    if doc.get("speed") not in (None, "standard", "fast"):
        return f"speed {doc['speed']!r} is not priced", 1.0, 0
    geo = doc.get("inference_geo")
    if geo is not None and (not isinstance(geo, str) or geo not in GEO):
        return f"inference geography {geo!r} is not priced", 1.0, 0
    found = {"images": 0}
    if why := content_problem([doc.get("system"), doc.get("messages")], found):
        return why, 1.0, 0
    return None, GEO.get(geo, GEO_WORST) * (FAST if doc.get("speed") == "fast" else 1.0), found["images"]


def settle_mult(usage, fast):
    """The price multiplier a finished call is billed at: the geography and speed the API reports
    it ran at (the worst geography when it reports none), fast when either side says so."""
    return GEO.get(usage.get("inference_geo"), GEO_WORST) * (FAST if fast or usage.get("speed") == "fast" else 1.0)


def merged_usage(seen, usage):
    """The API reports usage at message_start and (cumulatively) at message_delta: keep each
    count's largest value, the cache-write split's and the server tools' included."""
    for key, value in (usage or {}).items():
        if isinstance(value, int) and not isinstance(value, bool):
            seen[key] = max(seen.get(key, 0), value)
        elif key in ("cache_creation", "server_tool_use") and isinstance(value, dict):
            merged_usage(seen.setdefault(key, {}), value)
        elif key == "iterations" and isinstance(value, list):
            seen[key] = value
        elif key in ("inference_geo", "speed") and isinstance(value, str):
            seen[key] = value
    return seen


class Ledger:
    """The reservation ledger: settled spend, the calls in flight, and the append-only file."""

    def __init__(self, path, cap_usd):
        self.cap, self.settled, self.inflight, self.n = cap_usd, 0.0, {}, 0
        self.free_calls = self.free_bytes = 0
        self.lock = threading.Lock()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        self.fh = os.fdopen(fd, "a", encoding="utf-8")
        self.write({"event": "open", "cap_usd": cap_usd, "prices_usd_per_mtok": PRICES, "tiered": TIERED, "geo": GEO,
                    "image_tokens": IMAGE_TOKENS,
                    "framing_tokens": FRAMING_TOKENS, "pid": os.getpid()})

    def write(self, entry):
        tally = {"free_calls": self.free_calls, "free_bytes": self.free_bytes} if self.free_calls else {}
        self.fh.write(json.dumps({"at": now(), **entry, **tally}, sort_keys=True) + "\n")
        self.fh.flush()
        os.fsync(self.fh.fileno())

    def free(self, nbytes):
        """True when one more count_tokens call of `nbytes` fits the free-call bound (W5-17): free
        is not unbounded, and what was used is on the record."""
        with self.lock:
            if self.free_calls + 1 > FREE_CALLS_MAX or self.free_bytes + nbytes > FREE_BYTES_MAX:
                self.write({"event": "refuse", "model": None,
                            "why": f"the count_tokens bound ({FREE_CALLS_MAX} calls, {FREE_BYTES_MAX} bytes)"})
                return False
            self.free_calls += 1
            self.free_bytes += nbytes
            if self.free_calls % FREE_RECORD_EVERY == 0:
                self.write({"event": "free", "calls": self.free_calls, "bytes": self.free_bytes})
            return True

    def fault(self, where, err):
        """A fault, recorded where it is kept: the exception's type and frames, never its message
        (which may quote a request), a request, a response or the token (W5-18)."""
        frames = [f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}"
                  for f in traceback.extract_tb(err.__traceback__)][-12:] if err is not None else []
        with self.lock:
            self.write({"event": "fault", "where": where, "error": type(err).__name__, "frames": frames})

    def reserve(self, model, usd):
        """A call id when the call fits under the cap with every call in flight, else None."""
        with self.lock:
            committed = self.settled + sum(self.inflight.values())
            if committed + usd > self.cap:
                self.write({"event": "refuse", "model": model, "reserved_usd": round(usd, 6),
                            "committed_usd": round(committed, 6), "why": "the cap"})
                return None
            self.n += 1
            self.inflight[self.n] = usd
            self.write({"event": "start", "call": self.n, "model": model, "reserved_usd": round(usd, 6)})
            return self.n

    def refuse(self, why, model=None):
        with self.lock:
            self.write({"event": "refuse", "model": model, "why": why})

    def settle(self, call, usd, status, usage, complete):
        """Release the call's reservation and settle `usd`, or the whole reservation when None."""
        with self.lock:
            reserved = self.inflight.pop(call, 0.0)
            usd = reserved if usd is None else usd
            self.settled += usd
            self.write({"event": "settle", "call": call, "cost_usd": round(usd, 6), "status": status, "usage": usage,
                        "complete": complete, "settled_usd": round(self.settled, 6)})


class Broker(BaseHTTPRequestHandler):
    """One request: forwarded with the token in place of the client's credential, or refused."""

    server_version = "open-fleet-live-broker"
    token = ledger = upstream = None  # set by serve()

    def log_message(self, *args):  # no request line anywhere: the ledger is the record
        pass

    def fail(self, status, kind, why):
        data = json.dumps({"type": "error", "error": {"type": kind, "message": f"open-fleet live broker: {why}"}})
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data.encode())

    def do_GET(self):
        if self.path == "/health":
            data = json.dumps({"ok": True, "cap_usd": self.ledger.cap}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.ledger.refuse(f"GET {urllib.parse.urlsplit(self.path).path}")
        self.fail(403, "permission_error", "only POST /v1/messages and /v1/messages/count_tokens are forwarded")

    def do_POST(self):
        target = urllib.parse.urlsplit(self.path)
        path = target.path
        self.target = path + (f"?{target.query}" if target.query else "")  # what is forwarded: never a host
        if path not in (PRICED_PATH, FREE_PATH):
            self.ledger.refuse(f"POST {path}")
            return self.fail(403, "permission_error", "only POST /v1/messages and /v1/messages/count_tokens are forwarded")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.fail(411, "invalid_request_error", "a request needs a Content-Length")
        if not 0 <= length <= MAX_BODY:
            return self.fail(413, "invalid_request_error", f"a body over {MAX_BODY} bytes")
        body = self.read_body(length)
        if body is None:
            return self.fail(408, "invalid_request_error", f"the body did not arrive within {BODY_DEADLINE_S:g} s")
        if path == FREE_PATH:
            if not self.ledger.free(len(body)):
                return self.fail(403, "permission_error", "the count_tokens bound would be passed")
            return self.relay(body, None, None, False)
        try:
            doc = json.loads(body)
        except ValueError:
            doc = None
        why, mult, images = terms(doc)
        model = doc.get("model") if isinstance(doc, dict) else None
        if why:
            self.ledger.refuse(why, model)
            return self.fail(400, "invalid_request_error", why)
        call = self.ledger.reserve(model, reservation(len(body), doc["max_tokens"], model, mult, images))
        if call is None:
            return self.fail(403, "permission_error", f"the spend cap (${self.ledger.cap:g}) would be passed")
        self.relay(body, call, model, doc.get("speed") == "fast")

    def read_body(self, length):
        """The request's `length` body bytes, or None when they do not all arrive by the deadline:
        the socket timeout bounds each read, this bounds the trickle (W5-16)."""
        chunks, left, deadline = [], length, time.monotonic() + BODY_DEADLINE_S
        while left:
            if time.monotonic() > deadline:
                return None
            try:
                chunk = self.rfile.read1(min(left, 1 << 20))
            except OSError:  # the handler's socket timeout
                return None
            if not chunk:
                return None
            chunks.append(chunk)
            left -= len(chunk)
        return b"".join(chunks)

    def relay(self, body, call, model, fast):
        """Forward to the API and relay the answer as it arrives; settle the call's usage."""
        usage, complete, status, conn = {}, False, None, None
        try:
            up = urllib.parse.urlsplit(self.upstream)
            conn_cls = http.client.HTTPSConnection if up.scheme == "https" else http.client.HTTPConnection
            conn = conn_cls(up.hostname, up.port, timeout=UPSTREAM_TIMEOUT_S)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in DROP}
            betas = [b.strip() for b in self.headers.get("anthropic-beta", "").split(",") if b.strip()]
            headers = {k: v for k, v in headers.items() if k.lower() != "anthropic-beta"}
            headers.update({"Authorization": f"Bearer {self.token}", "Accept-Encoding": "identity",
                            "anthropic-beta": ",".join(betas + ([OAUTH_BETA] if OAUTH_BETA not in betas else []))})
            conn.request("POST", self.target, body=body, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            self.send_response(resp.status)
            for key, value in resp.getheaders():
                if key.lower() not in DROP_BACK:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            sse = "text/event-stream" in (resp.getheader("Content-Type") or "")
            pending, whole = b"", []
            while chunk := resp.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
                if call is None:
                    continue
                if not sse:
                    whole.append(chunk)
                    continue
                pending += chunk
                *lines, pending = pending.split(b"\n")
                for line in lines:
                    if not line.startswith(b"data:"):
                        continue
                    try:
                        event = json.loads(line[5:])
                    except ValueError:
                        continue
                    if event.get("type") == "message_start":
                        merged_usage(usage, (event.get("message") or {}).get("usage"))
                    elif event.get("type") == "message_delta":
                        merged_usage(usage, event.get("usage"))
                    elif event.get("type") == "message_stop":
                        complete = True
            if call is not None and not sse:
                try:
                    doc = json.loads(b"".join(whole))
                except ValueError:
                    doc = None
                if isinstance(doc, dict) and isinstance(doc.get("usage"), dict):
                    merged_usage(usage, doc["usage"])
                    complete = status == 200
                elif status != 200:  # an error the API answered at once bills nothing
                    complete = True
        except Exception as err:  # the client left, or the API did: whatever ran is settled below
            if status is None:
                try:
                    self.fail(502, "api_error", f"the API could not be reached ({type(err).__name__})")
                except OSError:
                    pass
        finally:
            if conn is not None:
                conn.close()
            if call is not None:
                # Priced inside its own guard, so a usage report of a shape the broker cannot price
                # still settles (its whole reservation) and is recorded, never skipped (W5-18).
                usd = None
                if complete:
                    try:
                        usd = settled(usage, model, settle_mult(usage, fast))
                    except Exception as err:  # any type surprise in the report: settle the reservation
                        self.ledger.fault("settle", err)
                self.ledger.settle(call, usd, status, usage, complete)


def read_token(path):
    """The token, from the read-only mount: one ASCII line. A refusal names the path, never a byte."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        token = raw.decode("ascii").strip()
    except (OSError, UnicodeDecodeError) as err:
        raise SystemExit(f"live_broker: cannot read the token at {path} ({type(err).__name__})") from None
    if not token or any(c.isspace() for c in token):
        raise SystemExit(f"live_broker: the token at {path} must be one line")
    return token


class BrokerServer(ThreadingHTTPServer):
    """At most `slots` connections served at once (one past it is closed unanswered), and a fault
    in any of them recorded in the ledger rather than printed to a log nobody keeps (W5-16, W5-18)."""

    daemon_threads = True

    def __init__(self, address, handler, ledger, slots):
        self.ledger, self.slots = ledger, threading.BoundedSemaphore(slots)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        self.ledger.fault("handler", sys.exc_info()[1])


def serve(token, ledger_path, cap_usd, port=PORT, upstream=UPSTREAM, host="127.0.0.1"):
    """A started server (its own thread) and its ledger; the caller owns shutdown."""
    handler = type("BoundBroker", (Broker,), {"token": token, "ledger": Ledger(ledger_path, cap_usd),
                                              "upstream": upstream, "timeout": HANDLER_TIMEOUT_S})
    server = BrokerServer((host, port), handler, handler.ledger, MAX_CONNECTIONS)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, handler.ledger


def main(argv=None):
    p = argparse.ArgumentParser(prog="live_broker.py", description=__doc__.split("\n", 1)[0])
    p.add_argument("--token-file", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--cap-usd", type=float, required=True)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--upstream", default=UPSTREAM, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if not args.cap_usd > 0:
        p.error("--cap-usd must be a positive number of dollars")
    server, _ledger = serve(read_token(args.token_file), args.ledger, args.cap_usd, args.port, args.upstream)
    print(f"live_broker: listening on 127.0.0.1:{server.server_address[1]}, cap ${args.cap_usd:g}", file=sys.stderr)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
