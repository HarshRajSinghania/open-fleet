"""The `danger` lane's verdict reader (#283).

sandbox-policy.md: a recipe doctor is CLEAR only with no `fail` AND no `warn`; `ok:true` alone
proves nothing. spawn_worker.sh enforced that with a substring grep over a caller-named file,
which was wrong in both directions — `/etc/passwd` passed, `"failures": []` was refused. These
tests pin both directions so neither mistake can come back.
"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "sandbox_doctor", ROOT / "runtime" / "scripts" / "sandbox_doctor.py")
sandbox_doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sandbox_doctor)


class ClearTranscripts(unittest.TestCase):
    def assert_clear(self, raw, recipe="lane-7"):
        clear, reason = sandbox_doctor.verdict(raw, recipe)
        self.assertTrue(clear, f"refused a clear transcript: {reason}")

    def test_empty_json_finding_lists_are_clear(self):
        # The exact shape the old grep refused: the word "fail" inside the key that reports none.
        self.assert_clear('{"recipe": "lane-7", "ok": true, "failures": [], "warnings": []}')

    def test_zero_counts_are_clear(self):
        self.assert_clear('{"recipe": "lane-7", "ok": true, "failures": 0, "warnings": 0}')

    def test_text_form_zero_and_no_are_clear(self):
        self.assert_clear("recipe lane-7 provisioned\n0 warnings, no failures\n")
        self.assert_clear("recipe lane-7 ok:true\nfailures: none\nwarnings: none\n")

    def test_passing_checks_are_clear(self):
        self.assert_clear('{"recipe": "lane-7", "checks": [{"name": "net", "status": "pass"}]}')


class RefusedTranscripts(unittest.TestCase):
    def assert_refused(self, raw, recipe="lane-7", because=None):
        clear, reason = sandbox_doctor.verdict(raw, recipe)
        self.assertFalse(clear, f"accepted a transcript that is not clear: {raw[:80]!r}")
        if because:
            self.assertIn(because, reason)

    def test_a_verdictless_quiet_file_reads_as_clear_by_design(self):
        # THE #283 bug, in one line: ORCA_SANDBOX_RECIPE=root, ORCA_SANDBOX_DOCTOR=/etc/passwd.
        # The passwd file names "root" and carries neither "fail" nor "warn", so the old grep
        # read it as a clean sandbox. spawn_worker.sh no longer accepts a caller-named file at
        # all; this asserts the reader alone would not call such a thing a doctor verdict either.
        # (Named "refused" while asserting acceptance until #381 — a failure here would have
        # printed a name claiming the opposite of what broke.)
        passwd = "root:x:0:0:root:/root:/bin/bash\ndaemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
        clear, _reason = sandbox_doctor.verdict(passwd, "root")
        self.assertTrue(clear, "guard the honest limit: text with no verdict words reads as clear")
        # ...which is exactly why the caller-named-file lane was removed rather than patched: the
        # reader cannot tell a doctor transcript from any other quiet file. Only running the
        # doctor can, and spawn_worker.sh does that now.

    def test_a_transcript_for_another_recipe_is_refused(self):
        self.assert_refused('{"recipe": "other-lane", "ok": true}', because="does not name recipe")
        self.assert_refused("recipe other-lane ok:true\n", because="does not name recipe")

    def test_a_warning_is_refused(self):
        self.assert_refused('{"recipe": "lane-7", "ok": true, "warnings": ["low disk"]}')
        self.assert_refused("recipe lane-7 ok:true\nwarn: disk nearly full\n")

    def test_a_failure_is_refused(self):
        self.assert_refused('{"recipe": "lane-7", "failures": ["no network"]}')
        self.assert_refused("recipe lane-7\nfail: no network\n")

    def test_a_failing_check_inside_a_list_is_refused(self):
        self.assert_refused(
            '{"recipe": "lane-7", "ok": true, "checks": [{"name": "net", "status": "fail"}]}')

    def test_ok_false_is_refused(self):
        self.assert_refused('{"recipe": "lane-7", "ok": false}')

    def test_ok_true_with_a_warn_check_is_refused(self):
        # sandbox-policy.md is explicit that ok:true alone proves nothing — a warn is a lane that
        # boots and then fails a build halfway through.
        self.assert_refused(
            '{"recipe": "lane-7", "ok": true, "checks": [{"name": "disk", "level": "warn"}]}')


class RecipeIdentityIsExact(unittest.TestCase):
    """#298: the recipe check was a SUBSTRING test, in both the JSON and the plain-text path.

    A transcript for `web-prod-privileged` therefore certified a danger lane asked about `web`,
    and about `prod`. Since #283 this script produces the transcript itself, so the check is a
    sanity check rather than a trust boundary — but a sanity check that passes on the wrong
    recipe is not one, and the doctor may report on a recipe it resolved differently.
    """

    CLEAN = {"recipe": "web-prod-privileged", "failures": [], "warnings": []}

    def test_a_prefix_of_the_recipe_id_does_not_match(self):
        raw = json.dumps(self.CLEAN)
        for wrong in ("web", "web-prod", "prod", "privileged"):
            with self.subTest(recipe=wrong):
                clear, reason = sandbox_doctor.verdict(raw, wrong)
                self.assertFalse(clear, f"{wrong!r} certified a transcript for another recipe")
                self.assertIn("does not name recipe", reason)

    def test_the_whole_recipe_id_still_matches(self):
        clear, reason = sandbox_doctor.verdict(json.dumps(self.CLEAN), "web-prod-privileged")
        self.assertTrue(clear, reason)

    def test_the_match_is_a_string_value_not_a_serialized_fragment(self):
        # The id has to appear as a VALUE somewhere in the document, at any depth — not merely
        # as bytes inside the serialized form of it.
        deep = {"run": {"config": [{"id": "sandbox.v2"}]}, "failures": [], "warnings": []}
        self.assertTrue(sandbox_doctor.verdict(json.dumps(deep), "sandbox.v2")[0])
        glued = {"note": "recipes: sandbox.v2-old,sandbox.v2x", "failures": []}
        self.assertFalse(sandbox_doctor.verdict(json.dumps(glued), "sandbox.v2")[0],
                         "a substring of a longer value is not this recipe")

    def test_plain_text_matches_on_a_token_boundary(self):
        raw = "doctor for recipe web-prod-privileged\n0 failures\n0 warnings\n"
        self.assertTrue(sandbox_doctor.verdict(raw, "web-prod-privileged")[0])
        for wrong in ("web", "prod", "privileged"):
            with self.subTest(recipe=wrong):
                self.assertFalse(sandbox_doctor.verdict(raw, wrong)[0])

    def test_the_recipe_check_runs_before_the_findings_check(self):
        # A transcript for the WRONG recipe is refused whether or not it is clean, so a clean
        # transcript for a permissive recipe can never certify a stricter one.
        dirty = json.dumps({"recipe": "other-recipe", "failures": ["boom"]})
        clear, reason = sandbox_doctor.verdict(dirty, "web")
        self.assertFalse(clear)
        self.assertIn("does not name recipe", reason)


HOME = os.path.realpath(os.path.expanduser("~"))
WT = os.path.join(HOME, ".open-fleet", "state", "repo", "worktrees", "unit")


def posix_docker_doc():
    """The shape PosixWorktreeProvider.vm_recipe_doctor prints for its docker backend."""
    return {
        "recipeId": "lane-7", "backend": "docker", "ok": True, "ephemeral": True,
        "credential_mounts": [], "prelaunch_placement_bound": True,
        "checks": [{"id": "docker-cli", "status": "pass"}, {"id": "image-present", "status": "pass"},
                   {"id": "isolation-flags", "status": "pass"}],
        "isolation": {"capDrop": ["ALL"], "noNewPrivileges": True, "pidsLimit": 512,
                      "privileged": False, "network": "bridge", "user": "1000:1000"},
        "mounts": [{"source": WT, "target": WT, "mode": "rw"},
                   {"source": "/opt/open-fleet/runtime", "target": "/opt/open-fleet/runtime", "mode": "ro"},
                   {"source": "/tmp/lane/sandbox.git", "target": "/open-fleet/sandbox.git", "mode": "rw"},
                   {"source": WT + "/.git", "target": WT + "/.git", "mode": "ro"}],
        "failures": [], "warnings": [],
    }


BASE = {"recipe": "lane-7", "ok": True, "ephemeral": True, "credential_mounts": [],
        "prelaunch_placement_bound": True, "failures": [], "warnings": []}
GOOD = {
    "docker": dict(BASE, backend="docker", isolation={"capDrop": ["ALL"], "noNewPrivileges": True,
                                                     "pidsLimit": 256}),
    "devcontainer": dict(BASE, backend="devcontainer", cap_drop=["ALL"], no_new_privileges=True,
                         pids_limit=256),
    "hermes-docker": dict(BASE, backend="hermes-docker", isolation={"capDrop": ["all"],
                                                                   "noNewPrivileges": True,
                                                                   "pidsLimit": 64}),
    "bwrap": dict(BASE, backend="bwrap", networkScope="deny", filesystemScope="workspace"),
    "gondolin": dict(BASE, backend="gondolin", mounts=[{"source": WT, "target": "/workspace"}]),
    "superset-cloud": dict(BASE, backend="superset-cloud"),
    "openhands-docker": dict(BASE, backend="openhands-docker"),
    "apptainer": dict(BASE, backend="apptainer"),
}


class RecipeIdentityComesFromRecipeFields(unittest.TestCase):
    """W4-10 (2026-10-27 audit): names_recipe pushed every dict KEY onto its search stack and
    matched any string VALUE anywhere, so `{"web": {…}}` or `{"image": "web"}` named recipe
    `web` — and a transcript declaring `recipe: other` certified `web` through one of them. The
    id now comes from recipe fields (recipe / recipeId / recipe_id / a `recipe` object's id) and
    those are authoritative; only a report with no recipe field falls back to `id`/`name`."""

    def clear(self, doc, recipe="web"):
        return sandbox_doctor.verdict(json.dumps(doc), recipe)

    def test_a_dict_key_never_names_the_recipe(self):
        for doc in ({"web": {"ok": True}, "failures": []},
                    {"recipe": "other", "web": {"ok": True}, "failures": []},
                    {"checks": {"web": "pass"}, "failures": []}):
            with self.subTest(doc=doc):
                clear, reason = self.clear(doc)
                self.assertFalse(clear, "a dict key certified the recipe")
                self.assertIn("does not name recipe", reason)

    def test_a_value_outside_a_recipe_field_never_names_it(self):
        for doc in ({"image": "web", "failures": []},
                    {"recipe": "other", "note": "web", "failures": []},
                    {"recipe": "other", "checks": [{"id": "web", "status": "pass"}]}):
            with self.subTest(doc=doc):
                self.assertFalse(self.clear(doc)[0])

    def test_a_report_declaring_another_recipe_too_is_not_this_one(self):
        self.assertFalse(self.clear({"recipe": "web", "fallback": {"recipeId": "other"},
                                     "failures": []})[0])

    def test_every_recipe_field_spelling_names_it(self):
        for doc in ({"recipe": "web"}, {"recipeId": "WEB"}, {"recipe_id": "web"},
                    {"recipe": {"id": "web", "name": "The web lane"}},
                    {"result": {"recipe": {"name": "web"}}}):
            with self.subTest(doc=doc):
                clear, reason = self.clear(dict(doc, failures=[]))
                self.assertTrue(clear, reason)

    def test_a_malformed_recipe_field_refuses_and_never_falls_back(self):
        # Codex review of W4-10 (P2): `"recipe": null` was silently dropped, so the report counted
        # as having NO recipe field and the `id`/`name` fallback certified `web` from a check id.
        # A recipe field that is present but not a declaration is a refusal, never a fallback.
        for bad in (None, "", "   ", 7, True, [], [None], ["web", 3], {}, {"id": None},
                    {"ref": "web"}, {"id": ""}):
            for key in ("recipe", "recipeId", "recipe_id"):
                with self.subTest(key=key, bad=bad):
                    doc = {key: bad, "checks": [{"id": "web", "status": "pass"}],
                           "name": "web", "failures": []}
                    clear, reason = self.clear(doc)
                    self.assertFalse(clear, f"{key}={bad!r} fell back to an unrelated identity")
                    self.assertIn("malformed recipe field", reason)
        # A malformed field beside a valid one still refuses: the report contradicts itself.
        clear, reason = self.clear({"recipe": "web", "recipe_id": None, "failures": []})
        self.assertFalse(clear)
        self.assertIn("malformed recipe field", reason)
        # ...and a list of whole ids is a declaration, held to the same every-field rule.
        self.assertTrue(self.clear({"recipe": ["web"], "failures": []})[0])
        self.assertFalse(self.clear({"recipe": ["web", "other"], "failures": []})[0])

    def test_a_portable_transcript_must_declare_its_recipe_in_a_recipe_field(self):
        # A placement claim that does not say WHICH recipe it binds certifies none.
        doc = {k: v for k, v in GOOD["docker"].items() if k != "recipe"}
        doc["checks"] = [{"id": "lane-7", "status": "pass"}]
        clear, reason, _ = sandbox_doctor.assess(json.dumps(doc), "lane-7")
        self.assertFalse(clear)
        self.assertIn("does not name recipe", reason)


class SelfAssertedClaimsMustNotContradictThemselves(unittest.TestCase):
    """W4-10: `ephemeral` and `prelaunch_placement_bound` are the transcript's own claims, read at
    the top level only; one that says false anywhere else in the same report is not a proof."""

    def test_a_contradicting_nested_claim_is_an_isolation_finding(self):
        for key, where in (("ephemeral", "isolation"), ("prelaunch_placement_bound", "isolation")):
            with self.subTest(key=key):
                doc = copy.deepcopy(GOOD["docker"])
                doc[where][key] = False
                clear, reason, exposes = sandbox_doctor.assess(json.dumps(doc), "lane-7")
                self.assertFalse(clear)
                self.assertTrue(exposes, reason)
                self.assertIn(key, reason)
        doc = copy.deepcopy(GOOD["bwrap"])
        doc["checks"] = [{"id": "placement", "status": "pass", "prelaunch_placement_bound": False}]
        self.assertFalse(sandbox_doctor.assess(json.dumps(doc), "lane-7")[0])
        self.assertFalse(sandbox_doctor.placement_bound(json.dumps(doc)))


class TheTranscriptCannotDisagreeWithItself(unittest.TestCase):
    """W4-10 re-attack: duplicate JSON keys (the parser keeps the LAST, so `"ephemeral": false …
    "ephemeral": true` passed --require-placement), claim and recipe spellings the reader did not
    know (`Ephemeral`, `prelaunchPlacementBound`, `recipe-id`), an `{ok, result}` envelope whose
    own fields were discarded, and an id/name fallback that read a check's id."""

    def assess(self, doc_or_raw, recipe="lane-7"):
        raw = doc_or_raw if isinstance(doc_or_raw, str) else json.dumps(doc_or_raw)
        return sandbox_doctor.assess(raw, recipe)

    def test_a_repeated_key_refuses(self):
        good = json.dumps(GOOD["docker"])[:-1]
        for tail in (', "ephemeral": false, "ephemeral": true}',
                     ', "prelaunch_placement_bound": false, "prelaunch_placement_bound": true}',
                     ', "recipe": "other", "recipe": "lane-7"}'):
            with self.subTest(tail=tail):
                raw = good + tail
                clear, reason, _ = self.assess(raw)
                self.assertFalse(clear)
                self.assertIn("repeats the key", reason)
                self.assertFalse(sandbox_doctor.placement_bound(raw))
        clear, reason, _ = self.assess('{"recipe": "other", "failures": [], "recipe": "web"}', "web")
        self.assertFalse(clear, reason)

    def test_claim_spellings_are_all_read(self):
        for where, key in (("isolation", "Ephemeral"), ("isolation", "prelaunchPlacementBound"),
                           ("top", "PRELAUNCH-PLACEMENT-BOUND"), ("top", "Ephemeral")):
            with self.subTest(where=where, key=key):
                doc = copy.deepcopy(GOOD["docker"])
                (doc if where == "top" else doc["isolation"])[key] = False
                clear, reason, exposes = self.assess(doc)
                self.assertFalse(clear)
                self.assertTrue(exposes, reason)
                self.assertFalse(sandbox_doctor.placement_bound(json.dumps(doc)))

    def test_recipe_spellings_are_all_read(self):
        for key in ("recipe-id", "Recipe-ID", "recipe.id", "RecipeName"):
            with self.subTest(key=key):
                self.assertFalse(self.assess({key: "other", "name": "web", "failures": []}, "web")[0])
                self.assertTrue(self.assess({key: "web", "failures": []}, "web")[0])
        self.assertFalse(self.assess({"recipe": ["other"], "checks": [{"id": "web"}], "failures": []}, "web")[0])
        self.assertFalse(self.assess({"recipe": {"slug": "other"}, "checks": [{"id": "web"}]}, "web")[0])
        self.assertFalse(self.assess({"recipe": {"id": "other", "name": "web"}, "failures": []}, "web")[0])

    def test_the_envelope_cannot_contradict_the_report(self):
        for outer in ({"ok": False}, {"ok": True, "ephemeral": False}, {"ok": True, "error": "boom"},
                      {"ok": True, "Prelaunch_Placement_Bound": False}):
            with self.subTest(outer=outer):
                raw = json.dumps(dict(outer, result=GOOD["docker"]))
                self.assertFalse(self.assess(raw)[0])
                self.assertFalse(sandbox_doctor.placement_bound(raw))
        raw = json.dumps({"ok": True, "result": GOOD["docker"]})
        self.assertTrue(self.assess(raw)[0], "orca_cli's own envelope around a clean report stays clear")
        self.assertTrue(sandbox_doctor.placement_bound(raw))
        self.assertFalse(self.assess({"recipe": "other", "result": GOOD["docker"]})[0],
                         "a recipe the envelope declares counts too")

    def test_the_fallback_never_reads_a_check_finding_or_mount_id(self):
        for doc in ({"ok": True, "checks": [{"name": "web", "status": "pass"}], "failures": []},
                    {"ok": True, "result": {"checks": [{"name": "web", "status": "pass"}]}},
                    {"mounts": [{"id": "web"}], "failures": []},
                    {"name": "web", "run": {"id": "other"}, "failures": []}):
            with self.subTest(doc=doc):
                self.assertFalse(self.assess(doc, "web")[0])


class PortableBackends(unittest.TestCase):
    """#585: a portable sandbox must PROVE its isolation, per backend, and fail with exit 2."""

    def verdict(self, doc):
        return sandbox_doctor.assess(json.dumps(doc), "lane-7")

    def test_every_backend_passes_with_its_own_isolation_proven(self):
        for backend, doc in GOOD.items():
            with self.subTest(backend=backend):
                clear, reason, _ = self.verdict(doc)
                self.assertTrue(clear, reason)

    def test_the_posix_provider_docker_shape_passes(self):
        # Worktree, runtime and git mounts under $HOME's SUBDIRECTORIES are fine.
        clear, reason, _ = self.verdict(posix_docker_doc())
        self.assertTrue(clear, reason)

    def test_docker_family_requires_each_flag(self):
        for backend in ("docker", "devcontainer", "hermes-docker"):
            for drop, needle in (("capDrop", "capDrop"), ("cap_drop", "capDrop"),
                                 ("noNewPrivileges", "noNewPrivileges"),
                                 ("no_new_privileges", "noNewPrivileges"),
                                 ("pidsLimit", "pidsLimit"), ("pids_limit", "pidsLimit")):
                doc = copy.deepcopy(GOOD[backend])
                iso = doc.get("isolation", doc)
                if drop not in iso:
                    continue
                with self.subTest(backend=backend, missing=drop):
                    del iso[drop]
                    clear, reason, exposes = self.verdict(doc)
                    self.assertFalse(clear)
                    self.assertTrue(exposes)
                    self.assertIn(needle, reason)
        doc = posix_docker_doc()
        doc["isolation"]["capDrop"] = ["NET_RAW"]
        self.assertFalse(self.verdict(doc)[0], "dropping one cap is not --cap-drop ALL")
        doc = posix_docker_doc()
        doc["isolation"]["pidsLimit"] = 0
        self.assertFalse(self.verdict(doc)[0])

    def test_bwrap_needs_a_non_host_network_scope_and_a_workspace_fs_scope(self):
        for change in ({"networkScope": "host"}, {"networkScope": ""}, {"filesystemScope": "host"}):
            with self.subTest(change=change):
                clear, _reason, exposes = self.verdict(dict(GOOD["bwrap"], **change))
                self.assertFalse(clear)
                self.assertTrue(exposes)

    def test_gondolin_mounts_only_the_workspace(self):
        bad = dict(GOOD["gondolin"], mounts=[{"source": WT, "target": "/workspace"},
                                             {"source": "/srv/data", "target": "/data"}])
        clear, reason, _ = self.verdict(bad)
        self.assertFalse(clear)
        self.assertIn("/workspace", reason)
        self.assertFalse(self.verdict(dict(GOOD["gondolin"], mounts=[]))[0])

    def test_host_exposures_fail_on_every_backend(self):
        exposures = {
            "real home": {"mounts": [HOME + ":/home/dev"]},
            "home via tilde": {"mounts": [{"source": "~", "target": "/h"}]},
            "home ancestor": {"mounts": [{"source": os.path.dirname(HOME) or "/", "target": "/h"}]},
            "filesystem root": {"volumes": ["/:/host"]},
            "/root": {"mounts": [{"source": "/root", "target": "/root"}]},
            "/root credentials": {"mounts": ["/root/.ssh:/k"]},
            "/root credential ancestor": {"mounts": [{"source": "/root/.config", "target": "/c"}]},
            "docker socket": {"mounts": ["/var/run/docker.sock:/var/run/docker.sock"]},
            "ssh keys": {"mounts": [os.path.join(HOME, ".ssh") + ":/k:ro"]},
            "privileged": {"privileged": True},
            "host network": {"network": "host"},
        }
        for backend, good in GOOD.items():
            for label, change in exposures.items():
                with self.subTest(backend=backend, exposure=label):
                    doc = copy.deepcopy(good)
                    for key, value in change.items():
                        doc[key] = value + doc.get(key, []) if isinstance(value, list) else value
                    clear, _reason, exposes = self.verdict(doc)
                    self.assertFalse(clear)
                    self.assertTrue(exposes)

    def test_a_home_subdirectory_is_not_the_home(self):
        doc = dict(GOOD["docker"], mounts=[{"source": os.path.join(HOME, "src", "repo"), "target": "/w"}])
        self.assertTrue(self.verdict(doc)[0])

    def test_unknown_backends_fail_closed(self):
        clear, reason, exposes = self.verdict(dict(BASE, backend="chroot"))
        self.assertFalse(clear)
        self.assertTrue(exposes)
        self.assertIn("unsupported", reason)


class SocketAncestorsAndLongFormMounts(unittest.TestCase):
    """#592: a directory ABOVE a runtime socket hands the socket over; long-form `--mount`
    strings carry their host side in source=/src=; /root's subdirectories follow $HOME's rule."""

    def verdict(self, mounts):
        return sandbox_doctor.assess(json.dumps(dict(GOOD["docker"], mounts=mounts)), "lane-7")

    def test_socket_directories_and_their_ancestors_are_refused(self):
        for source in ("/var/run", "/run", "/var/run/", "/run/containerd", "/run/podman",
                       "/var/run/containerd", f"/run/user/{os.getuid()}", "/run/user/4242",
                       "/run/user/4242/podman", "/run/user"):
            for spelled in ([{"source": source, "target": "/s"}], [{"Source": source, "Destination": "/s"}],
                            [source + ":/s"]):
                with self.subTest(source=spelled):
                    clear, reason, exposes = self.verdict(spelled)
                    self.assertFalse(clear, reason)
                    self.assertTrue(exposes)

    def test_long_form_mount_strings_are_parsed_for_their_source(self):
        for spec in ("type=bind,source=/home,target=/h", "type=bind,src=/var/run,dst=/r",
                     f"--mount type=bind,source={HOME},target=/h", f"--mount=type=bind,src={HOME},target=/h",
                     "type=bind,source=/,target=/host,readonly", f"-v {HOME}:/h",
                     "type=bind,source=/root,target=/r"):
            with self.subTest(spec=spec):
                clear, reason, exposes = self.verdict([spec])
                self.assertFalse(clear, reason)
                self.assertTrue(exposes)
        clear, reason, _ = self.verdict([f"type=bind,source={WT},target=/w"])
        self.assertTrue(clear, reason)

    def test_root_subdirectories_are_fine_but_root_credentials_are_not(self):
        for source in ("/root/open-fleet/runtime", "/root/src/repo", "/root/.open-fleet/state/w"):
            with self.subTest(source=source):
                clear, reason, _ = self.verdict([{"source": source, "target": "/x", "mode": "ro"}])
                self.assertTrue(clear, reason)
        for source in ("/root", "/root/.ssh", "/root/.aws", "/root/.config", "/root/.config/gh",
                       "/root/.kube/config", "/root/.docker", "/root/.gnupg"):
            with self.subTest(source=source):
                clear, _reason, exposes = self.verdict([{"source": source, "target": "/x"}])
                self.assertFalse(clear)
                self.assertTrue(exposes)

    def test_home_credential_ancestors_are_refused_too(self):
        clear, _reason, exposes = self.verdict([{"source": os.path.join(HOME, ".config"), "target": "/c"}])
        self.assertFalse(clear)
        self.assertTrue(exposes)


class HomeRootsWhateverTheJudgesHome(unittest.TestCase):
    """2026-10-23 review, P2-15: the doctor compared a source to the JUDGING process's $HOME, so a
    macOS coordinator (HOME=/Users/x) cleared a Linux recipe bind-mounting every user's /home."""

    def verdict(self, source, home):
        # A bare path is a mount's source; anything else is a long-form mount string as written.
        mounts = [{"source": source, "target": "/x"} if source.startswith("/") else source]
        with mock.patch.dict(os.environ, {"HOME": home}):
            return sandbox_doctor.assess(json.dumps(dict(GOOD["docker"], mounts=mounts)), "lane-7")

    def test_home_roots_and_user_homes_are_refused_on_any_judge(self):
        for home in ("/Users/x", "/home/tester", "/root", "/nonexistent-judge-home"):
            for source in ("/home", "/home/", "/Users", "/var/home", "/home/alice", "/Users/bob",
                           "/var/home/carol", "/home/alice/.ssh", "/Users/bob/.config", "type=bind,source=/home,target=/h"):
                with self.subTest(home=home, source=source):
                    clear, reason, exposes = self.verdict(source, home)
                    self.assertFalse(clear, reason)
                    self.assertTrue(exposes, reason)

    def test_a_subdirectory_of_any_users_home_is_still_fine(self):
        for home in ("/Users/x", "/home/tester"):
            for source in ("/home/alice/src/repo", "/Users/bob/.open-fleet/state/w", "/var/home/carol/work"):
                with self.subTest(home=home, source=source):
                    clear, reason, _ = self.verdict(source, home)
                    self.assertTrue(clear, reason)


class ExitCodes(unittest.TestCase):
    """0 clear, 1 a fail/warn or another recipe, 2 an isolation/credential finding or usage."""

    def run_main(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "doctor.json"
            f.write_text(payload if isinstance(payload, str) else json.dumps(payload))
            r = subprocess.run([sys.executable, str(ROOT / "runtime" / "scripts" / "sandbox_doctor.py"),
                                str(f), "lane-7"], capture_output=True, text=True)
            return r.returncode, r.stderr

    def test_exit_codes(self):
        self.assertEqual(self.run_main(GOOD["docker"])[0], 0)
        self.assertEqual(self.run_main(dict(GOOD["docker"], warnings=["low disk"]))[0], 1)
        self.assertEqual(self.run_main({"recipe": "other", "ok": True})[0], 1)
        rc, err = self.run_main(dict(GOOD["docker"], mounts=["/var/run/docker.sock:/s"]))
        self.assertEqual(rc, 2)
        self.assertIn("socket", err)
        rc, _ = self.run_main(dict(GOOD["bwrap"], credential_mounts=["~/.config/gh:/gh"]))
        self.assertEqual(rc, 2)
        r = subprocess.run([sys.executable, str(ROOT / "runtime" / "scripts" / "sandbox_doctor.py")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()


class ErrorEnvelopesAreFindings(unittest.TestCase):
    """2026-10-26 review: an exit-0 `{"error": {...}}` envelope carried no `fail`/`warn`/`status`
    key, so a doctor that never ran its checks read as CLEAR; spawn_worker.sh's own envelope reader
    treats the identical shape as failure. A singular `error` is now a finding."""

    def test_a_top_level_error_envelope_is_refused(self):
        raw = json.dumps({"error": {"code": "recipe_not_found", "data": {"recipe": "lane-7"}}})
        clear, reason = sandbox_doctor.verdict(raw, "lane-7")
        self.assertFalse(clear)
        self.assertIn("error=recipe_not_found", reason)

    def test_a_result_level_error_envelope_is_refused(self):
        raw = json.dumps({"result": {"recipeId": "lane-7", "error": "runtime_unavailable"}})
        clear, reason = sandbox_doctor.verdict(raw, "lane-7")
        self.assertFalse(clear)
        self.assertIn("error=runtime_unavailable", reason)

    def test_an_empty_or_null_error_field_is_not_a_finding(self):
        for value in (None, "", [], {}):
            raw = json.dumps({"recipeId": "lane-7", "ok": True, "checks": [], "error": value})
            clear, reason = sandbox_doctor.verdict(raw, "lane-7")
            self.assertTrue(clear, f"{value!r}: {reason}")
