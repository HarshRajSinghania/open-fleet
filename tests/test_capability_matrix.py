#!/usr/bin/env python3
"""capabilities.json is the single source of truth for what each runtime provider can do (#586)."""
from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = json.loads((ROOT / "runtime" / "providers" / "capabilities.json").read_text(encoding="utf-8"))


def _providers():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module("runtime.providers")


class TestCapabilityMatrix(unittest.TestCase):
    def test_every_registered_provider_has_an_entry(self):
        prov = _providers()
        self.assertEqual(set(prov.SUPPORTED_PROVIDERS), set(MATRIX["providers"]))

    def test_only_vocabulary_names_and_no_overlap(self):
        vocab = set(MATRIX["capabilities"])
        for name, entry in MATRIX["providers"].items():
            native = set(entry["native_capabilities"])
            fallback = set(entry["fallback_capabilities"])
            with self.subTest(provider=name):
                self.assertLessEqual(native | fallback, vocab)
                self.assertFalse(native & fallback)
                self.assertIn("cap:core-orchestration", native)
                self.assertTrue(set(entry["supported_profiles"]) <= {"ro", "rw", "danger"})

    def test_only_orca_has_self_audit(self):
        for name, entry in MATRIX["providers"].items():
            has = "cap:orca-self-audit" in entry["native_capabilities"] + entry["fallback_capabilities"]
            self.assertEqual(has, name == "orca", name)

    def test_provider_classes_report_the_matrix(self):
        prov = _providers()
        base = importlib.import_module("runtime.providers.base")
        for name in ("posix", "orca"):
            cls = prov.get_provider(name, env={"OPEN_FLEET_STATE_DB": "/tmp/_capmatrix.db"}).__class__
            self.assertEqual(cls.capabilities(cls.__new__(cls)), set(MATRIX["providers"][name]["native_capabilities"]))
        self.assertNotIn("capabilities", vars(prov.PosixWorktreeProvider), "no per-class override of the matrix")
        self.assertTrue(callable(base.RuntimeProvider.capabilities))

    def test_sandbox_vm_is_never_claimed_without_a_doctor(self):
        # Only providers that implement a real `vm recipe doctor` may count cap:sandbox-vm.
        prov = _providers()
        base = importlib.import_module("runtime.providers.base")
        for name, entry in MATRIX["providers"].items():
            if name == "orca" or "cap:sandbox-vm" not in entry["native_capabilities"] + entry["fallback_capabilities"]:
                continue  # OrcaProvider.dispatch hands `vm recipe doctor` to the real binary
            mod_name, cls_name = prov._PROVIDER_MODULES[name]
            cls = getattr(importlib.import_module(mod_name, package="runtime.providers"), cls_name)
            self.assertIsNot(cls.vm_recipe_doctor, base.RuntimeProvider.vm_recipe_doctor, name)


if __name__ == "__main__":
    unittest.main()
