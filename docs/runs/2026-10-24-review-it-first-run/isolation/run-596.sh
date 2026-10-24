#!/bin/sh
# #596 live first run, one profile: $1 = ro | rw. Isolated env, wrapper-first PATH, setsid backend.
set -u
prof=$1
cd "$(mktemp -d)" || exit 2
exec env -i HOME="$HOME" LANG=en_US.UTF-8 TMPDIR="$TMPDIR" SHELL=/bin/sh \
  PATH="/Users/ravindra/.local/share/mise/installs/python/3.13/bin:$HOME/of-live/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  OF_MODEL=claude-opus-5-5 OF_MAX_BUDGET_USD=1.60 OF_ENV_SCRUB=0 OPEN_FLEET_POSIX_BACKEND=setsid \
  /Users/ravindra/.local/share/mise/installs/python/3.13/bin/python3 -E -s /private/tmp/claude-501/-Users-ravindra-projects-orca-fleet--claude-worktrees-orca-fleet-issue-629-9c5ddd/4ebeaa55-03f8-4eb7-b5a1-7d89e16cf6a8/scratchpad/fr596b/runtime/scripts/first_run.py run --worker live --agent claude \
  --profile "$prof" --workdir "$HOME/of-live/runs/596-${prof}2" --keep --json
