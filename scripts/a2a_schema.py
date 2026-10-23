#!/usr/bin/env python3
"""Validate A2A AgentCards against the pinned official A2A proto, stdlib only (#607).

open-fleet's exporter emits its own offline mission descriptor. Whether a JSON object is an A2A
transport AgentCard is a question only the protocol's own schema answers, so this module answers
it from that schema and nothing else. Upstream's normative schema is `specification/a2a.proto`
(package `lf.a2a.v1`); at the pinned commit its JSON Schema is a generated build artifact that is
not committed. So this module reads the vendored proto itself -- pinned by commit and sha256 in
scripts/vendor/a2a/PIN.json, refused when the bytes drift -- and checks a ProtoJSON value:

* every key is a field of the message, by its lowerCamelCase JSON name or its proto name but not
  both; an unknown key is refused, as a ProtoJSON parser refuses it by default;
* every value has the field's JSON shape (string, bool, object, array, map,
  google.protobuf.Struct), and at most one member of a oneof is set;
* `(google.api.field_behavior) = REQUIRED` is enforced, including the part proto3 parsing alone
  cannot see: a required string or repeated field that is empty is unset on the wire, so it is
  refused (roadmap verification note G4).

Semantic checks the proto cannot express run once the shape passes: interface URL, binding and
protocol-version forms, unique skill ids, media types, security requirements that name a declared
scheme, base64url signature parts and unique absolute extension URIs.

The parser covers exactly the proto constructs the pinned file uses and raises on anything else,
and the validator refuses a message whose field closure holds a type it does not check. A re-pin
that brings in `reserved`, a nested type, `json_name`, an enum or a new scalar under AgentCard
therefore fails loudly instead of being validated wrongly; tests/test_a2a_schema.py pins both.

Usage:
    python3 scripts/a2a_schema.py card.json [...]   # validate ProtoJSON AgentCard files
    python3 scripts/a2a_schema.py --required        # required AgentCard fields, in proto order
    python3 scripts/a2a_schema.py --check-pin       # re-hash the vendored files against PIN.json

Exit: 0 valid · 1 invalid card or pin drift · 2 usage error.
"""
import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "scripts" / "vendor" / "a2a"
PIN_PATH = VENDOR_DIR / "PIN.json"
PROTO_PATH = VENDOR_DIR / "a2a.proto"
PROTO_PIN_PATH = "scripts/vendor/a2a/a2a.proto"

# Exactly the constructs the pinned a2a.proto uses. Anything else is a ProtoSchemaError: a schema
# this parser half-understands must never validate a card.
FILE_OPTIONS = frozenset({
    "csharp_namespace", "go_package", "java_multiple_files", "java_outer_classname", "java_package",
})
RPC_OPTIONS = frozenset({"google.api.http", "google.api.method_signature"})
FIELD_BEHAVIORS = frozenset({"REQUIRED"})
PROTO_SCALARS = frozenset({
    "double", "float", "int32", "int64", "uint32", "uint64", "sint32", "sint64",
    "fixed32", "fixed64", "sfixed32", "sfixed64", "bool", "string", "bytes",
})
WELL_KNOWN = frozenset({
    "google.protobuf.Struct", "google.protobuf.Value", "google.protobuf.Timestamp",
    "google.protobuf.Empty",
})
# What the validator checks. The AgentCard closure at the pin uses only these; a type outside the
# set under the validated message is refused rather than waved through.
VALIDATED_TYPES = frozenset({"string", "bool", "google.protobuf.Struct"})

CORE_BINDINGS = ("JSONRPC", "GRPC", "HTTP+JSON")
_PROTOCOL_VERSION = re.compile(r"^\d+\.\d+$")
_MEDIA_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_HOST_PORT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?:\d{1,5}$")

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<string>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
  | (?P<number>\d+)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
  | (?P<symbol>[{}\[\]()<>=;,:.-])
""", re.S | re.X)


class ProtoSchemaError(Exception):
    """The pinned schema is unreadable, drifted, or uses a construct this module does not cover."""


@dataclass
class Field:
    name: str
    number: int
    type: str
    label: str = ""  # "", "optional", "repeated" or "map"
    key_type: str = ""
    required: bool = False
    deprecated: bool = False
    oneof: str = ""

    @property
    def json_name(self):
        """protoc's lowerCamelCase JSON name: drop each `_` and upper-case the letter after it."""
        out, upper = [], False
        for ch in self.name:
            if ch == "_":
                upper = True
            else:
                out.append(ch.upper() if upper else ch)
                upper = False
        return "".join(out)


@dataclass
class Message:
    name: str
    fields: list = field(default_factory=list)
    oneofs: dict = field(default_factory=dict)

    def lookup(self, key):
        for f in self.fields:
            if key in (f.json_name, f.name):
                return f
        return None


@dataclass
class Schema:
    package: str
    imports: list
    messages: dict
    enums: dict
    services: dict
    sha256: str = ""

    @property
    def major(self):
        """The protocol major the package names (`lf.a2a.v1` -> "1")."""
        m = re.search(r"\.v(\d+)$", self.package)
        return m.group(1) if m else ""


def _tokenize(text):
    tokens, pos, line = [], 0, 1
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ProtoSchemaError(f"line {line}: unexpected character {text[pos]!r}")
        kind = m.lastgroup
        if kind not in ("ws", "comment"):
            tokens.append((kind, m.group(), line))
        line += m.group().count("\n")
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, text):
        self.toks = _tokenize(text)
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else ("eof", "", -1)

    def take(self, value=None, kind=None):
        tok = self.peek()
        if tok[0] == "eof" or (value is not None and tok[1] != value) or (kind and tok[0] != kind):
            want = value or kind or "a token"
            raise ProtoSchemaError(f"line {tok[2]}: expected {want!r}, found {tok[1]!r}")
        self.i += 1
        return tok

    def unsupported(self, what):
        tok = self.peek()
        raise ProtoSchemaError(f"line {tok[2]}: unsupported proto construct {what!r} "
                               "(scripts/a2a_schema.py covers only what the pinned a2a.proto uses)")

    def parse(self):
        schema = Schema(package="", imports=[], messages={}, enums={}, services={})
        while self.peek()[0] != "eof":
            word = self.peek()[1]
            if word == "syntax":
                self.take("syntax")
                self.take("=")
                if self.take(kind="string")[1].strip("\"'") != "proto3":
                    self.unsupported("syntax other than proto3")
                self.take(";")
            elif word == "package":
                self.take("package")
                schema.package = self.take(kind="ident")[1]
                self.take(";")
            elif word == "import":
                self.take("import")
                schema.imports.append(self.take(kind="string")[1].strip("\"'"))
                self.take(";")
            elif word == "option":
                self.take("option")
                name = self.take(kind="ident")[1]
                if name not in FILE_OPTIONS:
                    self.unsupported(f"option {name}")
                self.take("=")
                self._constant()
                self.take(";")
            elif word == "message":
                msg = self._message()
                schema.messages[msg.name] = msg
            elif word == "enum":
                name, values = self._enum()
                schema.enums[name] = values
            elif word == "service":
                name, rpcs = self._service()
                schema.services[name] = rpcs
            else:
                self.unsupported(word)
        _resolve(schema)
        return schema

    def _constant(self):
        tok = self.peek()
        if tok[0] in ("ident", "string", "number"):
            return self.take()[1]
        if tok[1] == "-":
            self.take("-")
            return "-" + self.take(kind="number")[1]
        return self.unsupported(f"option value {tok[1]}")

    def _message(self):
        self.take("message")
        msg = Message(name=self.take(kind="ident")[1])
        self.take("{")
        while self.peek()[1] != "}":
            word = self.peek()[1]
            if word == "oneof":
                self.take("oneof")
                oneof = self.take(kind="ident")[1]
                self.take("{")
                members = []
                while self.peek()[1] != "}":
                    f = self._field(oneof=oneof)
                    msg.fields.append(f)
                    members.append(f.name)
                self.take("}")
                msg.oneofs[oneof] = members
            elif word in ("message", "enum", "reserved", "extensions", "extend", "option", "group",
                          "required"):
                self.unsupported(f"{word} inside message {msg.name}")
            else:
                msg.fields.append(self._field())
        self.take("}")
        return msg

    def _field(self, oneof=""):
        label, key_type = "", ""
        if self.peek()[1] in ("optional", "repeated") and not oneof:
            label = self.take()[1]
        if self.peek()[1] == "map" and not oneof and not label:
            self.take("map")
            self.take("<")
            key_type = self.take(kind="ident")[1]
            self.take(",")
            ftype = self.take(kind="ident")[1]
            self.take(">")
            label = "map"
        else:
            ftype = self.take(kind="ident")[1]
            if ftype in ("message", "enum", "oneof", "map", "optional", "repeated", "group",
                         "required", "reserved", "extensions", "extend", "option", "stream"):
                self.unsupported(f"{ftype} in field position")
        f = Field(name=self.take(kind="ident")[1], number=0, type=ftype, label=label,
                  key_type=key_type, oneof=oneof)
        self.take("=")
        f.number = int(self.take(kind="number")[1])
        if self.peek()[1] == "[":
            self.take("[")
            while True:
                self._field_option(f)
                if self.peek()[1] != ",":
                    break
                self.take(",")
            self.take("]")
        self.take(";")
        return f

    def _field_option(self, f):
        if self.peek()[1] == "(":
            self.take("(")
            name = self.take(kind="ident")[1]
            self.take(")")
            self.take("=")
            value = self._constant()
            if name != "google.api.field_behavior" or value not in FIELD_BEHAVIORS:
                self.unsupported(f"field option ({name}) = {value}")
            f.required = True
            return
        name = self.take(kind="ident")[1]
        self.take("=")
        value = self._constant()
        if name != "deprecated" or value not in ("true", "false"):
            self.unsupported(f"field option {name} = {value}")
        f.deprecated = value == "true"

    def _enum(self):
        self.take("enum")
        name = self.take(kind="ident")[1]
        self.take("{")
        values = {}
        while self.peek()[1] != "}":
            word = self.peek()[1]
            if word in ("option", "reserved"):
                self.unsupported(f"{word} inside enum {name}")
            value_name = self.take(kind="ident")[1]
            self.take("=")
            sign = self.take("-")[1] if self.peek()[1] == "-" else ""
            values[value_name] = int(sign + self.take(kind="number")[1])
            if self.peek()[1] == "[":
                self.unsupported(f"enum value option on {value_name}")
            self.take(";")
        self.take("}")
        return name, values

    def _service(self):
        self.take("service")
        name = self.take(kind="ident")[1]
        self.take("{")
        rpcs = {}
        while self.peek()[1] != "}":
            if self.peek()[1] != "rpc":
                self.unsupported(f"{self.peek()[1]} inside service {name}")
            self.take("rpc")
            rpc = self.take(kind="ident")[1]
            types = []
            for i in range(2):  # (request) returns (response)
                if i:
                    self.take("returns")
                self.take("(")
                if self.peek()[1] == "stream":
                    self.take("stream")
                types.append(self.take(kind="ident")[1])
                self.take(")")
            rpcs[rpc] = tuple(types)
            if self.peek()[1] == ";":
                self.take(";")
                continue
            self.take("{")
            while self.peek()[1] != "}":
                self.take("option")
                self.take("(")
                opt = self.take(kind="ident")[1]
                self.take(")")
                if opt not in RPC_OPTIONS:
                    self.unsupported(f"rpc option ({opt})")
                self.take("=")
                if self.peek()[1] == "{":
                    self._skip_aggregate()
                else:
                    self._constant()
                self.take(";")
            self.take("}")
        self.take("}")
        return name, rpcs

    def _skip_aggregate(self):
        """An rpc option's text-format aggregate (`{ post: "/x" body: "*" }`): balanced, unread."""
        depth = 0
        while True:
            tok = self.take()
            depth += {"{": 1, "}": -1}.get(tok[1], 0) if tok[0] == "symbol" else 0
            if depth == 0:
                return


def _resolve(schema):
    """Every field and rpc type must name a scalar, a type in the file, or an imported well-known."""
    def known(t):
        return t in PROTO_SCALARS or t in schema.messages or t in schema.enums or t in WELL_KNOWN

    for msg in schema.messages.values():
        for f in msg.fields:
            if not known(f.type):
                raise ProtoSchemaError(f"{msg.name}.{f.name}: unresolved type {f.type!r}")
            if f.label == "map" and f.key_type not in PROTO_SCALARS - {"double", "float", "bytes"}:
                raise ProtoSchemaError(f"{msg.name}.{f.name}: invalid map key type {f.key_type!r}")
    for rpcs in schema.services.values():
        for rpc, types in rpcs.items():
            for t in types:
                if not known(t):
                    raise ProtoSchemaError(f"rpc {rpc}: unresolved type {t!r}")


def parse_proto(text):
    """Parse proto text into a Schema; ProtoSchemaError on any construct outside the covered set."""
    return _Parser(text).parse()


def load_pin(pin_path=PIN_PATH):
    try:
        return json.loads(Path(pin_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtoSchemaError(f"unreadable pin {pin_path}: {exc}") from exc


def pin_errors(root=ROOT, pin_path=PIN_PATH):
    """Re-hash every vendored file PIN.json names; a missing or drifted file is an error."""
    errors = []
    pin = load_pin(pin_path)
    commit = pin.get("upstream", {}).get("commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        errors.append(f"{pin_path}: upstream.commit is not a full 40-hex commit")
    for entry in pin.get("files", []):
        path = Path(root) / entry.get("path", "")
        if not path.is_file():
            errors.append(f"{entry.get('path')}: missing vendored file")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry.get("sha256"):
            errors.append(f"{entry.get('path')}: sha256 {digest} != pinned {entry.get('sha256')}")
        if commit and commit not in entry.get("source", ""):
            errors.append(f"{entry.get('path')}: source URL does not name the pinned commit")
    if not errors and not pin.get("files"):
        errors.append(f"{pin_path}: pins no files")
    return errors


def _pinned_proto_sha(pin_path=PIN_PATH):
    for entry in load_pin(pin_path).get("files", []):
        if entry.get("path") == PROTO_PIN_PATH:
            return entry.get("sha256", "")
    raise ProtoSchemaError(f"{pin_path} pins no {PROTO_PIN_PATH}")


_CACHE = {}


def load_schema(path=PROTO_PATH, expected_sha256=None):
    """Parse the vendored proto, refusing bytes that differ from the pin (fail closed)."""
    path = Path(path)
    expected = expected_sha256 if expected_sha256 is not None else _pinned_proto_sha()
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ProtoSchemaError(f"unreadable schema {path}: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise ProtoSchemaError(f"{path}: sha256 {digest} != pinned {expected}; re-pin deliberately")
    if digest not in _CACHE:
        schema = parse_proto(data.decode("utf-8"))
        schema.sha256 = digest
        _CACHE[digest] = schema
    return _CACHE[digest]


def closure_errors(schema, root="AgentCard"):
    """Fields reachable from `root` whose type the validator does not check (empty = covered)."""
    if root not in schema.messages:
        return [f"{root}: no such message in {schema.package}"]
    problems, seen, todo = [], set(), [root]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        for f in schema.messages[name].fields:
            if f.type in schema.messages:
                todo.append(f.type)
            elif f.type not in VALIDATED_TYPES:
                problems.append(f"{name}.{f.name}: type {f.type!r} is not checked by "
                                "scripts/a2a_schema.py")
            if f.label == "map" and f.key_type != "string":
                problems.append(f"{name}.{f.name}: map key {f.key_type!r} is not checked")
    return sorted(problems)


def required_fields(schema, message="AgentCard"):
    """JSON names of the message's `(google.api.field_behavior) = REQUIRED` fields, in proto order."""
    return [f.json_name for f in schema.messages[message].fields if f.required]


def _is_unset(f, value):
    """proto3 implicit presence: an empty string, false, empty list or map never reaches the wire."""
    if f.label in ("repeated", "map"):
        return len(value) == 0
    if f.label == "optional" or f.type not in ("string", "bool"):
        return False
    return value in ("", False)


def _check_single(schema, type_name, value, path, errors):
    if type_name == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: expected a string")
    elif type_name == "bool":
        if not isinstance(value, bool):
            errors.append(f"{path}: expected true or false")
    elif type_name == "google.protobuf.Struct":
        if not isinstance(value, dict):
            errors.append(f"{path}: expected a JSON object (google.protobuf.Struct)")
    elif type_name in schema.messages:
        _check_message(schema, schema.messages[type_name], value, path, errors)
    else:
        raise ProtoSchemaError(f"{path}: type {type_name!r} is not checked by scripts/a2a_schema.py")


def _check_message(schema, msg, value, path, errors):
    if not isinstance(value, dict):
        errors.append(f"{path}: expected a JSON object ({schema.package}.{msg.name})")
        return
    present = {}
    for key, val in value.items():
        f = msg.lookup(key)
        if f is None:
            errors.append(f"{path}.{key}: unknown field (not in {schema.package}.{msg.name})")
        elif f.name in present:
            errors.append(f"{path}.{key}: field {f.json_name!r} given twice (JSON and proto name)")
        else:
            present[f.name] = (key, val)
    for f in msg.fields:
        key, val = present.get(f.name, (f.json_name, None))
        fpath = f"{path}.{key}"
        if val is None:  # absent, or null, which ProtoJSON reads as the field's default
            if f.required:
                errors.append(f"{fpath}: required field missing")
            continue
        if f.label in ("repeated", "map"):
            want = list if f.label == "repeated" else dict
            if not isinstance(val, want):
                errors.append(f"{fpath}: expected a JSON {'array' if want is list else 'object'}")
                continue
            items = enumerate(val) if want is list else val.items()
            for k, item in items:
                ipath = f"{fpath}[{k}]" if want is list else f"{fpath}[{k!r}]"
                if item is None:
                    errors.append(f"{ipath}: null is not allowed in a {f.label} field")
                else:
                    _check_single(schema, f.type, item, ipath, errors)
        else:
            _check_single(schema, f.type, val, fpath, errors)
        if f.required and _is_unset(f, val):
            errors.append(f"{fpath}: required field is empty (unset on the proto3 wire)")
    for oneof, members in msg.oneofs.items():
        chosen = [present[m][0] for m in members if m in present and present[m][1] is not None]
        if len(chosen) > 1:
            errors.append(f"{path}: oneof {oneof!r} has {len(chosen)} members set "
                          f"({', '.join(chosen)}); at most one")


def schema_errors(card, root="AgentCard", schema=None):
    """Shape and REQUIRED errors of a ProtoJSON value against the pinned `root` message."""
    schema = schema or load_schema()
    uncovered = closure_errors(schema, root)
    if uncovered:
        raise ProtoSchemaError("; ".join(uncovered))
    errors = []
    _check_message(schema, schema.messages[root], card, "$", errors)
    return errors


def _normalize(schema, msg, value):
    """A schema-valid ProtoJSON object with every known field keyed by its JSON name.

    A null is dropped: ProtoJSON reads it as the field's default, i.e. unset, so the semantic
    checks see an absent key and report it -- they never call a string method on None (#636).
    """
    out = {}
    for key, val in value.items():
        f = msg.lookup(key)
        if f is None or val is None:
            continue
        if f.type in schema.messages and val is not None:
            sub = schema.messages[f.type]
            if f.label == "repeated":
                val = [_normalize(schema, sub, v) for v in val]
            elif f.label == "map":
                val = {k: _normalize(schema, sub, v) for k, v in val.items()}
            else:
                val = _normalize(schema, sub, val)
        out[f.json_name] = val
    return out


def _absolute_url(text):
    if not isinstance(text, str):
        return False
    try:
        parts = urlsplit(text)
        return bool(parts.scheme and parts.netloc and parts.hostname)
    except ValueError:  # a malformed authority such as an unclosed IPv6 bracket
        return False


def _security_names(requirements):
    for req in requirements or []:
        yield from (req.get("schemes") or {}).keys()


def semantic_errors(card, schema=None):
    """Checks the proto cannot express; run on a card that already passes schema_errors."""
    schema = schema or load_schema()
    card = _normalize(schema, schema.messages["AgentCard"], card)
    errors = []
    for i, iface in enumerate(card.get("supportedInterfaces") or []):
        where = f"$.supportedInterfaces[{i}]"
        binding, url = iface.get("protocolBinding", ""), iface.get("url", "")
        if binding not in CORE_BINDINGS and not _absolute_url(binding):
            errors.append(f"{where}.protocolBinding: {binding!r} is neither a core binding "
                          f"({', '.join(CORE_BINDINGS)}) nor a custom-binding URI")
        if not _PROTOCOL_VERSION.match(iface.get("protocolVersion", "")):
            errors.append(f"{where}.protocolVersion: expected Major.Minor such as '1.0'")
        grpc_address = binding == "GRPC" and _HOST_PORT.match(url)
        if not grpc_address and not _absolute_url(url):
            errors.append(f"{where}.url: expected an absolute URL"
                          + (" or host:port" if binding == "GRPC" else ""))
    skill_ids = [s.get("id") for s in card.get("skills") or []]
    for dup in sorted({s for s in skill_ids if skill_ids.count(s) > 1}):
        errors.append(f"$.skills: duplicate skill id {dup!r}")
    modes = [("$.defaultInputModes", card.get("defaultInputModes")),
             ("$.defaultOutputModes", card.get("defaultOutputModes"))]
    for i, skill in enumerate(card.get("skills") or []):
        modes += [(f"$.skills[{i}].inputModes", skill.get("inputModes")),
                  (f"$.skills[{i}].outputModes", skill.get("outputModes"))]
    for where, values in modes:
        for mode in values or []:
            if not _MEDIA_TYPE.match(mode):
                errors.append(f"{where}: {mode!r} is not a media type (type/subtype)")
    declared = set((card.get("securitySchemes") or {}).keys())
    for name, scheme in (card.get("securitySchemes") or {}).items():
        if len([v for v in scheme.values() if v is not None]) != 1:
            errors.append(f"$.securitySchemes[{name!r}]: expected exactly one scheme variant")
    requirement_sets = [("$.securityRequirements", card.get("securityRequirements"))]
    requirement_sets += [(f"$.skills[{i}].securityRequirements", s.get("securityRequirements"))
                         for i, s in enumerate(card.get("skills") or [])]
    for where, reqs in requirement_sets:
        for name in _security_names(reqs):
            if name not in declared:
                errors.append(f"{where}: names scheme {name!r} that securitySchemes does not declare")
    for i, sig in enumerate(card.get("signatures") or []):
        for part in ("protected", "signature"):
            if not _BASE64URL.match(sig.get(part, "")):
                errors.append(f"$.signatures[{i}].{part}: expected unpadded base64url")
    uris = [e.get("uri", "") for e in (card.get("capabilities") or {}).get("extensions") or []]
    for i, uri in enumerate(uris):
        if not _absolute_url(uri) and not uri.startswith("urn:"):
            errors.append(f"$.capabilities.extensions[{i}].uri: expected an absolute URI")
    for dup in sorted({u for u in uris if uris.count(u) > 1}):
        errors.append(f"$.capabilities.extensions: duplicate extension uri {dup!r}")
    links = [("$.provider.url", (card.get("provider") or {}).get("url")),
             ("$.documentationUrl", card.get("documentationUrl")), ("$.iconUrl", card.get("iconUrl"))]
    for where, url in links:
        if url is not None and not _absolute_url(url):
            errors.append(f"{where}: expected an absolute URL")
    return errors


def card_errors(card, schema=None):
    """Every reason `card` is not a valid lf.a2a.v1 AgentCard at the pin (empty = valid)."""
    schema = schema or load_schema()
    errors = schema_errors(card, schema=schema)
    return errors or semantic_errors(card, schema=schema)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="a2a_schema.py",
        description="Validate ProtoJSON A2A AgentCards against the pinned lf.a2a.v1 proto.")
    parser.add_argument("cards", nargs="*", help="AgentCard JSON files to validate.")
    parser.add_argument("--required", nargs="?", const="AgentCard", metavar="MESSAGE",
                        help="Print the REQUIRED fields of MESSAGE (default AgentCard).")
    parser.add_argument("--check-pin", action="store_true",
                        help="Re-hash the vendored schema and fixtures against PIN.json.")
    ns = parser.parse_args(argv)
    if not ns.cards and not ns.required and not ns.check_pin:
        parser.error("give AgentCard files, --required or --check-pin")
    return ns


def main(argv=None):
    try:
        ns = parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        if ns.check_pin:
            problems = pin_errors()
            for p in problems:
                print(f"a2a_schema: PIN DRIFT: {p}", file=sys.stderr)
            if problems:
                return 1
            print(f"A2A_SCHEMA_PIN=ok commit={load_pin()['upstream']['commit']}")
        schema = load_schema()
        if ns.required:
            if ns.required not in schema.messages:
                print(f"a2a_schema: no message {ns.required!r} in {schema.package}", file=sys.stderr)
                return 2
            print("\n".join(required_fields(schema, ns.required)))
        status = 0
        for path in ns.cards:
            try:
                card = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"A2A_CARD=invalid {path}\n  unreadable: {exc}", file=sys.stderr)
                status = 1
                continue
            errors = card_errors(card, schema=schema)
            if errors:
                status = 1
                print(f"A2A_CARD=invalid {path}", file=sys.stderr)
                for e in errors:
                    print(f"  {e}", file=sys.stderr)
            else:
                print(f"A2A_CARD=valid {path}")
        return status
    except ProtoSchemaError as exc:
        print(f"a2a_schema: FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
