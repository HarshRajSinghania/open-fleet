#!/bin/bash
# Runs inside a fresh ubuntu:24.04 container. Root installs OS packages; user fr does everything else.
set -u
t0=$(date +%s); ts() { echo "[$(date -u +%FT%TZ) +$(( $(date +%s) - t0 ))s] $*"; }
ts "host: $(uname -srm); image: $(. /etc/os-release; echo $PRETTY_NAME)"
ts "step 1: prerequisites as root (apt: git curl ca-certificates python3 tmux)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null && apt-get install -y -qq git curl ca-certificates python3 tmux >/dev/null || { ts "FAILED prerequisites"; exit 10; }
ts "  git $(git --version | cut -d' ' -f3), python $(python3 --version | cut -d' ' -f2), tmux $(tmux -V | cut -d' ' -f2)"
useradd -m -s /bin/bash fr && chown fr /out
su fr -c "CLAUDE_CODE_OAUTH_TOKEN='$CLAUDE_CODE_OAUTH_TOKEN' ANTHROPIC_MODEL='$ANTHROPIC_MODEL' REF='$REF' T0='$t0' bash /in/user.sh"
ts "done (rc=$?)"
