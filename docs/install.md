# Installing open-fleet

[Documentation Hub](README.md) · [Getting Started](getting-started.md) · [Verify Gate](verify-gate.md) · [Troubleshooting](troubleshooting.md)

Install the `open-fleet` catalog once on your workstation, then invoke missions from inside any target project repository. Keep your `open-fleet` clone on disk — symlinked skills and completion-gate hooks resolve files directly from it.

---

## Choose an install path

| Path | Best for | Completion gate (`verify-gate.sh`) | Witness status |
|---|---|---|---|
| **[Symlink install](#symlink-the-catalog)** *(recommended)* | Evaluating `open-fleet`, selecting specific missions, or hacking on the catalog | Wire into `~/.claude/settings.json` via `sh hooks/print-settings-snippet.sh` | Verified in CI ([clean-container transcript](completion/evidence/414-clean-container-install.txt) · [symlink witness](completion/evidence/CF-02-r2-happy-symlink-install.txt)) |
| **[Claude Code plugin](#claude-code-plugin)** | Installing the entire catalog as a managed Claude Code plugin | Automatically wired via `${CLAUDE_PLUGIN_ROOT}` in `hooks/hooks.json` | Verified ([lean plugin witness](completion/evidence/CF-02c-lean-plugin-install.txt) · [plugin install](completion/evidence/CF-02b-plugin-install.txt) · [uninstall](completion/evidence/CF-02b-plugin-uninstall.txt)) |
| **[Copy installer / `dist/` bundle](#copy-installers-and-bundles)** | External copy-based skill installers that copy individual skill folders | Requires separate hook wiring and `OPEN_FLEET_ROOT` | Repo-root copy unsupported; self-contained `dist` branch published per release tag |

---

## Symlink the catalog

### 1. Whole-catalog installer

The install script validates the repository, creates symlinks in `~/.claude/skills/`, and checks that the completion-gate snippet is ready (requires `git` and Python ≥ 3.11; see [pinned runtime prerequisites](distribution.md#prerequisites-pinned)):

```bash
git clone https://github.com/ravidsrk/open-fleet.git
cd open-fleet
sh scripts/install.sh
sh scripts/install.sh --check
```

> [!WARNING]
> **Use a full clone (`git clone` without `--depth 1`).** Proven missions bind their run reports to historical commits in this repository, and `validate.py` verifies those commit hashes during installation. If you have a shallow clone, unshallow it first:
> ```bash
> git fetch --unshallow
> sh scripts/install.sh
> ```

**Installer flags and safety checks:**
- If a mission is already symlinked to a *different* `open-fleet` checkout, `install.sh` stops rather than silently repointing it. Pass `--force` to repoint existing mission symlinks to the current clone, or pass `--skills-dir=DIR` to target a custom directory.
- Real (non-symlink) directories inside `~/.claude/skills/` are never overwritten ([troubleshooting](troubleshooting.md#installation-refuses-an-existing-mission-directory)).
- If the Orca desktop app is closed or unreachable, `install.sh` prints a soft warning so headless/CI installs still succeed.

### 2. Selective symlink install

To link only specific missions by hand, always use `ln -s` (never `cp -r`). Every mission resolves its composed playbooks and runtime policies in `playbooks/` and `runtime/` two levels above its `skills/<name>/` directory:

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)/skills/ship-it"   ~/.claude/skills/ship-it
ln -s "$(pwd)/skills/review-it" ~/.claude/skills/review-it
```

### 3. Wire the completion gate

A symlink install does not load a Claude Code plugin, so `${CLAUDE_PLUGIN_ROOT}` is unset and `hooks/hooks.json` does not fire automatically. Without this step, a symlink install has **no completion gate**:

```bash
sh hooks/print-settings-snippet.sh          # Merge the printed "hooks" block into ~/.claude/settings.json
sh hooks/print-settings-snippet.sh --check  # Confirm the template and gate script exist in this clone
```

When merging the snippet into `~/.claude/settings.json`, delete the `_comment` keys if your settings reader rejects unknown keys, and ensure `runtime/scripts/verify-gate.sh` has its execute bit set (`test -x runtime/scripts/verify-gate.sh || chmod +x runtime/scripts/verify-gate.sh`). Because the registered hook executes `runtime/scripts/verify-gate.sh` directly from your local clone path, keep the clone in a user-owned directory and review `git pull` updates just as you would for local dotfiles. See [Verify the completion gate](#verify-the-completion-gate) below to test that the hook blocks unverified manifests.

---

## Claude Code plugin

The repository includes a Claude Code plugin manifest at [`.claude-plugin/plugin.json`](../.claude-plugin/plugin.json) and marketplace configuration at [`.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json).

Inside an interactive Claude Code session, run:

```text
/plugin marketplace add ravidsrk/open-fleet
/plugin install open-fleet@open-fleet
```

Or from your shell:

```bash
claude plugin marketplace add ravidsrk/open-fleet
claude plugin install open-fleet@open-fleet
claude plugin details open-fleet@open-fleet
```

**How the plugin is packaged:**
- The marketplace installs from the generated `dist` branch (force-updated on `v*` release tags alongside `DIST-PROVENANCE.txt`, which records the exact release tag and source commit), where each mission is bundled with its referenced playbooks and runtime docs under `references/` and `hooks/hooks.json` is wired automatically via `${CLAUDE_PLUGIN_ROOT}`. If your environment requires pinning an immutable git tag rather than a branch ref, use the symlink install path checked out at a signed release tag.
- After installing, verify activation in the plugin manager (`claude plugin details open-fleet@open-fleet`) and type `/` in Claude Code to see skills such as `/open-fleet:review-it`. See the upstream [Claude Code plugin documentation](https://code.claude.com/docs/en/discover-plugins) and our repeatable [plugin install witness procedure](completion/PLUGIN-INSTALL-WITNESS.md).

---

## Copy installers and bundles

Copy-based skill managers (such as the [skills CLI](https://github.com/vercel-labs/skills)) work by copying `dirname(SKILL.md)` in isolation — so installing directly via copy CLI is **not from this repository, today.** Copying `skills/<name>/` out of the source root leaves behind `playbooks/`, `runtime/`, and `ARCHITECTURE.md`, causing the mission to fail when resolving its phase protocols.

Instead, copy installers require a published `dist/` bundle where every mission directory is self-contained:

```bash
python3 scripts/bundle.py           # Generates dist/skills/<name>/ with playbooks & runtime vendored under references/
python3 scripts/bundle.py --check   # Builds and verifies a temporary bundle; does not inspect existing dist/
```

- **Automated `dist` branch:** On every `v*` release tag, `.github/workflows/publish-dist.yml` runs `python3 scripts/bundle.py` and publishes the self-contained tree to the **`dist` branch** alongside `DIST-PROVENANCE.txt` ([first published at `v0.7.0`](https://github.com/ravidsrk/open-fleet/releases/tag/v0.7.0), [workflow run](https://github.com/ravidsrk/open-fleet/actions/runs/36700658706)).
- **Safe rebuilds:** `bundle.py` tracks its generated files in `<out>/.open-fleet-bundle.json` and refuses (exit `2`) to overwrite untracked files or symlinks.

---

## Check the install

1. **In your coding agent:** Ask `"which missions are available?"` to confirm your installed missions appear.
2. **Verify symlink resolution from your shell** (uses Python's `os.path.realpath` for cross-platform macOS/Linux portability):

```bash
shipit=$(python3 -c 'import os; print(os.path.realpath(os.path.expanduser("~/.claude/skills/ship-it")))')
ls "$(dirname "$(dirname "$shipit")")/playbooks"
```

If you installed from a bundled copy, inspect `references/README.md` and `runtime/scripts/verify.py` inside the mission folder instead.

---

## Verify the completion gate

After merging the output of `sh hooks/print-settings-snippet.sh` into `~/.claude/settings.json` (or installing the plugin), test the gate from the catalog root:

```bash
ORCA_MANIFEST=/nonexistent.json sh runtime/scripts/verify-gate.sh --event stop
```

**Expected output:** `BLOCKING (fail-closed)` with exit code `2` because `/nonexistent.json` does not exist. When `ORCA_MANIFEST` is unset (normal turns with no unit in flight), the hook exits `0` silently. Full environment and trust-boundary details are in **[Verify gate](verify-gate.md)**.

---

## Update or remove an install

- **Update a whole-catalog symlink install:**
  ```bash
  git pull --ff-only
  sh scripts/install.sh
  sh scripts/install.sh --check
  ```
- **Update or remove a selective symlink install:** Run `git pull --ff-only` in the clone. To remove a single symlinked mission without touching others:
  ```bash
  unlink ~/.claude/skills/review-it
  ```
  *(Note: `sh scripts/install.sh --check` checks that the full catalog is linked; if you manage a subset by hand, verify individual links with the `os.path.realpath` snippet above.)*
- **Full uninstall:** Unlink the mission entries from `~/.claude/skills/` and remove the `verify-gate.sh` hook entries from `~/.claude/settings.json` before deleting your local clone.
- **Plugin update or uninstall:** Use `/plugin` inside Claude Code or `claude plugin` from your shell ([upstream plugin management docs](https://code.claude.com/docs/en/discover-plugins#manage-installed-plugins)).
