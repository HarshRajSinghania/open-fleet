#!/bin/sh
# #596 clean-host first run in a fresh ubuntu:24.04 container. Only CLAUDE_CODE_OAUTH_TOKEN enters it (by name).
set -u
OUT="$HOME/of-live/runs/596-clean-host"; rm -rf "$OUT"; mkdir -p "$OUT"
CLAUDE_CODE_OAUTH_TOKEN=$(cat "$HOME/of-live/oauth-token") docker run --rm -e CLAUDE_CODE_OAUTH_TOKEN \
  -e ANTHROPIC_MODEL=claude-opus-5-5 -e REF="${1:-claude/r03-cert-close}" \
  -v "$HOME/of-live/clean-host:/in:ro" -v "$OUT:/out" ubuntu:24.04 bash /in/inner.sh 2>&1 | tee "$OUT/clean-host.log"
