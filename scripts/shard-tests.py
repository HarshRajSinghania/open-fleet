#!/usr/bin/env python3
"""Split the unittest suite into N shards for CI matrix fan-out.

The catalog-gates journey (validate + full suite + proof_status) ran ~260 s
sequentially when this was written and ~670 s by the 2026-10-14 re-measure, ~9x over its 30 s budget, and the cost is diffuse per-test
process fan-out no single hotspot fix can remove (see the speed-it self-test
report, docs/runs/campaign-2026-09-16-speed-it/REPORT.md). This script is the
reversible half of that run's parked infra gate: it partitions tests/test_*.py
into N shards so CI runs them in parallel jobs while unittest stays the runner
and no test dependency is added (the suite is stdlib-only by design).

Shards are FILE-level by default: splitting a module across processes re-runs
its setUpModule/setUpClass fixtures in every shard that holds a piece of it, so
a module stays whole unless its weight file records CLASS weights. Those few
modules (test_wip_curve alone is a third of the CI wall) are split into one
unit per live TestCase class, `test_wip_curve.TestGate`, and the shard runs
`python -m unittest tests.test_wip_curve.TestGate` — the same loader, the same
test IDs. The class list is read from the imported module at partition time,
the way unittest's own loader reads it, so a class added later lands in a
shard without anyone recording it (it takes the module's median class weight).

Weights live one JSON file per module in tests/shard-weights/ (CI speed and
bookkeeping change): adding a test module adds its own file and never edits a
line another change edits. They steer balance only, never correctness — the
partition always covers every discovered module (and every live class of a
split one) exactly once, which tests/test_shard_tests.py proves against live
discovery, ID by ID. A module with no weight file still runs: it takes the
median module weight, and the freshness test asks for the file.

Weight file, tests/shard-weights/test_<name>.json:
  {"seconds": 12.3, "measured": "<when, where, how>"}
  optional "classes": {"<TestCaseClass>": seconds, ...} splits the module by
  class; optional "fixture_seconds": module-level setup every shard holding a
  piece of a split module pays again. Seconds are wall seconds on CI's 3.13
  coverage lane, or a local measurement scaled to it; ratios are what steer.

Usage:
  python3 scripts/shard-tests.py --list [--of N]      print the partition
  python3 scripts/shard-tests.py --shard I --of N     run shard I (1-based)
  python3 scripts/shard-tests.py --check [--of N]     assert full coverage
  python3 scripts/shard-tests.py --measure test_<name> [--scale F]
                                                      time one module, per class;
                                                      prints a weight file

  --shard takes --with-coverage: the shard's unittest runs wrapped in
  `coverage run --parallel-mode`, one data file per shard for CI to combine.
  Tracing cannot cross into run_shard's unittest subprocess any other way —
  `coverage run` around THIS script would measure the sharder, not the suite.

Adding tests/test_<name>.py: add tests/shard-weights/test_<name>.json. The
quickest honest number is `python3 scripts/shard-tests.py --measure
test_<name> --scale 2` (one local run; 2 is roughly the CI-lane factor of a
fast laptop) redirected into that file. The weights-freshness test fails until
you do, so a new file can neither silently join the wrong shard nor silently
run nowhere. Re-measuring an EXISTING module is a rebalance PR's job, not a
feature PR's, so two feature PRs never edit the same weight file.
"""
import sys

# W3-01: `python3 <dir>/<script>.py` puts <dir> at sys.path[0], AHEAD of the stdlib, so a committed
# sibling named like a stdlib module (json.py, hashlib.py) would BE that module here, and no
# toolchain hash binds it. Drop that entry before any other import (`from __future__` imports too,
# which is why this file has none); `os` is read from sys.modules, loaded at start-up, never
# imported. `python3 -I` does the same from outside; this holds when a caller forgets it.
if (__name__ == "__main__" and not getattr(sys.flags, "safe_path", False) and sys.path
        and ("os" not in sys.modules or sys.modules["os"].path.realpath(sys.path[0])
             == sys.modules["os"].path.dirname(sys.modules["os"].path.realpath(__file__)))):
    del sys.path[0]

import argparse
import functools
import importlib
import json
import statistics
import subprocess
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
WEIGHTS_DIR = TESTS_DIR / "shard-weights"
DEFAULT_SHARDS = 6
WEIGHT_KEYS = {"seconds", "measured", "classes", "fixture_seconds"}


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def load_weights(directory=WEIGHTS_DIR):
    """({module: seconds}, {module: {class: seconds}}, {module: fixture seconds}).

    One file per module, so the table has no shared line. A malformed file raises
    ValueError naming it: a weight the sharder cannot read is a broken checkout, and
    every shard failing loudly beats one shard quietly running the wrong set.
    """
    weights, classes, fixtures = {}, {}, {}
    for path in sorted(Path(directory).glob("*.json")):
        name = path.stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ValueError(f"{path}: unreadable weight file ({err})") from None
        if not isinstance(data, dict):
            raise ValueError(f"{path}: a weight file is one JSON object")
        unknown = sorted(set(data) - WEIGHT_KEYS)
        if unknown:
            raise ValueError(f"{path}: unknown keys {unknown} (allowed: {sorted(WEIGHT_KEYS)})")
        if not name.startswith("test_"):
            raise ValueError(f"{path}: weight files are named after a test module, test_<name>.json")
        if not _positive(data.get("seconds")):
            raise ValueError(f"{path}: \"seconds\" must be a positive number")
        if not isinstance(data.get("measured"), str) or not data["measured"].strip():
            raise ValueError(f"{path}: \"measured\" must say when and how the seconds were taken")
        weights[name] = float(data["seconds"])
        if "classes" in data:
            split = data["classes"]
            if (not isinstance(split, dict) or not split
                    or not all(isinstance(k, str) and k.isidentifier() and _positive(v)
                               for k, v in split.items())):
                raise ValueError(f"{path}: \"classes\" maps TestCase class names to positive seconds")
            classes[name] = {k: float(v) for k, v in split.items()}
        if "fixture_seconds" in data:
            fixture = data["fixture_seconds"]
            if "classes" not in data or not (fixture == 0 or _positive(fixture)):
                raise ValueError(f"{path}: \"fixture_seconds\" is a non-negative number, "
                                 "and only a module split by class has one")
            fixtures[name] = float(fixture)
    return weights, classes, fixtures


WEIGHTS, CLASS_WEIGHTS, FIXTURE_SECONDS = load_weights()


def discover_modules():
    """Every tests/test_*.py module stem, sorted. The partition input."""
    return sorted(p.stem for p in TESTS_DIR.glob("test_*.py"))


@functools.lru_cache(maxsize=None)
def live_classes(module):
    """The TestCase classes unittest would load from tests/<module>.py, by attribute name.

    The same walk as TestLoader.loadTestsFromModule: every module attribute that is a TestCase
    subclass with at least one test (an empty base class collects nothing anywhere). None means
    the module cannot be split — it fails to import, or it defines load_tests, whose protocol may
    collect what no class attribute names — so it runs whole and unittest reports why.
    """
    # ROOT goes on sys.path deliberately (W3-01 review): this IMPORTS the checkout's own tests/
    # package — the graded tree's code, which CI runs anyway — so a root-level file shadowing a
    # stdlib module gains nothing that tests/ itself does not already have. Never a gate's model.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        mod = importlib.import_module(f"tests.{module}")
    except Exception:  # an import error is the shard's to report, whole and unsplit
        return None
    if hasattr(mod, "load_tests"):
        return None
    loader = unittest.TestLoader()
    found = []
    for name in dir(mod):
        obj = getattr(mod, name)
        if (isinstance(obj, type) and issubclass(obj, unittest.TestCase)
                and obj not in (unittest.TestCase, unittest.FunctionTestCase)
                and loader.getTestCaseNames(obj)):
            found.append(name)
    return tuple(sorted(found))


def _fallback(weights):
    ordered = sorted(weights.values())
    return ordered[len(ordered) // 2] if ordered else 1.0


def units(modules, weights=None, classes=None):
    """[(unit, module, seconds)]: a module whole, or one `module.Class` per live class of a
    module whose weights record classes. Unknown modules take the median module weight; a
    class the record has not seen takes its module's median class weight."""
    weights = WEIGHTS if weights is None else weights
    classes = {} if classes is None else classes
    fallback = _fallback(weights)
    out = []
    for mod in modules:
        live = live_classes(mod) if mod in classes else None
        if live:
            recorded = classes[mod]
            default = statistics.median(recorded.values())
            out += [(f"{mod}.{cls}", mod, recorded.get(cls, default)) for cls in live]
        else:
            out.append((mod, mod, weights.get(mod, fallback)))
    return out


def partition(modules, n, weights=None, classes=None, fixtures=None):
    """LPT assignment of units to n shards; deterministic, total coverage.

    Greedy longest-processing-time: heaviest unit first onto the currently
    lightest shard, ties broken by shard index then unit name, so the same
    inputs always produce the same shards; each shard comes back sorted, its
    run order. With no weights given, the recorded
    weights and class splits apply (what CI runs); explicit weights alone split
    nothing. A piece of a split module charges its shard the module's fixture
    once. Unknown weights degrade balance gracefully; coverage never degrades.
    """
    if n < 1:
        raise ValueError(f"shard count must be >= 1, got {n}")
    if weights is None:
        weights = WEIGHTS
        classes = CLASS_WEIGHTS if classes is None else classes
        fixtures = FIXTURE_SECONDS if fixtures is None else fixtures
    fixtures = {} if fixtures is None else fixtures
    loads = [0.0] * n
    shards = [[] for _ in range(n)]
    present = [set() for _ in range(n)]
    for unit, mod, seconds in sorted(units(modules, weights, classes),
                                     key=lambda u: (-u[2], u[0])):
        i = min(range(n), key=lambda j: (loads[j], j))
        shards[i].append(unit)
        loads[i] += seconds
        if unit != mod and mod not in present[i]:
            loads[i] += fixtures.get(mod, 0.0)
        present[i].add(mod)
    # Run order, not assignment order: a split module's classes sit together, so unittest
    # runs its setUpModule/tearDownModule once per shard instead of once per interleaving.
    return [sorted(shard) for shard in shards]


def predicted_wall(shard, weights=None, classes=None, fixtures=None):
    """Predicted seconds for one shard: its units, plus each split module's fixture once."""
    if weights is None:
        weights = WEIGHTS
        classes = CLASS_WEIGHTS if classes is None else classes
        fixtures = FIXTURE_SECONDS if fixtures is None else fixtures
    classes = {} if classes is None else classes
    fixtures = {} if fixtures is None else fixtures
    fallback = _fallback(weights)
    total, split_seen = 0.0, set()
    for unit in shard:
        mod, _, cls = unit.partition(".")
        if cls:
            recorded = classes.get(mod) or {}
            default = statistics.median(recorded.values()) if recorded else fallback
            total += recorded.get(cls, default)
            if mod not in split_seen:
                total += fixtures.get(mod, 0.0)
                split_seen.add(mod)
        else:
            total += weights.get(mod, fallback)
    return round(total, 1)


def check(shards, modules):
    """Coverage errors: anything missing, doubled, or an empty shard.

    A module is covered once whole, or once per live class when it is split — never both,
    or its classes would run twice.
    """
    errors = []
    seen = {}
    for i, shard in enumerate(shards, start=1):
        if not shard:
            errors.append(f"shard {i} is empty — a CI job that runs zero tests and passes")
        for unit in shard:
            if unit in seen:
                errors.append(f"{unit} is in shards {seen[unit]} and {i}")
            seen[unit] = i
    whole = {u for u in seen if "." not in u}
    split = {}
    for unit in seen:
        mod, _, cls = unit.partition(".")
        if cls:
            split.setdefault(mod, set()).add(cls)
    for mod in sorted(whole & set(split)):
        errors.append(f"{mod} runs whole and split by class — its classes would run twice")
    for mod in sorted(set(modules) - whole - set(split)):
        errors.append(f"{mod} is in no shard — it would silently stop running")
    for mod in sorted((whole | set(split)) - set(modules)):
        errors.append(f"{mod} is sharded but no longer exists under tests/")
    for mod in sorted(set(split) & set(modules)):
        live = live_classes(mod)
        if live is None:
            errors.append(f"{mod} is split by class but does not load as one — run it whole")
            continue
        for cls in sorted(set(live) - split[mod]):
            errors.append(f"{mod}.{cls} is in no shard — it would silently stop running")
        for cls in sorted(split[mod] - set(live)):
            errors.append(f"{mod}.{cls} is sharded but {mod} has no such test class")
    return errors


def shard_command(shard, with_coverage=False):
    """The argv run_shard executes: unittest over the shard's units, optionally
    wrapped in `coverage run --parallel-mode` (one data file per shard; CI
    combines them before the report). A pure function so the contract test can
    pin the wrap shape without coverage installed — the suite is stdlib-only."""
    # Repo-root cwd with tests.-prefixed ids: tests assume root cwd (running
    # from tests/ reds test_inventory), and this matches the suite contract.
    # A class unit is the dotted name unittest's loader takes as it is.
    cmd = [sys.executable, "-m", "unittest"] + [f"tests.{m}" for m in shard]
    if with_coverage:
        cmd = ([sys.executable, "-m", "coverage", "run", "--parallel-mode"]
               + cmd[1:])
    return cmd


def run_shard(index, n, with_coverage=False):
    modules = discover_modules()
    shards = partition(modules, n)
    errors = check(shards, modules)
    if errors:
        for e in errors:
            print(f"shard-tests: {e}", file=sys.stderr)
        return 1
    shard = shards[index - 1]
    wall = predicted_wall(shard)
    print(f"shard {index}/{n}: {len(shard)} units, predicted ~{wall}s: "
          + " ".join(shard), flush=True)
    r = subprocess.run(shard_command(shard, with_coverage), cwd=ROOT)
    return r.returncode


class _Timed(unittest.TextTestResult):
    """Wall seconds per test, gaps included, so setUpClass lands on its class's first test."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last = time.perf_counter()
        self.spent = []

    def stopTest(self, test):
        super().stopTest(test)
        now = time.perf_counter()
        self.spent.append((type(test).__name__, now - self.last))
        self.last = now


def measure(module, scale=1.0, stream=None):
    """Run one module in this process and return its weight record, per class.

    `fixture_seconds` is the time before its first test ran (setUpModule and the first
    class's setUpClass): an upper bound on what a split shard pays again.
    """
    if str(ROOT) not in sys.path:  # deliberate: runs the checkout's own tests (see live_classes)
        sys.path.insert(0, str(ROOT))
    start = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromName(f"tests.{module}")
    runner = unittest.TextTestRunner(stream=stream or sys.stderr, resultclass=_Timed,
                                     verbosity=0)
    result = runner.run(suite)
    wall = time.perf_counter() - start
    per_class = {}
    for name, seconds in result.spent:
        per_class[name] = per_class.get(name, 0.0) + seconds
    record = {"seconds": round(max(wall * scale, 0.1), 1),
              "measured": f"{time.strftime('%Y-%m-%d')}: one local run of tests.{module} "
                          f"({result.testsRun} tests, Python {sys.version.split()[0]}), "
                          f"x{scale:g} to the CI lane"}
    if per_class:
        record["classes"] = {k: round(max(v * scale, 0.1), 1) for k, v in sorted(per_class.items())}
        first = result.spent[0][1] if result.spent else 0.0
        record["fixture_seconds"] = round(first * scale, 1)
    return record, result.wasSuccessful()


def main(argv=None):
    parser = argparse.ArgumentParser(description="shard the unittest suite for CI fan-out")
    parser.add_argument("--of", type=int, default=DEFAULT_SHARDS,
                        help="shard count (must match the CI matrix)")
    parser.add_argument("--list", action="store_true", help="print the partition")
    parser.add_argument("--check", action="store_true", help="assert full coverage")
    parser.add_argument("--shard", type=int, help="1-based shard to run")
    parser.add_argument("--with-coverage", action="store_true",
                        help="wrap the shard run in `coverage run --parallel-mode`")
    parser.add_argument("--measure", metavar="MODULE",
                        help="time one test module per class and print its weight file")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="--measure: multiply local seconds by this CI-lane factor")
    args = parser.parse_args(argv)
    if args.of < 1:
        print(f"shard-tests: --of must be >= 1, got {args.of}", file=sys.stderr)
        return 2
    if args.measure:
        if args.measure not in discover_modules() or args.scale <= 0:
            print(f"shard-tests: --measure takes a tests/test_*.py module stem and a positive "
                  f"--scale, got {args.measure!r} x{args.scale:g}", file=sys.stderr)
            return 2
        record, ok = measure(args.measure, args.scale)
        print(json.dumps(record, indent=2))
        if not ok:
            print(f"shard-tests: tests.{args.measure} failed; a red run's time is not a weight",
                  file=sys.stderr)
        return 0 if ok else 1
    modules = discover_modules()
    if args.list or args.check:
        shards = partition(modules, args.of)
        if args.list:
            for i, shard in enumerate(shards, start=1):
                print(f"shard {i}/{args.of}: ~{predicted_wall(shard)}s: "
                      + " ".join(shard))
        errors = check(shards, modules)
        for e in errors:
            print(f"shard-tests: {e}", file=sys.stderr)
        return 1 if errors else 0
    if args.shard is not None:
        if not 1 <= args.shard <= args.of:
            print(f"shard-tests: --shard {args.shard} out of range for --of {args.of}",
                  file=sys.stderr)
            return 2
        return run_shard(args.shard, args.of, args.with_coverage)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
