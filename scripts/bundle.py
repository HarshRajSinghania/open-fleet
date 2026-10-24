#!/usr/bin/env python3
"""Build self-contained missions for installers that copy skill directories.

The three-layer separation is why the catalog works: a mission references its
playbooks and runtime policies by BARE NAME, and they live two directories up.
A symlink install preserves that. A plugin install copies the whole repo, so it
preserves it too. An installer that copies `skills/<name>/` *out* of the tree
severs every one of those references, and the mission then runs half-blind with
nothing saying so (docs/reviews/2026-09-10-review.md §8 P2-18).

This makes a distribution tree where each mission carries its own copies:

    dist/skills/<name>/SKILL.md
    dist/skills/<name>/references/<protocol>.md      one per composed/ridden doc
    dist/skills/<name>/references/ARCHITECTURE.md    root docs it links
    dist/skills/<name>/runtime/scripts/             executable runtime + helpers
    dist/skills/<name>/runtime/*.json               runtime data
    dist/skills/<name>/docs/runs/TEMPLATE.md        mandatory run-report template

Every `runtime/scripts/<file>` a vendored document names becomes
`"$OPEN_FLEET_ROOT/runtime/scripts/<file>"`, so a worker running from the project repository
can execute the documented command as written instead of substituting the root by hand.

It also rewrites the SKILL.md so nothing points outside the mission directory:
`](../../ARCHITECTURE.md)` becomes `](references/ARCHITECTURE.md)`, and one line
points at `references/README.md`, the generated index naming each protocol's local
copy. Bare names in the Composes/rides clause are left alone — they are the
mission's vocabulary, not paths — and that index is what resolves them.

`dist/` is generated, never committed: vendoring 21 copies of the doctrine tree
into git would make every runtime edit a 21-file diff and the copies would rot
between edits. Build it at release time, or before running a copy installer.

    python3 scripts/bundle.py                 # build dist/
    python3 scripts/bundle.py --out /tmp/x    # build somewhere else
    python3 scripts/bundle.py --check         # build to a temp dir and verify only

A build records every file it writes in `<out>/.open-fleet-bundle.json`; a rebuild deletes only
those, and refuses (exit 2, nothing deleted) when anything else sits where it would write.

Exit: 0 built and verified · 1 a reference could not be resolved · 2 could not run (or refused
an --out holding content a previous build did not write).
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

_spec = importlib.util.spec_from_file_location("_validate", ROOT / "scripts" / "validate.py")
validate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate)
_grammar = validate._grammar

# `](../../X.md)` and `](../../dir/X.md)` — the outbound links the rewriter knows how to vendor.
OUTBOUND_LINK_RE = re.compile(r"\]\((?:\.\./)+([A-Za-z0-9_./-]+\.md)(#[^)]*)?\)")
# Every link that leaves the directory, whatever its extension. The rewriter only vendors `.md`,
# but the CHECK has to see the rest: `](../../runtime/scripts/verify.py)` was neither rewritten nor
# flagged, so dist/ could ship a link pointing nowhere with --check green (#316).
OUTBOUND_ANY_RE = re.compile(r"\]\((?:\.\./)+([A-Za-z0-9_./-]+)(#[^)]*)?\)")
# A relative link that does NOT climb out with `../`. A vendored doc keeps the repo-root-relative
# links it was written with — `](runtime/evidence-manifest.md)` — and from `references/` those
# resolve under `references/`, where nothing was copied. They escape nothing, so OUTBOUND_ANY_RE
# never saw them, and 56 of them shipped dead while --check stayed green (PR #308 review, P1).
RELATIVE_LINK_RE = _grammar.RELATIVE_LINK_RE
REFERENCES = "references"
# A runtime path as a protocol spells it: repo-root-relative, because in the repository that is
# where it is. Beside an installed mission it is not, and the worker runs from the PROJECT
# repository, where `runtime/scripts/` is absent or belongs to someone else. The index used to ask
# for the `$OPEN_FLEET_ROOT` substitution by hand, which is a step a protocol followed literally
# never takes: the documented command looked in the project checkout while --check stayed green
# (#322 review, P1). `runtime/scripts/` with no filename is prose about the directory, not an
# invocation, so a name character after the slash is required.
_RUNTIME_REF = r"runtime/(?:scripts/[A-Za-z0-9_][A-Za-z0-9_.-]*|[A-Za-z0-9_][A-Za-z0-9_.-]*\.json)"
RUNTIME_LINK_RE = re.compile(rf"\[([^\]]*)\]\((?:\.\./)*({_RUNTIME_REF})(#[^)]*)?\)")
RUNTIME_PATH_RE = re.compile(rf"(?<![\w/$.-])({_RUNTIME_REF})")
# The installed-root variable every vendored command names. ORCA_FLEET_ROOT is its pre-rename
# spelling; a source document that still carries it is normalised in the copy, so one bundle never
# names two roots.
ROOT_VAR = "OPEN_FLEET_ROOT"
LEGACY_ROOT_VAR_RE = re.compile(r"\bORCA_FLEET_ROOT\b")
# The template states the substitution as a manual step. The bundled copy has already had it made,
# so the instruction would send a reader hunting for invocations that are no longer there.
MANUAL_SUBSTITUTION_RE = re.compile(
    r"Replace every `runtime/scripts/<file>` invocation below with\s+"
    r"`\"\$OPEN_FLEET_ROOT/runtime/scripts/<file>\"`;\s+")
MANUAL_SUBSTITUTION_NOTE = ('Runtime invocations below already name\n'
                            '`"$OPEN_FLEET_ROOT/runtime/scripts/<file>"`; ')
# The distribution's runtime interface, independent of what survived in the input tree.
# Ship additional runtime files too, but never let discovery shrink this required floor.
REQUIRED_RUNTIME = tuple(f"runtime/scripts/{name}" for name in (
    # The shared catalog grammar: proof_status.py and quarantine_check.py (preflight's quarantine
    # gate) load it beside themselves (2026-10-23 review, P1-9 / P1-10).
    "_catalog_grammar.py",
    # Process containment: first_run.py loads it beside itself, and every paid runner's marker sweep
    # and host probe live there (PR #668 review).
    "containment.py",
    "decisions.py", "deny-hook.sh", "diff_scope.py", "dispatch-sign.py", "ed25519.py",
    "egress.py", "evidence-run.py", "floor_guard.py", "guard_text.py", "hitl-loop.template.sh",
    "inventory.py", "pm.py", "preflight.py", "proof_status.py", "quarantine_check.py",
    "run_report.py", "sandbox_doctor.py", "spawn_worker.sh", "verify-gate.sh", "verify.py",
    "wtree.sh",
)) + ("runtime/one-way-doors.json", "runtime/pins.json")
# build-change's mandatory reporting input is outside the protocol directories.
SUPPORT_DOCS = ("docs/runs/TEMPLATE.md",)
# The bundle doubles as the installable lean plugin, so its manifests are build inputs too.
PLUGIN_MANIFESTS = (".claude-plugin/plugin.json", "hooks/hooks.json")


def missing_inputs(protocols):
    """Check declared requirements before discovered files can define the inventory."""
    problems = [f"missing required source: {name}"
                for name in (*REQUIRED_RUNTIME, *SUPPORT_DOCS, *PLUGIN_MANIFESTS)
                if not (ROOT / name).is_file()]
    for path in [*SKILLS_DIR.glob("*/SKILL.md"), *(ROOT / "playbooks").glob("*.md"),
                 *(ROOT / "runtime").glob("*.md")]:
        text = path.read_text(encoding="utf-8")  # never the locale's codec (2026-10-23 review)
        for name in sorted(validate.explicit_protocol_refs(text) - protocols):
            problems.append(f"{path.relative_to(ROOT)}: missing required protocol: {name}.md")
    return problems


def protocol_docs(text, protocols):
    """Resolve the protocol closure, including calls inside other protocols.

    Playbooks call each other with bare backticks outside Composes/rides clauses.
    Include conditional calls too: they may become mandatory later in a run. The closure is the
    catalog grammar's (runtime/scripts/_catalog_grammar.py), the same one the quarantine gates
    read, so what a bundle vendors and what quarantine checks are one set (2026-10-23 review,
    P2-11) — DEFERRED READS named bare ("compound-learn at VERDICT") included.
    """
    def resolve(name):
        if name not in protocols:
            return None
        for base in (ROOT / "playbooks", ROOT / "runtime"):
            doc = base / f"{name}.md"
            if doc.is_file():
                return doc
        return None

    return _grammar.protocol_closure(text, resolve, lambda doc: doc.read_text(encoding="utf-8"))


def root_docs(text):
    """{filename: source path} for every repo-root doc the SKILL.md links."""
    found = {}
    for match in OUTBOUND_LINK_RE.finditer(text):
        target = match.group(1)
        source = (ROOT / target).resolve()
        try:
            source.relative_to(ROOT)
        except ValueError:
            continue
        if source.is_file():
            found[Path(target).name] = source
    return found


def rewrite(text, mission, protocols):
    """SKILL.md with outbound links pointed at references/, plus one pointer line.

    The index itself goes in `references/README.md`, not here: the mission body is
    budget-capped (ARCHITECTURE.md "Instruction budget"), and a bundle that blew
    that cap to explain itself would be its own kind of dishonest.
    """
    def local(match):
        anchor = match.group(2) or ""
        return f"]({REFERENCES}/{Path(match.group(1)).name}{anchor})"

    out = OUTBOUND_LINK_RE.sub(local, text)
    if protocol_docs(text, protocols):
        out = out.rstrip("\n") + (
            f"\n\nBundled copy of `{mission}`: every protocol named above is vendored in "
            f"[`{REFERENCES}/`]({REFERENCES}/README.md), not two directories up.\n"
        )
    return out


def shipped_runtime(mission_dir):
    """Runtime payload paths, mission-relative, spelled as a protocol would spell them."""
    runtime = mission_dir / "runtime"
    if not runtime.is_dir():
        return set()
    return {path.relative_to(mission_dir).as_posix()
            for path in runtime.rglob("*") if path.is_file()}


def absolutize_runtime(text, shipped):
    """Point a document's runtime invocations at the installed copy.

    Rewrite only paths this bundle actually ships. An unshipped one is a reference to the
    repository, and pointing it inside the installed mission would be a claim the reader
    cannot check. A markdown link is replaced whole: `](runtime/scripts/verify.py)` resolves
    to nothing beside the copy, and a backticked absolute path is what the reader runs.
    """
    def installed(path):
        return f'"$OPEN_FLEET_ROOT/{path}"'

    def link(match):
        return f"`{installed(match.group(2))}`" if match.group(2) in shipped else match.group(0)

    def bare(match):
        return installed(match.group(1)) if match.group(1) in shipped else match.group(0)

    text = LEGACY_ROOT_VAR_RE.sub(ROOT_VAR, text)
    text = MANUAL_SUBSTITUTION_RE.sub(MANUAL_SUBSTITUTION_NOTE, text)
    return RUNTIME_PATH_RE.sub(bare, RUNTIME_LINK_RE.sub(link, text))


def unbound_runtime(mission_dir, shipped):
    """Invocations still naming a shipped runtime file by its repository path.

    The inventory check passes on a bundle whose documented commands all reach for the project
    checkout, so the paths need a check of their own or they rot back silently.
    """
    problems = []
    for path in sorted(mission_dir.rglob("*.md")):
        where = path.relative_to(mission_dir).as_posix()
        for match in RUNTIME_PATH_RE.finditer(path.read_text(encoding="utf-8")):
            if match.group(1) in shipped:
                problems.append(f"{mission_dir.name}: runtime path is not installed-relative "
                                f"({where}): {match.group(1)}")
    return problems


def reference_index(mission, names):
    """The `references/README.md` a bundled mission ships next to its copies."""
    rows = "\n".join(f"- `{name}` → [{name}.md]({name}.md)" for name in names)
    return (
        f"# `{mission}` bundled references\n\n"
        f"Generated by `scripts/bundle.py`. In the repository these live in `playbooks/` and\n"
        f"`runtime/`, two directories above the mission. An installer that copies skill\n"
        f"directories out of the tree severs that path, so the copies live here instead —\n"
        f"resolve bare protocol names throughout the mission and its protocols against this list.\n\n"
        "## Installed runtime\n\n"
        "Set `OPEN_FLEET_ROOT` to the absolute installed mission directory (the directory\n"
        "containing SKILL.md). Run commands from the PROJECT repository being worked on;\n"
        "keep manifests, contracts and other project paths relative to that repository.\n"
        "These protocols already name their runtime as\n"
        '`"$OPEN_FLEET_ROOT/runtime/scripts/<file>"`, so export that variable and run the\n'
        "commands as written; no path is left to substitute by hand. Runtime JSON lives under\n"
        '`"$OPEN_FLEET_ROOT/runtime/"`; helpers locate it relative to themselves.\n'
        "Read the mandatory `docs/runs/TEMPLATE.md` from\n"
        '`"$OPEN_FLEET_ROOT/docs/runs/TEMPLATE.md"` ([run-report template](../docs/runs/TEMPLATE.md));\n'
        "write the filled report and its evidence into the PROJECT repository.\n"
        "Follow its target-project gates and integrity inventory procedure. The separate\n"
        "catalog proof-promotion section applies only in an open-fleet catalog clone;\n"
        "recording an external run does not promote the installed mission's proof tier.\n"
        "Python 3, a POSIX shell and git are host prerequisites; live operations also\n"
        "require the external tools and permissions named by their protocols (Orca, gh, etc.).\n\n"
        "```sh\n"
        'python3 "$OPEN_FLEET_ROOT/runtime/scripts/verify.py" --help\n'
        'python3 "$OPEN_FLEET_ROOT/runtime/scripts/evidence-run.py" --help\n'
        'python3 "$OPEN_FLEET_ROOT/runtime/scripts/preflight.py" --help\n'
        "```\n\n"
        "[Payload inventory](bundle-files.json) lists every required installed file.\n\n"
        f"{rows}\n"
    )


def runtime_files():
    """Ship the runtime as one unit so lazy imports and shell helpers stay local."""
    return [path for path in sorted((ROOT / "runtime").rglob("*"))
            if path.is_file() and path.suffix in {".py", ".sh", ".json"}
            and "__pycache__" not in path.parts]


def plugin_files():
    """Root files that make the bundle tree itself an installable lean plugin.

    The bundle doubles as the plugin distribution (announcement gate 3): pointing the
    marketplace at this tree ships skills/ + hooks + the gate runtime without the source
    repo's receipt trees. The hook commands resolve under the plugin root, so a root
    runtime/ must ride along — the same runtime_files() set the missions vendor."""
    files = [ROOT / ".claude-plugin" / "plugin.json", ROOT / "hooks" / "hooks.json"]
    files.extend(runtime_files())
    return files


# --out ownership (2026-10-23 review, P2-21 / #623). build() used to rmtree <out>/.claude-plugin,
# hooks, runtime and skills whenever they were not the source's own tree, so `--out ~/.claude`
# deleted the user's own skills/ (where the README's symlink install puts missions), hooks/ and
# runtime/ with exit 0 and no prompt. A build now records every file it writes in MARKER at the
# root of --out; a rebuild deletes only files that marker lists, and never a directory tree.
# Anything else where the build would write — a file the marker does not list, a symlink, a
# symlinked parent — is a collision, and the build refuses before deleting or writing anything.
MARKER = ".open-fleet-bundle.json"
# The marker's pre-rename name: read when MARKER is absent and replaced by MARKER on the next
# build, so a tree an earlier build wrote keeps rebuilding (PR #633 review, P2).
LEGACY_MARKER = ".orca-fleet-bundle.json"


class BundleRefused(Exception):
    """--out holds content this script did not write; nothing was deleted or written."""


def _entries_under(path):
    """Every non-directory entry at or under `path`; symlinks are entries, never followed."""
    if not os.path.lexists(path):
        return []
    if path.is_symlink() or not path.is_dir():
        return [path]
    found = []
    for dirpath, dirnames, filenames in os.walk(path):
        found += [Path(dirpath) / name for name in filenames]
        found += [Path(dirpath) / name for name in dirnames if (Path(dirpath) / name).is_symlink()]
    return found


def _owned(out):
    """The out-relative files a previous build recorded (empty when there is no marker)."""
    marker = out / MARKER
    if not os.path.lexists(marker):
        marker = out / LEGACY_MARKER
    if not os.path.lexists(marker):
        return set()
    try:
        files = json.loads(marker.read_text(encoding="utf-8")).get("files")
    except (OSError, UnicodeDecodeError, ValueError, AttributeError) as err:
        raise BundleRefused(f"{marker}: unreadable ownership marker ({err}) — refusing to guess "
                            "what a previous build wrote") from err
    if not isinstance(files, list) or not all(
            isinstance(f, str) and f and not Path(f).is_absolute() and ".." not in Path(f).parts
            for f in files):
        raise BundleRefused(f"{marker}: malformed ownership marker — refusing to guess what a "
                            "previous build wrote")
    return set(files)


def _claim(out, planned):
    """Delete what a previous build wrote, or refuse: `planned` are the out-relative paths this
    build writes (files, or mission directories written whole)."""
    if out.exists() and not out.is_dir():
        raise BundleRefused(f"--out {out} is not a directory")
    owned = _owned(out)
    foreign = []
    # Parents are checked for every path this build DELETES as well as every path it writes: a
    # retired mission stays in the marker after leaving `planned`, and a symlink swapped in for
    # its directory would aim the unlink below at another checkout's files (PR #631 review, P1).
    for rel in sorted(set(planned) | owned):
        parts = Path(rel).parts
        parents = [out.joinpath(*parts[:i]) for i in range(1, len(parts))]
        foreign += [p for p in parents if p.is_symlink() or (p.exists() and not p.is_dir())]
    for rel in planned:
        foreign += [entry for entry in _entries_under(out / rel)
                    if entry.relative_to(out).as_posix() not in owned or entry.is_symlink()]
    if foreign:
        shown = ", ".join(sorted({p.relative_to(out).as_posix() for p in foreign})[:5])
        raise BundleRefused(
            f"--out {out}: {len(set(foreign))} path(s) where the bundle writes or deletes were not "
            f"written by bundle.py (not listed in {MARKER}, or behind a symlink): {shown} — move "
            "them away or choose an empty --out; bundle.py never deletes what it did not write")
    for rel in sorted(owned):
        path = out / rel
        if path.is_symlink() or path.is_file():
            path.unlink()
        for parent in path.parents:
            if parent == out or not parent.is_relative_to(out):
                break
            try:
                parent.rmdir()  # only once empty: a directory is never removed with content
            except OSError:
                break


def _record(out, planned):
    files = sorted(entry.relative_to(out).as_posix()
                   for rel in planned for entry in _entries_under(out / rel))
    (out / MARKER).write_text(json.dumps({"generator": "scripts/bundle.py", "files": files},
                                         indent=2) + "\n", encoding="utf-8")
    if os.path.lexists(out / LEGACY_MARKER):
        (out / LEGACY_MARKER).unlink()  # migrated: MARKER now lists everything this build owns


def build(out_dir):
    """Write the distribution tree. Returns (missions built, unresolved refs).

    Raises BundleRefused, having deleted and written nothing, when --out holds content a
    previous build did not write (MARKER).
    """
    protocols = validate.known_protocol_names()
    problems = missing_inputs(protocols)
    if problems:
        return 0, problems
    out = Path(out_dir)
    missions = [d for d in sorted(SKILLS_DIR.iterdir())
                if d.is_dir() and not d.name.startswith((".", "_")) and (d / "SKILL.md").is_file()]
    planned = sorted({source.relative_to(ROOT).as_posix() for source in plugin_files()}
                     | {f"skills/{d.name}" for d in missions})
    _claim(out, planned)
    out.mkdir(parents=True, exist_ok=True)
    try:
        return _build_into(out, missions, protocols)
    finally:
        _record(out, planned)  # even a failed build owns exactly what it wrote


def _build_into(out, missions, protocols):
    for source in plugin_files():
        destination = out / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    skills_out = out / "skills"
    built, problems = 0, []
    for skill_dir in missions:
        skill_md = skill_dir / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        target = skills_out / skill_dir.name
        (target / REFERENCES).mkdir(parents=True, exist_ok=True)
        inventory = {"SKILL.md"}
        for extra in skill_dir.iterdir():
            if extra.name == "SKILL.md":
                continue
            inventory.update(path.relative_to(skill_dir).as_posix()
                             for path in (extra.rglob("*") if extra.is_dir() else [extra])
                             if path.is_file())
            if extra.is_dir():
                shutil.copytree(extra, target / extra.name, dirs_exist_ok=True)
            else:
                shutil.copy2(extra, target / extra.name)
        docs = protocol_docs(text, protocols)
        for name, source in docs.items():
            inventory.add(f"{REFERENCES}/{name}.md")
            shutil.copy2(source, target / REFERENCES / f"{name}.md")
        if docs:
            inventory.add(f"{REFERENCES}/README.md")
            (target / REFERENCES / "README.md").write_text(
                reference_index(skill_dir.name, sorted(docs)), encoding="utf-8"
            )
        for name, source in root_docs(text).items():
            inventory.add(f"{REFERENCES}/{name}")
            shutil.copy2(source, target / REFERENCES / name)
        for source in [*runtime_files(), *(ROOT / name for name in SUPPORT_DOCS)]:
            inventory.add(source.relative_to(ROOT).as_posix())
            destination = target / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        shipped = shipped_runtime(target)   # after the runtime copy: only what really shipped
        (target / "SKILL.md").write_text(
            absolutize_runtime(rewrite(text, skill_dir.name, protocols), shipped), encoding="utf-8")
        # Record intended copies, not what survived copying: a dropped helper must fail --check.
        (target / REFERENCES / "bundle-files.json").write_text(
            json.dumps(sorted(inventory), indent=2) + "\n", encoding="utf-8")
        relink_vendored(target)   # after every copy: it needs to know what ended up beside it
        problems.extend(dangling(target))
        problems.extend(unbound_runtime(target, shipped))
        built += 1
    return built, problems


def relink_vendored(mission_dir):
    """Re-point a vendored doc's repo-root-relative links, or de-link them (PR #308 review, P1).

    The copies under `references/` are verbatim, so they still say `](runtime/evidence-manifest.md)`
    — a path that was right in the repository and resolves to nothing beside the copy. Where the
    same document was vendored too, the link becomes its bare name; where it was not, the link
    becomes plain text naming the repository path, because a dead link is worse than a sentence
    telling the reader where to look."""
    refs = mission_dir / REFERENCES
    if not refs.is_dir():
        return
    available = {path.name for path in refs.glob("*.md")}
    shipped = shipped_runtime(mission_dir)
    for path in [*sorted(refs.glob("*.md")), *(mission_dir / name for name in SUPPORT_DOCS
                                             if (mission_dir / name).is_file())]:
        text = path.read_text(encoding="utf-8")

        def fix(match, _dir=path.parent):
            label, target, anchor = match.group(1), match.group(2), match.group(3) or ""
            if (_dir / target).exists():
                return match.group(0)
            name = Path(target).name
            if _dir == refs and name in available:
                return f"[{label}]({name}{anchor})"
            if _dir != refs:
                target = (_dir / target).relative_to(mission_dir).as_posix()
            if label.strip().strip("`") in (target, name):
                return f"`{target}`"   # the label WAS the path; saying it twice helps nobody
            return f"{label} (`{target}` in the open-fleet repository)"

        # Runtime paths first: a `](runtime/scripts/verify.py)` left to `fix` would be de-linked
        # as living in the repository, when the bundle ships it right there beside the mission.
        rewritten = RELATIVE_LINK_RE.sub(fix, absolutize_runtime(text, shipped))
        if rewritten != text:
            path.write_text(rewritten, encoding="utf-8")


def dangling(mission_dir):
    """Links in a bundled mission that still leave its directory, or point at nothing.

    Check every markdown file, not just SKILL.md (#316), after relinking. An upward link
    within the installed mission is valid (the reporting template is outside references/);
    a missing target or escape is not. Check all extensions, including runtime scripts."""
    problems = []
    inventory = mission_dir / REFERENCES / "bundle-files.json"
    if inventory.exists():
        try:
            files = json.loads(inventory.read_text(encoding="utf-8"))
            if not isinstance(files, list) or not all(isinstance(p, str) for p in files):
                raise ValueError("expected a list of payload paths")
            for relative in files:
                path = (mission_dir / relative).resolve()
                if not path.is_relative_to(mission_dir.resolve()) or not path.is_file():
                    problems.append(f"{mission_dir.name}: missing bundle payload: {relative}")
        except (OSError, ValueError) as error:
            problems.append(f"{mission_dir.name}: invalid payload inventory: {error}")
    for path in sorted(mission_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        where = path.relative_to(mission_dir).as_posix()
        for match in OUTBOUND_ANY_RE.finditer(text):
            target = match.group(0)[2:-1].split("#", 1)[0]
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(mission_dir.resolve()) or not resolved.is_file():
                problems.append(f"{mission_dir.name}: link escapes the bundle or is missing "
                                f"({where}): {match.group(0)}")
        for match in re.finditer(rf"\]\({REFERENCES}/([A-Za-z0-9_.-]+\.md)(?:#[^)]*)?\)", text):
            if not (mission_dir / REFERENCES / match.group(1)).is_file():
                problems.append(f"{mission_dir.name}: {REFERENCES}/{match.group(1)} was not vendored")
        for match in RELATIVE_LINK_RE.finditer(text):
            if not (path.parent / match.group(2)).exists():
                problems.append(f"{mission_dir.name}: dead relative link "
                                f"({where}): {match.group(0)}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bundle.py",
        description="Vendor each mission's referenced docs so copy installers keep working.",
        epilog="exit 0 built · 1 unresolved reference · 2 could-not-run",
    )
    parser.add_argument("--out", default=str(ROOT / "dist"), help="output directory (default dist/)")
    parser.add_argument("--check", action="store_true",
                        help="build into a temp dir and verify, writing nothing durable")
    args = parser.parse_args(argv)

    if not SKILLS_DIR.is_dir():
        print(f"skills/ not found at {SKILLS_DIR}", file=sys.stderr)
        return 2

    if not args.check:
        # build() once rmtree'd <out>/skills before rebuilding; `--out .` resolved that to the
        # real catalog and deleted all 21 missions it was asked to copy (#350). It now removes only
        # what its own marker lists, but writing over the source catalog stays refused.
        if (Path(args.out) / "skills").resolve() == SKILLS_DIR.resolve():
            print(f"--out {args.out}: its skills/ IS the source catalog; refusing to delete what "
                  "this script copies from", file=sys.stderr)
            return 2

    try:
        if args.check:
            with tempfile.TemporaryDirectory() as tmp:
                built, problems = build(tmp)
        else:
            built, problems = build(args.out)
    except BundleRefused as refusal:
        print(f"bundle: {refusal}", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    where = "a temp dir" if args.check else args.out
    print(f"bundle: {built} self-contained mission(s) in {where}; no reference leaves its directory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
