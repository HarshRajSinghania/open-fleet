#!/usr/bin/env python3
"""quarantine_check.py — the fleet-wide component off-switch (#558).

Reads runtime/quarantine.json, a checked-in deny-list of components (mission,
playbook, upstream pack) a human has declared unusable. Three gates consume it:

    scripts/validate.py      the catalog may not route through a quarantined
                             component: no mission may compose a quarantined
                             playbook, pins.json may not pin a quarantined pack
                             (it builds the catalog view and imports violations()
                             from here, so the matching rule exists once)
    preflight.py --mission   a run may not start on a quarantined mission or on
                             playbooks it composes (invariant, exit 2)
    this CLI                 ad hoc checks and the tests

Semantics, stated because they bound what this is worth: quarantine is a
checked-in file, so it takes effect on checkouts that contain it; it cannot
reach an already-running worker or a stale clone. It is the fast, reversible,
auditable rung of the response ladder (runtime/threat-model.md), not a remote
kill. Entries are HUMAN acts only — parse refuses an entry whose `by` names no
human, so an agent cannot quarantine (or, by editing, un-quarantine) anything
through the sanctioned shape.

Fail-closed, with one deliberate exception: a root with NO
runtime/quarantine.json is not a fleet catalog (preflight runs in target
repos), so there is simply no quarantine in force — the CLI says so on stderr
rather than passing silently. A PRESENT but malformed deny-list refuses every
gate: it never reads as an empty one. validate.py additionally requires the
file to exist in this repo.

Usage:
    quarantine_check.py [--root DIR] --catalog
    quarantine_check.py [--root DIR] --mission <name>
    # exit 0 = nothing quarantined is in play; 2 = violation;
    # 3 = cannot evaluate (unreadable/malformed deny-list, bad root)

Stdlib-only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

KINDS = ("mission", "playbook", "pack")
_HEX = re.compile(r"^[0-9a-f]{7,40}$")
# Mirrors decisions.py's human-grant name rule verbatim (same repo, same audit
# purpose): person-shaped, and never an agent role wearing a human: prefix.
_HUMAN_NAME = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")
_RESERVED_HUMAN_NAMES = frozenset({
    "agent", "ai", "anonymous", "auto", "automatic", "bot", "coordinator",
    "fleet", "human", "model", "nobody", "none", "orca", "system",
    "unknown", "worker",
})
_CLAUSE = re.compile(
    r"\b(?:Composes|COMPOSES|composes|Rides|RIDES|rides)\b\s+(.+?)(?:\n\n|\Z)", re.DOTALL
)


def parse_quarantine(data):
    """(entries, errors) from already-parsed JSON. Shape errors are loud."""
    errors = []
    if not isinstance(data, dict) or not isinstance(data.get("quarantined"), list):
        return [], ["quarantine.json: expected an object with a 'quarantined' list"]
    entries = []
    for i, raw in enumerate(data["quarantined"]):
        where = f"quarantine.json entry {i}"
        if not isinstance(raw, dict):
            errors.append(f"{where}: not an object")
            continue
        component = raw.get("component", "")
        kind, _, name = component.partition(":") if isinstance(component, str) else ("", "", "")
        if kind not in KINDS or not name or ":" in name:
            errors.append(
                f"{where}: component must be '<kind>:<name>' with kind in "
                f"{'/'.join(KINDS)} (got {component!r})"
            )
            continue
        ref = raw.get("ref", "*")
        if ref != "*" and not _HEX.fullmatch(str(ref)):
            errors.append(f"{where}: ref must be '*' or at least 7 hex chars (got {ref!r})")
            continue
        if not str(raw.get("reason", "")).strip():
            errors.append(f"{where}: reason is required — a quarantine with no reason is a rumor")
            continue
        try:
            datetime.datetime.strptime(str(raw.get("date", "")), "%Y-%m-%d")
        except ValueError:
            errors.append(f"{where}: date must be YYYY-MM-DD (got {raw.get('date')!r})")
            continue
        # Same person-shape rule as decisions.py's human grants: a bare
        # `human:` or an agent role (human:agent, human:coordinator, …) names
        # no person, and the audit trail must name one.
        by_match = re.fullmatch(r"human:(\S+)", str(raw.get("by", "")))
        by_name = by_match.group(1) if by_match else ""
        if not _HUMAN_NAME.fullmatch(by_name) or by_name.lower() in _RESERVED_HUMAN_NAMES:
            errors.append(
                f"{where}: by must be 'human:<name>' naming a person — entries are "
                "human acts, never agent-added"
            )
            continue
        entries.append(
            {"kind": kind, "name": name, "ref": str(ref),
             "reason": str(raw["reason"]), "by": str(raw["by"])}
        )
    return entries, errors


def load_quarantine(root):
    """(entries, errors, present) for <root>/runtime/quarantine.json.

    Absent (does not lexist) is the only silent state. A directory, a broken
    symlink, invalid UTF-8, or bad JSON at that path is present-but-unusable:
    an error, never an empty list.
    """
    path = Path(root) / "runtime" / "quarantine.json"
    if not os.path.lexists(path):
        return [], [], False
    if not path.is_file():
        return [], [f"{path}: present but not a regular file — refusing to "
                    "treat an unusable deny-list as an absent one"], True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        return [], [f"{path}: cannot parse ({err})"], True
    entries, errors = parse_quarantine(data)
    return entries, errors, True


def _ref_matches(ref, commit):
    if ref == "*":
        return True
    if not commit:
        return False
    return commit.startswith(ref) or ref.startswith(commit)


def violations(entries, view):
    """Quarantine violations against a catalog view.

    view = {"missions": set[str],
            "composes": {mission: set[playbook-name]},
            "pins": {pack: commit}}
    A quarantined mission still present is itself the violation a spawn gate
    refuses; the catalog gate only needs the routing checks, so callers that
    want catalog semantics pass missions=set() — see validate.py.
    """
    out = []
    for e in entries:
        label = f"{e['kind']}:{e['name']} (quarantined by {e['by']}: {e['reason']})"
        if e["kind"] == "mission" and e["name"] in view.get("missions", set()):
            out.append(f"mission {e['name']} is quarantined — {label}")
        elif e["kind"] == "playbook":
            for mission, playbooks in sorted(view.get("composes", {}).items()):
                if e["name"] in playbooks:
                    out.append(
                        f"mission {mission} composes quarantined playbook "
                        f"{e['name']} — {label}"
                    )
        elif e["kind"] == "pack":
            if view.get("pins_error"):
                out.append(
                    f"pack {e['name']} cannot be cleared — {view['pins_error']} "
                    f"— refusing rather than assuming the quarantined pack is unused"
                )
                continue
            commit = view.get("pins", {}).get(e["name"])
            if commit is not None and _ref_matches(e["ref"], commit):
                out.append(
                    f"pack {e['name']} is pinned at quarantined ref {commit} — {label}"
                )
    return out


def _playbook_names(root):
    playbooks = Path(root) / "playbooks"
    if not playbooks.is_dir():
        return set()
    return {p.stem for p in playbooks.glob("*.md")}


def _composed_playbooks(skill_text, playbook_names):
    """Playbooks named in Composes/rides clauses. Over-matching is the safe
    direction for a refusal gate; the catalog gate (validate.py) passes its
    own precise extraction into violations() instead."""
    found = set()
    for clause in _CLAUSE.findall(skill_text):
        for token in re.findall(r"`([^`]+)`", clause):
            stem = token[:-3] if token.endswith(".md") else token
            if stem in playbook_names:
                found.add(stem)
    return found


def mission_view(root, mission):
    skill = Path(root) / "skills" / mission / "SKILL.md"
    text = skill.read_text(encoding="utf-8") if skill.exists() else ""
    pins, pins_error = pins_view(root)
    return {
        "missions": {mission},
        "composes": {mission: _composed_playbooks(text, _playbook_names(root))},
        "pins": pins,
        "pins_error": pins_error,
    }


def pins_view(root):
    """({pack: commit}, error-or-None) for <root>/runtime/pins.json.

    Absent pins (a target repo) is a clean empty map. Present-but-unreadable
    pins beside a pack quarantine entry must not read as "pack unused":
    the error rides the view and violations() turns it into a refusal.
    """
    path = Path(root) / "runtime" / "pins.json"
    if not os.path.lexists(path):
        return {}, None
    if not path.is_file():
        return {}, f"{path}: present but not a regular file"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        return {}, f"{path}: cannot parse ({err})"
    if not isinstance(data, dict):
        return {}, f"{path}: expected a JSON object"
    return {
        name: str(meta.get("commit", ""))
        for name, meta in data.items()
        if not name.startswith("_") and isinstance(meta, dict)
    }, None


def catalog_view(root):
    skills = Path(root) / "skills"
    playbooks = _playbook_names(root)
    missions, composes = set(), {}
    if skills.is_dir():
        for skill_dir in sorted(skills.iterdir()):
            skill = skill_dir / "SKILL.md"
            if skill_dir.is_dir() and skill.exists():
                missions.add(skill_dir.name)
                composes[skill_dir.name] = _composed_playbooks(
                    skill.read_text(encoding="utf-8"), playbooks
                )
    pins, pins_error = pins_view(root)
    return {"missions": missions, "composes": composes,
            "pins": pins, "pins_error": pins_error}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="catalog root (default: cwd)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--catalog", action="store_true", help="check the whole catalog")
    mode.add_argument("--mission", metavar="NAME", help="check one mission and its playbooks")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"quarantine_check: root {root} is not a directory", file=sys.stderr)
        return 3
    entries, errors, present = load_quarantine(root)
    if errors:
        for error in errors:
            print(f"quarantine_check: {error}", file=sys.stderr)
        return 3
    if not present:
        print(
            f"quarantine_check: no runtime/quarantine.json under {root} — "
            "no quarantine in force (not a fleet catalog?)",
            file=sys.stderr,
        )
        return 0
    if args.catalog:
        view = catalog_view(root)
        present = sorted(
            e["name"] for e in entries
            if e["kind"] == "mission" and e["name"] in view["missions"]
        )
        for name in present:
            print(
                f"QUARANTINED mission {name} present in the catalog "
                "(dispatch refused at preflight; files preserved as evidence)"
            )
        view = {**view, "missions": set()}  # presence is the designed state
    else:
        view = mission_view(root, args.mission)
    found = violations(entries, view)
    for violation in found:
        print(f"QUARANTINED {violation}")
    if found:
        return 2
    print("quarantine_check: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
