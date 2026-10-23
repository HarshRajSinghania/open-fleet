#!/usr/bin/env python3
"""capabilities.json may claim a harness for a provider only if spawn_worker.sh launches it (#596).

The provider-certification first run found Orca's entry claiming opencode, omp and pi while the
public wrapper refused all three there for every profile: the matrix advertised routes no
coordinator could dispatch. test_capability_harnesses.py holds each list to the ADAPTER's table;
this holds every claimed (provider, harness) pair to the WRAPPER. A pair agrees when
spawn_worker.sh resolves a launch for at least one profile the provider advertises (ro or rw;
danger is gated on a sandbox doctor, never on the harness table), read through the script's own
SW_PRINT_LAUNCH contract hook, which stops before any orchestration call or launch.

The only claim outside the CLI harness roster is openhands' own SDK agent, which no spawn_worker
row launches; it is named below so no other non-CLI claim can hide behind it.
"""
from __future__ import annotations

import concurrent.futures
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

base = importlib.import_module("runtime.providers.base")
SPAWN = ROOT / "runtime" / "scripts" / "spawn_worker.sh"
CAPS = json.loads((ROOT / "runtime" / "providers" / "capabilities.json").read_text(encoding="utf-8"))["providers"]
CLI_HARNESSES = frozenset(base.SUPPORTED_HARNESSES)
# (provider, harness) claims no spawn_worker row can launch, each with the reason it is allowed.
NON_CLI_CLAIMS = {("openhands", "openhands"): "the provider runs the OpenHands SDK agent itself"}
LAUNCH_PROFILES = ("rw", "ro")  # rw first: it is the profile most harnesses can launch


def resolve_launch(provider: str, agent: str, profile: str) -> tuple[int, str | None, str]:
    """spawn_worker.sh's resolved launch for `agent` under `profile` on `provider` (no side effect)."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", tmp), "SP": tmp, "SHELL": "/bin/sh",
               "SW_PRINT_LAUNCH": "1", "PROFILE": profile, "OPEN_FLEET_RUNTIME": provider,
               "OPEN_FLEET_STATE_DB": str(Path(tmp) / "s.db")}
        if provider == "orca":
            env["ORCA_CLI_COMMAND"] = "orca"
        if profile == "rw":
            env["ORCA_COORD_ALLOW_AUTONOMOUS_WRITE"] = "1"
        p = subprocess.run(["bash", str(SPAWN), "task_x", "path:/tmp/of-wt", "t", agent, "high"],
                           env=env, capture_output=True, text=True, timeout=120)
        launch = next((ln[len("LAUNCH="):] for ln in p.stdout.splitlines() if ln.startswith("LAUNCH=")), None)
        return p.returncode, launch, p.stderr


def pair_launches(provider: str, agent: str) -> tuple[bool, str]:
    """True when some advertised non-danger profile resolves a launch; else the last refusal."""
    why = "the provider advertises neither ro nor rw"
    for profile in LAUNCH_PROFILES:
        if profile not in CAPS[provider]["supported_profiles"]:
            continue
        rc, launch, err = resolve_launch(provider, agent, profile)
        if rc == 0 and launch:
            return True, f"{profile}: {launch}"
        why = f"{profile}: rc={rc} {err.strip()[-200:]}"
    return False, why


class CapabilityClaimsMatchTheWrapper(unittest.TestCase):
    def test_every_claimed_cli_pair_launches_through_spawn_worker(self) -> None:
        pairs = [(p, h) for p, entry in sorted(CAPS.items()) for h in entry["supported_harnesses"]
                 if (p, h) not in NON_CLI_CLAIMS]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            verdicts = dict(zip(pairs, pool.map(lambda ph: pair_launches(*ph), pairs), strict=True))
        refused = {f"{p}/{h}": why for (p, h), (ok, why) in verdicts.items() if not ok}
        self.assertEqual(sorted(refused), [], "capabilities.json claims pairs spawn_worker.sh refuses:\n"
                         + "\n".join(f"  {pair}  {why}" for pair, why in sorted(refused.items())))

    def test_only_the_named_claims_sit_outside_the_cli_roster(self) -> None:
        outside = {(p, h) for p, entry in CAPS.items() for h in entry["supported_harnesses"]
                   if h not in CLI_HARNESSES}
        self.assertEqual(outside, set(NON_CLI_CLAIMS))

    def test_the_probe_sees_a_refusal_and_a_launch(self) -> None:
        # Negative control on the checker itself: a pair the wrapper refuses for every profile
        # reads as refused, and one it launches reads as launched.
        ok, why = pair_launches("orca", "opencode")
        self.assertFalse(ok, why)
        rc, launch, err = resolve_launch("orca", "opencode", "rw")
        self.assertEqual((rc, launch), (2, None), err)
        self.assertIn("no verified PROFILE=rw launch flag", err)
        ok, why = pair_launches("orca", "claude")
        self.assertTrue(ok, why)


if __name__ == "__main__":
    unittest.main()
