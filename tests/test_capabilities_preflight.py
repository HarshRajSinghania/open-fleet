#!/usr/bin/env python3
"""Contract and negative-control tests for Wave 0 & Issue #586.

Covers:
1. `runtime/providers/capabilities.json` completeness and invariants across all
   8 capabilities, 14 RPI providers, and every catalog mission.
2. `runtime/scripts/preflight.py` capability-based enforcement (`--runtime`,
   `OPEN_FLEET_RUNTIME`, `ORCA_FLEET_RUNTIME`, `--strict-native-capabilities`,
   `--json`), including negative controls (`--mission pin-it --runtime posix`
   failing closed with exit 2 and `missing_capability: cap:orca-self-audit`).
3. Wave 0 neutral env var precedence (`OPEN_FLEET_EGRESS_LEDGER` in `egress.py`,
   `OPEN_FLEET_DECISIONS_FILE` in `decisions.py`, `OPEN_FLEET_GATE_MANIFEST` and
   `OPEN_FLEET_UNIT_CLASS` in `verify-gate.sh`).
4. `docs/runtimes.md` and `skills/*/SKILL.md` multi-runtime compatibility.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPABILITIES_JSON = ROOT / "runtime" / "providers" / "capabilities.json"
PREFLIGHT = ROOT / "runtime" / "scripts" / "preflight.py"
EGRESS = ROOT / "runtime" / "scripts" / "egress.py"
DECISIONS = ROOT / "runtime" / "scripts" / "decisions.py"
VERIFY_GATE = ROOT / "runtime" / "scripts" / "verify-gate.sh"
SKILLS_DIR = ROOT / "skills"
RUNTIMES_DOC = ROOT / "docs" / "runtimes.md"
DOCS_README = ROOT / "docs" / "README.md"

_pf_spec = importlib.util.spec_from_file_location("preflight", PREFLIGHT)
preflight = importlib.util.module_from_spec(_pf_spec)
_pf_spec.loader.exec_module(preflight)

_eg_spec = importlib.util.spec_from_file_location("egress", EGRESS)
egress = importlib.util.module_from_spec(_eg_spec)
_eg_spec.loader.exec_module(egress)

_dec_spec = importlib.util.spec_from_file_location("decisions", DECISIONS)
decisions = importlib.util.module_from_spec(_dec_spec)
_dec_spec.loader.exec_module(decisions)

EXPECTED_CAPABILITIES = {
    "cap:core-orchestration",
    "cap:sandbox-vm",
    "cap:session-search",
    "cap:browser",
    "cap:mobile-emulator",
    "cap:issue-tracker",
    "cap:scheduler",
    "cap:orca-self-audit",
}

EXPECTED_PROVIDERS = {
    "orca",
    "posix",
    "overstory",
    "t3code",
    "ao",
    "superset",
    "gastown",
    "worktrunk",
    "jcode-swarm",
    "emdash",
    "vibe-kanban",
    "paperclip",
    "multiclaude",
    "openhands",
}


def _ALL_TOOLS(name):
    return f"/stub/bin/{name}"


def _stub_tools(directory, *names):
    for name in names:
        tool = Path(directory) / name
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)


def run_preflight(*argv, cwd=None, env=None):
    import contextlib
    import io
    from unittest import mock

    run_env = dict(os.environ if env is None else env)
    if env is None:
        run_env.pop("OPEN_FLEET_RUNTIME", None)
        run_env.pop("ORCA_FLEET_RUNTIME", None)
    with mock.patch.dict(os.environ, run_env, clear=True):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            try:
                preflight.main(list(argv))
            except SystemExit:
                pass
    return subprocess.run(
        [sys.executable, str(PREFLIGHT), *argv],
        capture_output=True,
        text=True,
        cwd=cwd or ROOT,
        env=run_env,
        timeout=60,
    )


class TestCapabilitiesMatrixSchema(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(CAPABILITIES_JSON.read_text(encoding="utf-8"))

    def test_declares_all_eight_capabilities(self):
        caps = self.data.get("capabilities", {})
        self.assertEqual(set(caps.keys()), EXPECTED_CAPABILITIES)
        for cap_id, meta in caps.items():
            self.assertTrue(meta.get("description"), f"{cap_id} lacks description")

    def test_declares_all_fourteen_providers_and_restricts_orca_self_audit(self):
        providers = self.data.get("providers", {})
        self.assertEqual(set(providers.keys()), EXPECTED_PROVIDERS)
        for name, p in providers.items():
            with self.subTest(provider=name):
                native = set(p.get("native_capabilities", []))
                fallback = set(p.get("fallback_capabilities", []))
                harnesses = p.get("supported_harnesses", [])
                self.assertIn("cap:core-orchestration", native)
                self.assertTrue(native.issubset(EXPECTED_CAPABILITIES))
                self.assertTrue(fallback.issubset(EXPECTED_CAPABILITIES))
                self.assertEqual(native & fallback, set(), f"{name} overlaps native and fallback")
                # A provider lists only the harnesses it can actually launch (multiclaude is
                # claude-only, jcode-swarm jcode-only) — never the full table by default.
                self.assertGreaterEqual(len(harnesses), 1)
                if name == "orca":
                    self.assertIn("cap:orca-self-audit", native)
                else:
                    self.assertNotIn("cap:orca-self-audit", native | fallback)
                # Every portable capability is available natively or via fallback. cap:sandbox-vm
                # is the exception: it is claimed only where a real `vm recipe doctor` exists, so
                # an adapter that refuses PROFILE=danger must not appear to offer it.
                self.assertEqual(
                    (native | fallback) - {"cap:orca-self-audit", "cap:sandbox-vm"},
                    EXPECTED_CAPABILITIES - {"cap:orca-self-audit", "cap:sandbox-vm"},
                )

    def test_declares_every_catalog_mission(self):
        missions = self.data.get("missions", {})
        on_disk = {
            d.name
            for d in SKILLS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith((".", "_")) and (d / "SKILL.md").is_file()
        }
        self.assertEqual(set(missions.keys()), on_disk)
        for m, entry in missions.items():
            with self.subTest(mission=m):
                req = entry.get("required", [])
                opt = entry.get("optional", [])
                self.assertIn("cap:core-orchestration", req)
                self.assertTrue(set(req).issubset(EXPECTED_CAPABILITIES))
                self.assertTrue(set(opt).issubset(EXPECTED_CAPABILITIES))
        self.assertIn("cap:orca-self-audit", missions["pin-it"]["required"])
        self.assertIn("cap:mobile-emulator", missions["field-test-it"]["required"])
        self.assertIn("cap:sandbox-vm", missions["offload-it"]["required"])


class TestPreflightCapabilitiesEnforcement(unittest.TestCase):
    def test_pin_it_on_posix_fails_closed_with_missing_capability(self):
        r = run_preflight("--mission", "pin-it", "--runtime", "posix")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("missing_capability: cap:orca-self-audit", r.stderr)

    def test_pin_it_on_posix_json_output_includes_missing_capability(self):
        r = run_preflight("--mission", "pin-it", "--runtime", "posix", "--json")
        self.assertEqual(r.returncode, 2, r.stderr)
        payload = json.loads(r.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["missing_capability"], "cap:orca-self-audit")
        self.assertIn("cap:orca-self-audit", payload["missing_capabilities"])

    def test_pin_it_on_orca_passes(self):
        r = run_preflight("--mission", "pin-it", "--runtime", "orca", "--mode", "readonly")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("preflight: OK", r.stdout)

    def test_ship_it_on_posix_passes(self):
        r = run_preflight("--mission", "ship-it", "--runtime", "posix", "--mode", "readonly")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("preflight: OK", r.stdout)

    def test_runtime_write_mode_still_requires_base(self):
        r = run_preflight("--mission", "ship-it", "--runtime", "posix", "--mode", "write")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("--base", r.stderr)

    def test_all_general_missions_pass_across_all_providers(self):
        data = json.loads(CAPABILITIES_JSON.read_text(encoding="utf-8"))
        for provider in EXPECTED_PROVIDERS:
            for mission in data["missions"]:
                # Fallback tooling stubbed present: this test is about the matrix, not the host.
                if mission == "pin-it" and provider != "orca":
                    refusal, info = preflight._capabilities_refusal(mission, provider, which=_ALL_TOOLS)
                    self.assertIsNotNone(refusal)
                    self.assertEqual(info["missing_capability"], "cap:orca-self-audit")
                elif "cap:sandbox-vm" in data["missions"][mission]["required"] and provider not in ("orca", "posix"):
                    # Adapters that refuse PROFILE=danger (no certifiable sandbox) must refuse here
                    # too, not pass preflight and fail at the first danger launch.
                    refusal, info = preflight._capabilities_refusal(mission, provider, which=_ALL_TOOLS)
                    self.assertIsNotNone(refusal, f"{mission} must refuse on {provider}")
                    self.assertEqual(info["missing_capability"], "cap:sandbox-vm")
                else:
                    refusal, info = preflight._capabilities_refusal(mission, provider, which=_ALL_TOOLS)
                    self.assertIsNone(refusal, f"{mission} failed on {provider}: {refusal}")
                    self.assertTrue(info["ok"])

    def test_strict_native_capabilities_mode(self):
        # offload-it requires cap:sandbox-vm: fallback on posix (Docker probed), native on orca only
        with tempfile.TemporaryDirectory() as tmp:
            _stub_tools(Path(tmp), "docker")
            env = {**os.environ, "PATH": tmp + os.pathsep + os.environ.get("PATH", "")}
            env.pop("OPEN_FLEET_RUNTIME", None)
            env.pop("ORCA_FLEET_RUNTIME", None)
            r_fallback = run_preflight(
                "--mission", "offload-it", "--runtime", "posix", "--mode", "readonly", env=env
            )
        self.assertEqual(r_fallback.returncode, 0, r_fallback.stderr)
        self.assertIn("by fallback", r_fallback.stderr)
        self.assertIn("cap:sandbox-vm via docker", r_fallback.stderr)

        r_strict_fail = run_preflight(
            "--mission", "offload-it", "--runtime", "posix", "--strict-native-capabilities"
        )
        self.assertEqual(r_strict_fail.returncode, 2, r_strict_fail.stderr)
        self.assertIn("missing_capability: cap:sandbox-vm", r_strict_fail.stderr)

        r_strict_ok = run_preflight(
            "--mission",
            "offload-it",
            "--runtime",
            "orca",
            "--strict-native-capabilities",
            "--mode",
            "readonly",
        )
        self.assertNotIn("missing_capability", r_strict_ok.stderr)

        # openhands has no certifiable `vm recipe doctor`: no sandbox-vm, natively or otherwise.
        r_oh = run_preflight("--mission", "offload-it", "--runtime", "openhands", "--mode", "readonly")
        self.assertEqual(r_oh.returncode, 2, r_oh.stderr)
        self.assertIn("missing_capability: cap:sandbox-vm", r_oh.stderr)

    def test_unknown_runtime_fails_closed(self):
        r = run_preflight("--mission", "ship-it", "--runtime", "not-a-provider")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("unknown_runtime", r.stderr)

    def test_env_runtime_precedence_open_fleet_over_orca(self):
        env_posix = {**os.environ, "OPEN_FLEET_RUNTIME": "posix", "ORCA_FLEET_RUNTIME": "orca"}
        r_fail = run_preflight("--mission", "pin-it", "--mode", "readonly", env=env_posix)
        self.assertEqual(r_fail.returncode, 2, r_fail.stderr)
        self.assertIn("missing_capability: cap:orca-self-audit", r_fail.stderr)

        env_orca = {**os.environ, "OPEN_FLEET_RUNTIME": "orca", "ORCA_FLEET_RUNTIME": "posix"}
        r_ok = run_preflight("--mission", "pin-it", "--mode", "readonly", env=env_orca)
        self.assertEqual(r_ok.returncode, 0, r_ok.stderr)

    def test_malformed_capabilities_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            (fake_root / "runtime" / "providers").mkdir(parents=True)
            (fake_root / "runtime" / "providers" / "capabilities.json").write_text(
                "{corrupt-json", encoding="utf-8"
            )
            env = {**os.environ, "OPEN_FLEET_ROOT": str(fake_root)}
            r = run_preflight("--mission", "ship-it", "--runtime", "posix", env=env)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("capabilities.json is malformed", r.stderr)


class TestFallbackProbesAndSharedResolver(unittest.TestCase):
    """#586: a fallback counts only when its tooling is present, and the runtime
    name resolves through dispatch's own resolver (runtime/providers)."""

    def _resolve(self, runtime, **env):
        from unittest import mock
        with mock.patch.dict(os.environ, env, clear=True):
            refusal, info = preflight._capabilities_refusal(None, runtime)
        self.assertIsNone(refusal, refusal)
        return info["runtime"]

    def test_field_test_it_on_posix_refuses_without_emulator_tooling(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": tmp, "HOME": tmp}
            r = run_preflight("--mission", "field-test-it", "--runtime", "posix", "--mode",
                              "readonly", "--json", env=env)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("missing_capability: cap:mobile-emulator", r.stderr)
            self.assertIn("adb", r.stderr)
            payload = json.loads(r.stdout)
            self.assertFalse(payload["fallback_probes"]["cap:mobile-emulator"]["ok"])

    def test_field_test_it_on_posix_passes_with_adb_and_reports_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            _stub_tools(Path(tmp), "adb")
            refusal, info = preflight._capabilities_refusal(
                "field-test-it", "posix", which=lambda t: shutil.which(t, path=tmp))
            self.assertIsNone(refusal, refusal)
            self.assertEqual(info["fallbacks_used"], ["cap:mobile-emulator"])
            self.assertTrue(info["fallback_probes"]["cap:mobile-emulator"]["found"])
            self.assertIn("cap:browser", info["optional_unavailable"] + info["fallback_capabilities"])

    def test_offload_it_on_posix_refuses_non_docker_sandbox_tools(self):
        # posix only sandboxes through Docker: bwrap/podman/gondolin alone must not
        # pass preflight and then fail at the first danger launch.
        with tempfile.TemporaryDirectory() as tmp:
            _stub_tools(Path(tmp), "bwrap", "podman", "gondolin")
            refusal, info = preflight._capabilities_refusal(
                "offload-it", "posix", which=lambda t: shutil.which(t, path=tmp))
            self.assertIsNotNone(refusal)
            self.assertEqual(info["missing_capability"], "cap:sandbox-vm")
            self.assertEqual(info["fallback_probes"]["cap:sandbox-vm"]["tools"], ["docker"])
            self.assertIn("docker", refusal)
            r = run_preflight("--mission", "offload-it", "--runtime", "posix", "--mode",
                              "readonly", env={"PATH": tmp, "HOME": tmp})
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("missing_capability: cap:sandbox-vm", r.stderr)
            _stub_tools(Path(tmp), "docker")
            refusal, info = preflight._capabilities_refusal(
                "offload-it", "posix", which=lambda t: shutil.which(t, path=tmp))
            self.assertIsNone(refusal, refusal)
            self.assertEqual(info["fallback_probes"]["cap:sandbox-vm"]["found"], "docker")

    def test_sandbox_fallback_without_a_provider_probe_fails_closed(self):
        from unittest import mock
        with mock.patch.object(preflight, "PROVIDER_FALLBACK_PROBES", {}):
            refusal, info = preflight._capabilities_refusal("offload-it", "posix", which=_ALL_TOOLS)
        self.assertIsNotNone(refusal)
        self.assertEqual(info["missing_capability"], "cap:sandbox-vm")
        self.assertIn("no probed fallback launch path", refusal)

    def test_native_capability_is_never_probed(self):
        refusal, info = preflight._capabilities_refusal(
            "field-test-it", "orca", which=lambda t: None)
        self.assertIsNone(refusal, refusal)
        self.assertEqual(info["fallback_probes"], {})

    def test_local_posix_alias_maps_to_posix(self):
        self.assertEqual(self._resolve("local-posix", PATH=""), "posix")
        r = run_preflight("--mission", "pin-it", "--runtime", "local-posix")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("runtime 'posix'", r.stderr)

    def test_auto_orca_dev_repo_root_with_only_orca_dev_on_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            _stub_tools(Path(tmp), "orca-dev")
            self.assertEqual(
                self._resolve("auto", PATH=tmp, ORCA_DEV_REPO_ROOT="/src/orca"), "orca")
            # Without the dev root the platform binary is wanted, and it is absent.
            self.assertEqual(self._resolve("auto", PATH=tmp), "posix")

    def test_auto_nonexistent_cli_command_is_posix(self):
        self.assertEqual(
            self._resolve("auto", PATH="", ORCA_CLI_COMMAND="/nonexistent/orca"), "posix")

    def test_auto_linux_orca_ide_only(self):
        from unittest import mock
        # Pin the platform: the Linux binary-name rule is tested on every host, never skipped.
        with mock.patch("platform.system", return_value="Linux"), tempfile.TemporaryDirectory() as tmp:
            _stub_tools(Path(tmp), "orca-ide")
            self.assertEqual(self._resolve("auto", PATH=tmp), "orca")
        with mock.patch("platform.system", return_value="Linux"), tempfile.TemporaryDirectory() as tmp:
            _stub_tools(Path(tmp), "orca")  # the macOS name does not count on Linux
            self.assertEqual(self._resolve("auto", PATH=tmp), "posix")

    def test_mission_without_runtime_checks_against_orca(self):
        r = run_preflight("--mission", "pin-it", "--mode", "readonly", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["runtime"], "orca")
        r_bad = run_preflight("--mission", "no-such-mission", "--mode", "readonly")
        self.assertEqual(r_bad.returncode, 2, r_bad.stderr)
        self.assertIn("unknown_mission", r_bad.stderr)


class TestWave0NeutralEnvVars(unittest.TestCase):
    def test_open_fleet_egress_ledger_works_and_outranks_orca_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "open-fleet-egress.jsonl"
            legacy = Path(tmp) / "orca-egress.jsonl"
            env = {
                **os.environ,
                "OPEN_FLEET_EGRESS_LEDGER": str(primary),
                "ORCA_EGRESS_LEDGER": str(legacy),
            }
            w = subprocess.run(
                [
                    sys.executable,
                    str(EGRESS),
                    "write",
                    "--sink",
                    "pr-open",
                    "--host",
                    "github.com",
                    "--payload-class",
                    "pr-body",
                    "--consent",
                    "grant:pr-open",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(w.returncode, 0, w.stderr)
            self.assertTrue(primary.is_file())
            self.assertFalse(legacy.exists())

            v = subprocess.run(
                [sys.executable, str(EGRESS), "verify"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(v.returncode, 0, v.stderr)

    def test_open_fleet_decisions_file_works_and_outranks_orca_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "OPEN_DECISIONS.md"
            legacy = Path(tmp) / "ORCA_DECISIONS.md"
            env = {
                **os.environ,
                "OPEN_FLEET_DECISIONS_FILE": str(primary),
                "ORCA_DECISIONS_FILE": str(legacy),
            }
            a = subprocess.run(
                [
                    sys.executable,
                    str(DECISIONS),
                    "append",
                    "--id",
                    "gate-wave0",
                    "--class",
                    "mechanical",
                    "--answer",
                    "ok",
                    "--why",
                    "verified neutral env precedence",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(a.returncode, 0, a.stderr)
            self.assertTrue(primary.is_file())
            self.assertFalse(legacy.exists())

            c = subprocess.run(
                [sys.executable, str(DECISIONS), "check"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(c.returncode, 0, c.stderr)

    def test_verify_gate_honors_open_fleet_gate_manifest_and_unit_class(self):
        script_text = VERIFY_GATE.read_text(encoding="utf-8")
        self.assertIn("OPEN_FLEET_GATE_MANIFEST", script_text)
        self.assertIn("OPEN_FLEET_UNIT_CLASS", script_text)
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nonexistent-manifest.json"
            env = {
                **os.environ,
                "OPEN_FLEET_GATE_MANIFEST": str(missing),
                "OPEN_FLEET_UNIT_CLASS": "report-only",
            }
            r = subprocess.run(
                ["sh", str(VERIFY_GATE)],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn(str(missing), r.stderr)


class TestRuntimesDocumentationAndCompatibility(unittest.TestCase):
    def test_runtimes_doc_exists_and_is_linked_from_docs_readme(self):
        self.assertTrue(RUNTIMES_DOC.is_file(), "docs/runtimes.md is missing")
        text = RUNTIMES_DOC.read_text(encoding="utf-8")
        for provider in EXPECTED_PROVIDERS:
            self.assertIn(f"`{provider}`", text)
        for cap in EXPECTED_CAPABILITIES:
            self.assertIn(f"`{cap}`", text)
        readme = DOCS_README.read_text(encoding="utf-8")
        self.assertIn("(runtimes.md)", readme)

    def test_general_missions_declare_open_fleet_rpi_in_compatibility(self):
        for d in sorted(SKILLS_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith((".", "_")):
                continue
            text = (d / "SKILL.md").read_text(encoding="utf-8")
            if d.name == "pin-it":
                self.assertIn("Orca runtime + orchestration skill (Orca CLI)", text)
            else:
                self.assertIn("open-fleet RPI runtime (Orca, posix,", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
