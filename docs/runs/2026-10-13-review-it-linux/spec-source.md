# Spec source for the review (retained verbatim)

Spec-source search order (acceptance-review): frozen spec -> originating issue -> task
criteria -> PR description. First hit: the originating issue below; the PR description
follows as the implementer's claim against it.

## Originating issue: stablyai/orca#28164 — [Bug]: Deleting a workspace fails when the worktree has initialized submodules

URL: https://github.com/stablyai/orca/issues/28164  Author: @knine79

### Operating system

macOS

### Orca version

1.4.224

### Details

**Short summary:**
Deleting a workspace from the UI fails for any git worktree whose submodules have been initialized:

```
fatal: working trees containing submodules cannot be moved or removed
```

Git refuses `git worktree remove <path>` for such worktrees unless `--force` is passed. Orca's delete flow appears to call it without `--force`, so the workspace can never be deleted from the UI (repeated attempts fail the same way).

**How can we reproduce it?**
1. Repo with a submodule (e.g. one entry in `.gitmodules`).
2. Create a workspace (worktree) in Orca.
3. In it, run `git submodule update --init`.
4. Delete the workspace in Orca -> fails with the error above.

Plain git repro:

```sh
git worktree add ../wt
git -C ../wt submodule update --init
git worktree remove ../wt          # exit 128
git worktree remove --force ../wt  # succeeds
```

**Note:** `git submodule deinit -f --all` alone is not enough; git also checks `.git/worktrees/<name>/modules`. Removing that directory as well unblocks the delete.

**Expected:**
Orca detects submodules (or this specific error) and retries with `--force` after its own dirty-check, or offers a "force delete" option in the UI.


## PR description: stablyai/orca#28206 — fix(worktrees): offer Force Delete when Git refuses a checkout with submodules

URL: https://github.com/stablyai/orca/pull/28206  Author: @Hotragn  Head: 6dcd957a65daf77fe49f15afbb998b262427224c

## ELI5

If a workspace's git submodules were initialized (`git submodule update --init`), deleting that workspace from Orca could fail every time with "working trees containing submodules cannot be moved or removed", with no button to get past it. Now Orca recognizes that refusal and offers Force Delete, and tells you what forcing will remove.

## What Changed

- **Before:** Git refuses `git worktree remove` without `--force` for any checkout with initialized submodules, even when nothing in it has changed. Orca deletes without `--force` when you skip the delete confirmation and from the workspace space manager (`forceOnConfirm: false`). In both cases the refusal reached `classifyWorktreeForceDeleteReason`, which didn't know it, so the toast showed Git's raw error and **no** Force Delete button. Retrying failed the same way.
- **After:**
  - `classifyWorktreeForceDeleteReason` maps that refusal to a new `'submodules'` reason. A forced attempt still returns `null`, like the other reasons.
  - The toast shows Force Delete, with this copy: "Git only removes a workspace with initialized submodules when forced. Force Delete also deletes the submodule checkouts, including commits in them that were never pushed."
  - Force Delete then runs the existing forced path (`git worktree remove --force`), which removes the checkout and its registration.

## Why

The issue suggests Orca could retry with `--force` on its own after its dirty check. I didn't do that, because `--force` also deletes the worktree's submodule git directories under `.git/worktrees/<name>/modules`. A commit made inside a submodule and recorded in the superproject leaves `git status` clean. If that commit was never pushed, an automatic force would delete it without asking. Offering Force Delete with honest copy follows how Orca already handles a dirty worktree, and leaves that choice with the user. "Always force delete" from the toast still works for people who don't want to see the question again.

Matching the message is safe across Git versions: `git worktree remove` has printed this exact text since it was added in Git 2.17, below the 2.25 baseline. If Git prints it in another language, the classifier misses it and behavior stays as it is today.

## Linked Issue

Fixes #28164

## Visual Proof

The only visual change is the delete-failure toast:
- **Before:** "Failed to delete workspace <name>", with Git's raw `fatal: working trees containing submodules cannot be moved or removed` as a destructive toast and no Force Delete button.
- **After:** the same title, the explanation quoted above, and the Force Delete button (non-destructive styling, like the dirty-files toast).

I can add screenshots if you want them; the behavior is covered against the real Git binary below.

## Testing

- [x] I manually tested these changes locally
- [x] Automated tests added/updated, or explained why not below

- I reproduced the refusal with plain git 2.56 first: a clean worktree with an initialized submodule exits 128 without `--force` and is removed with it.
- `worktree-removal-real-git.test.ts`, a new real-Git case:
  - a checkout with an initialized submodule is refused by `removeWorktree(..., false)`;
  - the error Orca surfaces classifies as `'submodules'`;
  - the checkout stays registered;
  - `removeWorktree(..., true)` then removes it and its registration.
- `removal-force-classification.test.ts`: the refusal maps to `'submodules'`, and a forced attempt does not re-offer force.
- `delete-worktree-toast.test.ts`: the refusal text, run through the real classifier, renders the new copy and offers Force Delete.
- All three fail without the change.
- The `src/shared/worktree`, delete-toast and worktree store suites pass (78 files). `pnpm typecheck`, `oxlint`/`oxfmt`, `pnpm run check:code-quality:changed` and the three `verify:localization-*` checks pass. Tested on macOS.

## AI Disclosure

I used Claude Code (Claude Opus 5.5) to trace the delete flow and the force-reason classifier and to draft the change and tests. I reproduced the Git behavior myself, chose not to auto-force because of the submodule commit loss, and reviewed every line.

## Review

My review of the change, with the agent's help:
- **Cross-platform:** a string match on Git's own message. No paths and no platform code.
- **SSH / remote:** removal runs Git on the owning host and its error text comes back to the renderer, where the classifier runs, so SSH and paired hosts get the same button.
- **Folder workspaces:** not affected, since they have no `git worktree remove`.
- **Git compatibility:** the message is unchanged since Git 2.17, and nothing new is run.
- **Performance:** one extra `includes` on a failure path.
- **UI:** reuses the existing failure toast and Force Delete button. The one new string is in `en.json`, as other recent strings were.
- **Security / data:** nothing is forced without the user's click, and the copy names exactly what forcing deletes.

## Agent skill upstream boundary

- [x] Not applicable, or this change copies or mechanically translates no upstream skill-installer source, tests, fixtures, registry entries, path tables, comments, or documentation.

## Notes

Ensure no issues in: Security, Cross-platoform support (Linux, Windows, Mac), Remote SSH, Mobile, general backwards compatibility, performance

## Checklist

- [x] This PR is small and focused
- [x] I explained what changed and why (ELI5, the user-facing before/after, the mechanism, and why over the alternatives)
- [x] Before/after screenshots or videos attached for UI changes, or `N/A` with reason
- [x] Self-reviewed for correctness, security, and performance
- [x] Cross-platform, SSH/remote, and path/shortcut impact considered (or N/A)
- [x] `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build` pass (or CI will cover; local preferred)

