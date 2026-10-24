#!/bin/sh
# #605 live hint replay: hints off / unchecked / checked, 2 scenarios x 3 arms x 3 attempts, USD 40 cap.
set -u
cd "$(mktemp -d)" || exit 2
exec env -i HOME="$HOME" LANG=en_US.UTF-8 TMPDIR="$TMPDIR" SHELL=/bin/sh \
  PATH="/Users/ravindra/.local/share/mise/installs/python/3.13/bin:$HOME/of-live/bin:/usr/bin:/bin:/usr/sbin:/sbin" OF_MODEL=claude-opus-5-5 \
  /Users/ravindra/.local/share/mise/installs/python/3.13/bin/python3 -E -s /private/tmp/claude-501/-Users-ravindra-projects-orca-fleet--claude-worktrees-orca-fleet-issue-629-9c5ddd/4ebeaa55-03f8-4eb7-b5a1-7d89e16cf6a8/scratchpad/live605/scripts/hint_replay.py --live --tier live --model claude-opus-5-5 \
  --agent-cmd "claude -p --model claude-opus-5-5 --output-format json --permission-mode acceptEdits '--allowedTools=Read,Edit,Write,MultiEdit,Glob,Grep,Bash(python3 -m unittest:*)'" \
  --budget-usd 40 --per-call-usd 2 --agent-limit-flag=--max-budget-usd \
  --max-runs 18 --attempts 3 --out "$HOME/of-live/runs/605-live/results.json"
