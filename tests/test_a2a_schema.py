#!/usr/bin/env python3
"""Contract tests for scripts/a2a_schema.py: the pinned lf.a2a.v1 AgentCard validator (#607).

The validator is only as good as its pin and its coverage, so these tests hold four things:
the vendored bytes still hash to PIN.json; the parser understands every construct the pinned
proto uses and refuses any other; the REQUIRED set matches an independent reading of the proto;
and the upstream example cards pass while the custom offline descriptor and golden mutations of
the upstream card fail. No test fetches anything.
"""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "a2a_schema.py"
EXPORT = ROOT / "scripts" / "a2a_export.py"
FIXTURES = ROOT / "tests" / "fixtures" / "a2a"
SAMPLE = FIXTURES / "upstream-sample-agent-card.json"
CANONICAL = FIXTURES / "upstream-canonicalization-agent-card.json"
PINNED_COMMIT = "1205f45951ca97c209634ce6046180e38c5dfb30"  # the commit #607 names


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


class TestPin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load(SCRIPT, "a2a_schema_pin")

    def test_vendored_files_hash_to_their_pins_at_the_issue_commit(self):
        pin = json.loads((ROOT / "scripts" / "vendor" / "a2a" / "PIN.json").read_text("utf-8"))
        self.assertEqual(pin["upstream"]["commit"], PINNED_COMMIT)
        self.assertEqual(pin["upstream"]["license"], "Apache-2.0")
        paths = {e["path"] for e in pin["files"]}
        self.assertEqual(paths, {
            "scripts/vendor/a2a/a2a.proto", "scripts/vendor/a2a/LICENSE",
            "tests/fixtures/a2a/upstream-sample-agent-card.json",
            "tests/fixtures/a2a/upstream-canonicalization-agent-card.json",
        })
        for entry in pin["files"]:
            digest = hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest()
            self.assertEqual(digest, entry["sha256"], entry["path"])
            self.assertIn(PINNED_COMMIT, entry["source"], entry["path"])
        self.assertEqual(self.mod.pin_errors(), [])

    def test_a_drifted_proto_is_refused_not_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            drifted = Path(tmp) / "a2a.proto"
            drifted.write_bytes(self.mod.PROTO_PATH.read_bytes().replace(
                b"string name = 1 [(google.api.field_behavior) = REQUIRED];",
                b"string name = 1;", 1))
            with self.assertRaisesRegex(self.mod.ProtoSchemaError, "re-pin deliberately"):
                self.mod.load_schema(drifted)

    def test_pin_errors_names_a_drifted_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pin = json.loads(self.mod.PIN_PATH.read_text(encoding="utf-8"))
            for entry in pin["files"]:
                dst = root / entry["path"]
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes((ROOT / entry["path"]).read_bytes())
            (root / "tests/fixtures/a2a/upstream-sample-agent-card.json").write_text("{}\n")
            problems = self.mod.pin_errors(root=root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("upstream-sample-agent-card.json: sha256", problems[0])


class TestParserCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load(SCRIPT, "a2a_schema_cov")
        cls.text = cls.mod.PROTO_PATH.read_text(encoding="utf-8")
        cls.schema = cls.mod.load_schema()

    def test_the_pinned_proto_parses_whole_and_the_agentcard_closure_is_covered(self):
        self.assertEqual(self.schema.package, "lf.a2a.v1")
        self.assertEqual(self.schema.major, "1")
        self.assertIn("AgentCard", self.schema.messages)
        self.assertEqual(set(self.schema.enums), {"TaskState", "Role"})
        self.assertEqual(len(self.schema.services["A2AService"]), 11)
        self.assertEqual(self.mod.closure_errors(self.schema, "AgentCard"), [])

    def test_every_construct_outside_the_covered_set_is_refused(self):
        anchor = "message AgentProvider {\n"
        cases = {
            "reserved": anchor + "  reserved 9;\n",
            "nested message": anchor + "  message Inner { string x = 1; }\n",
            "nested enum": anchor + "  enum Inner { INNER_UNSPECIFIED = 0; }\n",
            "message option": anchor + "  option deprecated = true;\n",
            "proto2 required": anchor + "  required string x = 9;\n",
            "json_name": anchor + "  string x = 9 [json_name = \"y\"];\n",
            "other field_behavior": anchor + "  string x = 9 [(google.api.field_behavior) = OUTPUT_ONLY];\n",
            "extend": "extend AgentProvider { string x = 100; }\n" + anchor,
            "edition": "edition = \"2023\";\n" + anchor,
            "unknown file option": "option optimize_for = SPEED;\n" + anchor,
            "unresolved type": anchor + "  Missing x = 9;\n",
        }
        for label, replacement in cases.items():
            with self.subTest(label):
                self.assertIn(anchor, self.text)
                with self.assertRaises(self.mod.ProtoSchemaError):
                    self.mod.parse_proto(self.text.replace(anchor, replacement, 1))
        with self.assertRaises(self.mod.ProtoSchemaError):
            self.mod.parse_proto(self.text.replace("syntax = \"proto3\";", "syntax = \"proto2\";"))

    def test_a_type_the_validator_does_not_check_under_agentcard_fails_closed(self):
        anchor = "  optional string icon_url = 14;\n"
        self.assertIn(anchor, self.text)
        for decl in ("int64 retries = 20;", "TaskState state = 20;", "bytes logo = 20;",
                     "google.protobuf.Timestamp updated = 20;", "map<int32, string> m = 20;"):
            with self.subTest(decl):
                schema = self.mod.parse_proto(self.text.replace(anchor, anchor + f"  {decl}\n"))
                self.assertTrue(self.mod.closure_errors(schema, "AgentCard"))
                with self.assertRaises(self.mod.ProtoSchemaError):
                    self.mod.schema_errors(sample(), schema=schema)


class TestRequiredFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load(SCRIPT, "a2a_schema_req")
        cls.schema = cls.mod.load_schema()

    def test_required_fields_match_an_independent_reading_of_the_proto(self):
        # Read by hand from a2a.proto at the pin: the `(google.api.field_behavior) = REQUIRED`
        # annotations, written here as ProtoJSON names. The parser must agree field for field.
        expected = {
            "AgentCard": ["name", "description", "supportedInterfaces", "version", "capabilities",
                          "defaultInputModes", "defaultOutputModes", "skills"],
            "AgentInterface": ["url", "protocolBinding", "protocolVersion"],
            "AgentSkill": ["id", "name", "description", "tags"],
            "AgentProvider": ["url", "organization"],
            "AgentCardSignature": ["protected", "signature"],
            "AgentCapabilities": [],
            "AgentExtension": [],
            "OpenIdConnectSecurityScheme": ["openIdConnectUrl"],
        }
        for message, fields in expected.items():
            with self.subTest(message):
                self.assertEqual(self.mod.required_fields(self.schema, message), fields)

    def test_protojson_names_follow_protoc_lower_camel_case(self):
        names = {f.name: f.json_name for f in self.schema.messages["AgentCard"].fields}
        self.assertEqual(names["supported_interfaces"], "supportedInterfaces")
        self.assertEqual(names["icon_url"], "iconUrl")
        oauth = {f.name: f.json_name for f in self.schema.messages["OAuth2SecurityScheme"].fields}
        self.assertEqual(oauth["oauth2_metadata_url"], "oauth2MetadataUrl")


class TestCardValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load(SCRIPT, "a2a_schema_val")
        cls.export = load(EXPORT, "a2a_export_for_schema")

    def errors(self, card):
        return self.mod.card_errors(card)

    def test_both_upstream_example_cards_are_accepted(self):
        for path in (SAMPLE, CANONICAL):
            with self.subTest(path.name):
                self.assertEqual(self.errors(json.loads(path.read_text("utf-8"))), [])

    def test_proto_field_names_are_accepted_as_protojson_requires(self):
        card = sample()
        card["default_input_modes"] = card.pop("defaultInputModes")
        card["supported_interfaces"] = card.pop("supportedInterfaces")
        self.assertEqual(self.errors(card), [])

    def test_the_offline_descriptor_is_rejected_as_a_transport_card(self):
        payload = self.export.build_catalog_cards()
        for descriptor in payload["cards"]:
            with self.subTest(descriptor["id"]):
                errs = self.mod.schema_errors(descriptor)
                for missing in ("supportedInterfaces", "version", "defaultInputModes",
                                "defaultOutputModes", "skills"):
                    self.assertIn(f"$.{missing}: required field missing", errs)
                for unknown in ("schema", "kind", "id", "proof", "identity", "contracts"):
                    self.assertIn(f"$.{unknown}: unknown field (not in lf.a2a.v1.AgentCard)", errs)
                self.assertIn("$.capabilities.stateTransitionHistory: unknown field "
                              "(not in lf.a2a.v1.AgentCapabilities)", errs)
        catalog_errs = self.mod.card_errors(payload)
        self.assertIn("$.cards: unknown field (not in lf.a2a.v1.AgentCard)", catalog_errs)
        self.assertIn("$.name: required field missing", catalog_errs)

    def test_every_required_field_dropped_from_the_upstream_card_is_refused(self):
        schema = self.mod.load_schema()
        for name in self.mod.required_fields(schema, "AgentCard"):
            with self.subTest(name):
                card = sample()
                del card[name]
                self.assertEqual(self.errors(card), [f"$.{name}: required field missing"])
            with self.subTest(f"{name}=null"):
                card = sample()
                card[name] = None
                self.assertEqual(self.errors(card), [f"$.{name}: required field missing"])

    def test_golden_invalid_shapes_are_refused(self):
        def mutate(fn):
            card = sample()
            fn(card)
            return card

        cases = {
            "empty required string": (
                lambda c: c.update(name=""), "$.name: required field is empty"),
            "empty required repeated": (
                lambda c: c.update(skills=[]), "$.skills: required field is empty"),
            "empty required skill tags": (
                lambda c: c["skills"][0].update(tags=[]), "$.skills[0].tags: required field is empty"),
            "nested required missing": (
                lambda c: c["supportedInterfaces"][1].pop("protocolVersion"),
                "$.supportedInterfaces[1].protocolVersion: required field missing"),
            "wrong scalar type": (
                lambda c: c["capabilities"].update(streaming="yes"),
                "$.capabilities.streaming: expected true or false"),
            "string where list": (
                lambda c: c.update(defaultInputModes="text/plain"),
                "$.defaultInputModes: expected a JSON array"),
            "null inside repeated": (
                lambda c: c["defaultOutputModes"].append(None),
                "$.defaultOutputModes[2]: null is not allowed in a repeated field"),
            "unknown nested field": (
                lambda c: c["provider"].update(email="x@y"),
                "$.provider.email: unknown field (not in lf.a2a.v1.AgentProvider)"),
            "two oneof members": (
                lambda c: c["securitySchemes"]["google"].update(
                    mtlsSecurityScheme={"description": "also"}),
                "$.securitySchemes['google']: oneof 'scheme' has 2 members set "
                "(openIdConnectSecurityScheme, mtlsSecurityScheme); at most one"),
            "map value wrong type": (
                lambda c: c["securityRequirements"][0]["schemes"].update(other=["openid"]),
                "$.securityRequirements[0].schemes['other']: expected a JSON object "
                "(lf.a2a.v1.StringList)"),
            "struct not an object": (
                lambda c: c["capabilities"].update(
                    extensions=[{"uri": "https://e.org/x/v1", "params": [1]}]),
                "$.capabilities.extensions[0].params: expected a JSON object "
                "(google.protobuf.Struct)"),
            "json and proto name both given": (
                lambda c: c.update(icon_url=c["iconUrl"]),
                "$.icon_url: field 'iconUrl' given twice (JSON and proto name)"),
        }
        for label, (fn, expected) in cases.items():
            with self.subTest(label):
                errs = self.errors(mutate(fn))
                self.assertTrue(any(e.startswith(expected) for e in errs), errs)

    def test_semantic_errors_the_proto_cannot_express(self):
        def mutate(fn):
            card = sample()
            fn(card)
            return card

        cases = {
            "duplicate skill id": (
                lambda c: c["skills"][1].update(id=c["skills"][0]["id"]),
                "$.skills: duplicate skill id 'route-optimizer-traffic'"),
            "not a media type": (
                lambda c: c["skills"][0]["inputModes"].append("json"),
                "$.skills[0].inputModes: 'json' is not a media type"),
            "protocol version form": (
                lambda c: c["supportedInterfaces"][0].update(protocolVersion="v1"),
                "$.supportedInterfaces[0].protocolVersion: expected Major.Minor"),
            "unknown binding": (
                lambda c: c["supportedInterfaces"][0].update(protocolBinding="SOAP"),
                "$.supportedInterfaces[0].protocolBinding: 'SOAP' is neither a core binding"),
            "relative interface url": (
                lambda c: c["supportedInterfaces"][0].update(url="/a2a/v1"),
                "$.supportedInterfaces[0].url: expected an absolute URL"),
            "undeclared security scheme": (
                lambda c: c["securityRequirements"][0]["schemes"].update(
                    apikey={"list": []}),
                "$.securityRequirements: names scheme 'apikey'"),
            "scheme with no variant": (
                lambda c: c["securitySchemes"].update(empty={}),
                "$.securitySchemes['empty']: expected exactly one scheme variant"),
            "signature not base64url": (
                lambda c: c["signatures"][0].update(signature="a+b/c=="),
                "$.signatures[0].signature: expected unpadded base64url"),
            "duplicate extension uri": (
                lambda c: c["capabilities"].update(extensions=[
                    {"uri": "https://e.org/x/v1"}, {"uri": "https://e.org/x/v1"}]),
                "$.capabilities.extensions: duplicate extension uri"),
            "relative provider url": (
                lambda c: c["provider"].update(url="examplegeoservices"),
                "$.provider.url: expected an absolute URL"),
        }
        for label, (fn, expected) in cases.items():
            with self.subTest(label):
                errs = self.errors(mutate(fn))
                self.assertTrue(any(e.startswith(expected) for e in errs), errs)

    def test_grpc_interfaces_accept_host_port(self):
        card = sample()
        card["supportedInterfaces"][1]["url"] = "grpc.georoute.example.com:443"
        self.assertEqual(self.errors(card), [])
        card["supportedInterfaces"][0]["url"] = "grpc.georoute.example.com:443"  # JSONRPC
        self.assertTrue(self.errors(card))

    def test_validation_never_mutates_the_card(self):
        card = sample()
        before = copy.deepcopy(card)
        self.errors(card)
        self.assertEqual(card, before)


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              capture_output=True, text=True)

    def test_cli_accepts_the_upstream_cards_and_refuses_a_descriptor(self):
        ok = self.run_cli(str(SAMPLE), str(CANONICAL))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(ok.stdout.count("A2A_CARD=valid"), 2)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "descriptor.json"
            made = subprocess.run([sys.executable, str(EXPORT), "--mission", "review-it",
                                   "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            bad = self.run_cli(str(out))
        self.assertEqual(bad.returncode, 1)
        self.assertIn("A2A_CARD=invalid", bad.stderr)
        self.assertIn("$.supportedInterfaces: required field missing", bad.stderr)

    def test_cli_pin_and_required_and_usage(self):
        p = self.run_cli("--check-pin", "--required", "AgentSkill")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(f"A2A_SCHEMA_PIN=ok commit={PINNED_COMMIT}", p.stdout)
        self.assertTrue(p.stdout.rstrip().endswith("id\nname\ndescription\ntags"), p.stdout)
        self.assertEqual(self.run_cli().returncode, 2)


class TestReviewFindings(unittest.TestCase):
    """PR #636 review threads on the semantic checks, each pinned against the pinned proto/spec."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load(SCRIPT, "a2a_schema_review")

    def errors_for(self, fn):
        card = sample()
        fn(card)
        return self.mod.card_errors(card)

    def test_a_null_extension_uri_is_reported_not_raised(self):
        # ProtoJSON reads null as the default, so `"uri": null` passes the shape check; the
        # semantic check must report the missing URI, never raise on the null.
        errs = self.errors_for(lambda c: c["capabilities"].update(
            extensions=[{"uri": None, "description": "no identifier"}]))
        self.assertIn("$.capabilities.extensions[0].uri: expected an absolute URI", errs)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "null-uri.json"
            card = sample()
            card["capabilities"]["extensions"] = [{"uri": None}]
            bad.write_text(json.dumps(card), encoding="utf-8")
            p = subprocess.run([sys.executable, str(SCRIPT), str(bad), str(SAMPLE)],
                               capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertIn(f"A2A_CARD=invalid {bad}", p.stderr)
        self.assertIn(f"A2A_CARD=valid {SAMPLE}", p.stdout)

    def test_media_types_with_parameters_are_accepted(self):
        # a2a.proto: the modes are "Defined as media types"; RFC 9110 section 8.3.1 lets a media
        # type carry `;`-separated token=token or token="quoted" parameters.
        def add(c):
            c["defaultInputModes"].append("text/plain; charset=utf-8")
            c["skills"][0]["outputModes"].append('application/json;profile="https://e.org/p v1"')
            c["skills"][1]["inputModes"].append("text/markdown;variant=GFM ; charset=UTF-8")

        self.assertEqual(self.errors_for(add), [])
        for bad in ("text/plain;", "text/plain; charset", "text/plain; =utf-8",
                    "text/plain; charset=utf 8", 'text/plain; charset="open', "text/plain\n"):
            with self.subTest(bad=bad):
                errs = self.errors_for(lambda c, m=bad: c["defaultOutputModes"].append(m))
                self.assertIn(f"$.defaultOutputModes: {bad!r} is not a media type (type/subtype)",
                              errs)

    def test_grpc_host_port_accepts_a_bracketed_ipv6_literal(self):
        # a2a.proto AgentInterface.url: gRPC uses "hostname:port"; an IPv6 host is written as a
        # bracketed literal (RFC 3986 IP-literal), the form gRPC targets use.
        def grpc(url):
            return lambda c: c["supportedInterfaces"][1].update(url=url)

        for good in ("[2606:4700:4700::1111]:443", "192.0.2.10:8443", "grpc.georoute.example.com:443"):
            with self.subTest(good=good):
                self.assertEqual(self.errors_for(grpc(good)), [])
        for bad in ("[not-an-ip]:443", "2606:4700:4700::1111:443", "[2606:4700::1111]",
                    "[2606:4700::1111]:0", "[2606:4700::1111]:70000", "host:port"):
            with self.subTest(bad=bad):
                self.assertIn("$.supportedInterfaces[1].url: expected an absolute URL or host:port",
                              self.errors_for(grpc(bad)))

    def test_extension_and_binding_identifiers_are_rfc3986_uris_not_hosts(self):
        # a2a.proto AgentExtension.uri: "The unique URI identifying the extension"; spec 5.8: a
        # custom protocolBinding SHOULD be a URI. A URI needs a scheme, not a network host.
        def ext(uri):
            return lambda c: c["capabilities"].update(extensions=[{"uri": uri}])

        for good in ("tag:acme.org,2026:mission-v1", "urn:example:a2a:ext:v1",
                     "https://e.org/ext/v1#part", "https://e.org/ext/%7Euser/v1"):
            with self.subTest(good=good):
                self.assertEqual(self.errors_for(ext(good)), [])
        for bad in ("relative/ext/v1", "ext-v1", "tag:", "1tag:acme.org", "tag:acme org",
                    "https://", "https:///no-host", "tag:a%zz", "tag:a#b#c"):
            with self.subTest(bad=bad):
                self.assertIn("$.capabilities.extensions[0].uri: expected an absolute URI",
                              self.errors_for(ext(bad)))
        self.assertEqual(self.errors_for(lambda c: c["supportedInterfaces"][0].update(
            protocolBinding="tag:acme.org,2026:binding-v1")), [])

    def test_uri_identifiers_are_parsed_by_rfc3986_component(self):
        # PR #636 review: a character-set check let brackets through anywhere and skipped the
        # authority for non-HTTP schemes. RFC 3986 section 3: brackets only around an IP-literal
        # host, an authority's host and port parsed for every scheme, `%` always two hex digits.
        def ext(uri):
            return lambda c: c["capabilities"].update(extensions=[{"uri": uri}])

        for good in ("tag:acme.org,2026:mission-v1", "urn:example:a2a:ext:v1",
                     "custom://[2606:4700::1111]:8443/binding", "custom://[v7.fe:1]/binding",
                     "custom://user:pw@host.internal:/p?q=1/2?#f/?", "custom:///abs/path",
                     "https://e.org/ext/%7Euser/v1;p=1", "mailto:ops@acme.org"):
            with self.subTest(good=good):
                self.assertEqual(self.errors_for(ext(good)), [])
        for bad in ("tag:acme.org,2026:mission[v1", "custom://[not-an-ip]/binding",
                    "custom://[2606:4700::1111/binding", "custom://[fe80::1%eth0]/b",
                    "custom://[v7.]/b", "custom://host.internal:8x/b", "custom://a@b@c/x",
                    "custom://h]st/b", "https://e.org/p?q=[x]", "https://e.org/p#f[1]",
                    "tag:a%2", "tag:a%g1", "https://:443/x", "custom://host.internal:\u0664\u0664\u0663/b"):
            with self.subTest(bad=bad):
                self.assertIn("$.capabilities.extensions[0].uri: expected an absolute URI",
                              self.errors_for(ext(bad)))
        binding_errs = self.errors_for(lambda c: c["supportedInterfaces"][0].update(
            protocolBinding="custom://[not-an-ip]/binding"))
        self.assertTrue(any("protocolBinding" in e for e in binding_errs), binding_errs)
        grpc_errs = self.errors_for(lambda c: c["supportedInterfaces"][1].update(
            url="[2606:4700::1111]:\u0664\u0664\u0663"))  # Arabic-Indic digits are not a port
        self.assertTrue(any(".url: expected an absolute URL" in e for e in grpc_errs), grpc_errs)

    def test_api_key_location_is_query_header_or_cookie(self):
        # a2a.proto APIKeySecurityScheme.location: 'Valid values are "query", "header", or
        # "cookie".' Anything else gives a client no defined place to send the key.
        def api_key(location):
            return lambda c: c["securitySchemes"].update(
                key={"apiKeySecurityScheme": {"location": location, "name": "X-API-Key"}})

        for good in ("query", "header", "cookie"):
            with self.subTest(good=good):
                self.assertEqual(self.errors_for(api_key(good)), [])
        for bad in ("body", "Header", "path"):
            with self.subTest(bad=bad):
                self.assertIn(f"$.securitySchemes['key'].apiKeySecurityScheme.location: {bad!r} "
                              "is not one of query, header, cookie", self.errors_for(api_key(bad)))

    # PR #636 review: urlsplit is a splitter, not a validator. It reports `bad host` as a
    # hostname, leaves port 99999 or 0 to a later `.port` read, and deletes tab/CR/LF, so the
    # card check and the exporter's endpoint check passed URLs no client can dial.
    UNDIALABLE_URLS = (
        "https://bad host/a2a", "https://host:99999/a2a",  # the review's two examples
        "https://fleet.corp.internal:0/a2a", "https://fleet.corp.internal:/a2a",
        "https://fleet.corp.internal:8x/a2a", "https://fleet.corp.internal:+443/a2a",
        "https://fleet.corp.internal:٤٤٣/a2a",
        "https://fleet\t.corp.internal/a2a", "https://fleet.corp.internal/a 2a",
        "https://fleet.corp.internal/a2a\n", " https://fleet.corp.internal/a2a",
        "https://fleet.corp.internal/a2a\x00", "https://fleet.corp.internal/\x7f",
        "https://fleet.corp.internal/a2a ", "https://fleet_1.corp.internal/a2a",
        "https://fleet<1>.corp.internal/a2a", "https://-fleet.corp.internal/a2a",
        "https://fleet..corp.internal/a2a", "https://bücher.corp.internal/a2a",
        "https://999.0.2.10/a2a", "https://192.0.2/a2a", "https://[2606:4700::1111/a2a",
        "https://[fe80::1%25eth0]/a2a", "https://[v7.fe:1]/a2a", "https://[2606:4700::1111]x/a2a",
    )
    DIALABLE_URLS = (
        "https://fleet.corp.internal/a2a/v1", "https://fleet.corp.internal:1/a2a",
        "https://fleet.corp.internal:65535/a2a?tenant=ops&v=1#top",
        "https://FLEET.Corp.Internal./a2a", "https://xn--bcher-kva.corp.internal/a2a",
        "https://192.0.2.10:8443/a2a", "https://[2606:4700:4700::1111]/a2a",
        "https://[2606:4700:4700::1111]:443/a2a?x=%20y",
    )

    def test_a_url_with_a_bad_host_port_or_character_is_refused_by_both_paths(self):
        export = load(EXPORT, "a2a_export_review")

        def url_errors(url):
            return {
                "interface": self.errors_for(
                    lambda c: c["supportedInterfaces"][0].update(url=url)),
                "grpc interface": self.errors_for(
                    lambda c: c["supportedInterfaces"][1].update(url=url)),
                "links": self.errors_for(lambda c: (c["provider"].update(url=url), c.update(
                    documentationUrl=url, iconUrl=url))),
            }

        for bad in self.UNDIALABLE_URLS:
            with self.subTest(bad=bad):
                errs = url_errors(bad)
                self.assertIn("$.supportedInterfaces[0].url: expected an absolute URL",
                              errs["interface"])
                self.assertIn("$.supportedInterfaces[1].url: expected an absolute URL or host:port",
                              errs["grpc interface"])
                for where in ("$.provider.url", "$.documentationUrl", "$.iconUrl"):
                    self.assertIn(f"{where}: expected an absolute URL", errs["links"])
                endpoint = export.endpoint_errors(bad, "JSONRPC")
                self.assertEqual(len(endpoint), 1, endpoint)
                self.assertIn(f"--endpoint {bad!r}: malformed URL (", endpoint[0])
        for good in self.DIALABLE_URLS + ("http://fleet.corp.internal:8080/a2a",
                                          "https://user@fleet.corp.internal/a2a"):
            with self.subTest(good=good):
                self.assertEqual(url_errors(good),
                                 {"interface": [], "grpc interface": [], "links": []})
        for good in self.DIALABLE_URLS:
            with self.subTest(endpoint=good):
                self.assertEqual(export.endpoint_errors(good, "JSONRPC"), [])
                card = export.build_standard_card(good, "HTTP+JSON", mission="review-it")
                self.assertEqual(self.mod.card_errors(card), [])

    # A gRPC host:port address judges its host by the URL rule, so a host one path refuses the
    # other refuses: the regex alone let `999.1.1.1:443` and `a..b:443` through (#636).
    UNDIALABLE_HOSTS = (
        "999.1.1.1", "a..b", "1.2.3.04", "192.0.2", "fleet-.corp.internal",
        "-fleet.corp.internal", "fleet_1.corp.internal", "x" * 64 + ".corp.internal",
        "[fe80::1%eth0]", "[v7.fe:1]", "[not-an-ip]", "",
    )
    DIALABLE_HOSTS = (
        "fleet.corp.internal", "FLEET.Corp.Internal", "fleet.corp.internal.",
        "xn--bcher-kva.corp.internal", "x" * 63 + ".corp.internal", "192.0.2.10",
        "[2606:4700:4700::1111]",
    )

    def test_a_grpc_host_port_uses_the_url_host_rule(self):
        export = load(EXPORT, "a2a_export_grpc_review")

        def grpc(url):
            return lambda c: c["supportedInterfaces"][1].update(url=url)

        for host in self.UNDIALABLE_HOSTS + self.DIALABLE_HOSTS:
            with self.subTest(same_rule=host):
                self.assertEqual(self.mod.grpc_address(f"{host}:443") is not None,
                                 self.mod._absolute_url(f"https://{host}:443/a2a"))
        for host in self.UNDIALABLE_HOSTS:
            with self.subTest(bad=host):
                self.assertIsNone(self.mod.grpc_address(f"{host}:443"))
                self.assertIn("$.supportedInterfaces[1].url: expected an absolute URL or host:port",
                              self.errors_for(grpc(f"{host}:443")))
                endpoint = export.endpoint_errors(f"{host}:443", "GRPC")
                self.assertEqual(len(endpoint), 1, endpoint)
                self.assertIn("a GRPC endpoint is host:port", endpoint[0])
        for host in self.DIALABLE_HOSTS:
            for port in (1, 443, 65535):
                with self.subTest(good=host, port=port):
                    address = f"{host}:{port}"
                    self.assertEqual(self.mod.grpc_address(address), (host, port))
                    self.assertEqual(self.errors_for(grpc(address)), [])
                    self.assertEqual(export.endpoint_errors(address, "GRPC"), [])
            with self.subTest(card=host):
                card = export.build_standard_card(f"{host}:443", "GRPC", mission="review-it")
                self.assertEqual(self.mod.card_errors(card), [])

    def test_anchored_forms_refuse_a_trailing_newline(self):
        # PR #636 review: `re.match` with a pattern ending in `$` also matches just before a final
        # "\n", so "1.0\n" passed as Major.Minor and "abc\n" as base64url. Every form check now
        # uses fullmatch, and ASCII digits only: `\d` also matches Arabic-Indic digits.
        export = load(EXPORT, "a2a_export_anchor_review")

        def version(v):
            return lambda c: c["supportedInterfaces"][0].update(protocolVersion=v)

        for bad in ("1.0\n", "1.0\r\n", "١.٠", "1.0 ", "1.", "v1.0"):
            with self.subTest(version=bad):
                self.assertIn("$.supportedInterfaces[0].protocolVersion: expected Major.Minor "
                              "such as '1.0'", self.errors_for(version(bad)))
        for good in ("1.0", "10.25", "0.3"):
            with self.subTest(version=good):
                self.assertEqual(self.errors_for(version(good)), [])
        for part in ("protected", "signature"):
            for bad in ("abc\n", "abc\r\n", "abc=", "ab c", "abc١"):
                with self.subTest(part=part, bad=bad):
                    errs = self.errors_for(lambda c, p=part, b=bad: c["signatures"][0].update({p: b}))
                    self.assertIn(f"$.signatures[0].{part}: expected unpadded base64url", errs)
        with self.assertRaisesRegex(export.ExportError, "expected Major.Minor"):
            export.build_standard_card("https://fleet.corp.internal/a2a", "JSONRPC",
                                       protocol_version="1.0\n")
        self.assertEqual(self.mod.load_schema().major, "1")
        self.assertEqual(self.mod.Schema(package="lf.a2a.v1\n", imports=[], messages={},
                                         enums={}, services={}).major, "")

    def test_struct_values_are_walked_and_every_number_is_finite(self):
        # PR #636 review: the Struct check stopped at the outer object, and valid JSON such as
        # 1e999 reads as infinity. google.protobuf.Struct carries numbers as IEEE doubles, so NaN,
        # an infinity or an integer past the double range has no faithful ProtoJSON form.
        params = "$.capabilities.extensions[0].params"
        header = "$.signatures[0].header"

        def struct(value, field="params"):
            if field == "header":
                return lambda c: c["signatures"][0].update(header=value)
            return lambda c: c["capabilities"].update(
                extensions=[{"uri": "https://e.org/x/v1", "params": value}])

        cases = {
            "1e999": (struct({"value": float("inf")}),
                      f"{params}['value']: inf is not a finite number"),
            "-Infinity": (struct({"value": float("-inf")}),
                          f"{params}['value']: -inf is not a finite number"),
            "NaN nested in a list": (struct({"a": {"b": [1, float("nan")]}}),
                                     f"{params}['a']['b'][1]: nan is not a finite number"),
            "integer past a double": (struct({"big": 2 ** 1024}),
                                      f"{params}['big']: integer overflows a double"),
            "not a JSON value": (struct({"t": (1, 2)}), f"{params}['t']: tuple is not a JSON value"),
            "non-string key": (struct({1: "x"}), f"{params}: key 1 is not a string"),
            "signature header": (struct({"jwk": {"x": [float("inf")]}}, "header"),
                                 f"{header}['jwk']['x'][0]: inf is not a finite number"),
        }
        for label, (fn, expected) in cases.items():
            with self.subTest(label):
                errs = self.errors_for(fn)
                self.assertTrue(any(e.startswith(expected) for e in errs), errs)
        deep = {}
        cursor = deep
        for _ in range(5000):  # a stack walk, so nesting depth is no RecursionError
            cursor["a"] = {}
            cursor = cursor["a"]
        cursor["n"] = 1.5
        good = {"null": None, "bool": True, "text": "x", "max": 1.7976931348623157e308,
                "negative zero": -0.0, "int": 2 ** 64, "int near max": 10 ** 308,
                "lists": [[], {}, [1.5, None, "y", False]], "deep": deep}
        for field in ("params", "header"):
            with self.subTest(good=field):
                self.assertEqual(self.errors_for(struct(good, field)), [])

    def test_the_cli_reports_unrepresentable_or_unreadable_json_without_a_traceback(self):
        # 1e999 and the NaN/Infinity tokens parse to non-finite floats; a 5000-digit integer, deep
        # nesting and non-UTF-8 bytes raise ValueError or RecursionError while reading (#636).
        def with_params(token):
            card = sample()
            card["capabilities"]["extensions"] = [{"uri": "https://e.org/x/v1",
                                                   "params": {"value": "@N@"}}]
            return json.dumps(card).replace('"@N@"', token).encode("utf-8")

        files = {
            "overflow.json": (with_params("1e999"), "inf is not a finite number"),
            "nan.json": (with_params("NaN"), "nan is not a finite number"),
            "infinity.json": (with_params("-Infinity"), "-inf is not a finite number"),
            "digits.json": (with_params("9" * 5000), "unreadable"),
            "deep.json": (b"[" * 100000, "unreadable"),
            "latin1.json": (b'{"name": "caf\xe9"}', "unreadable"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, (data, expected) in files.items():
                with self.subTest(name):
                    path = Path(tmp) / name
                    path.write_bytes(data)
                    p = subprocess.run([sys.executable, str(SCRIPT), str(path), str(SAMPLE)],
                                       capture_output=True, text=True)
                    self.assertEqual(p.returncode, 1, p.stderr)
                    self.assertNotIn("Traceback", p.stderr)
                    self.assertIn(f"A2A_CARD=invalid {path}", p.stderr)
                    self.assertIn(expected, p.stderr)
                    self.assertIn(f"A2A_CARD=valid {SAMPLE}", p.stdout)


if __name__ == "__main__":
    unittest.main()
