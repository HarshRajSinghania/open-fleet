#!/bin/bash
set -u
ts() { echo "[$(date -u +%FT%TZ) +$(( $(date +%s) - T0 ))s] $*"; }
cd "$HOME"
ts "step 2 (as $(id -un)): Claude Code via the official installer, pinned 2.1.304"
curl -fsSL https://claude.ai/install.sh | bash -s 2.1.304 > /tmp/install.log 2>&1 || { ts "FAILED installer"; tail -5 /tmp/install.log; exit 11; }
export PATH="$HOME/.local/bin:$PATH"; ts "  claude: $(command -v claude) $(claude --version)"
ts "step 3: fresh clone of https://github.com/ravidsrk/open-fleet at $REF"
git clone -q --branch "$REF" https://github.com/ravidsrk/open-fleet "$HOME/open-fleet" || { ts "FAILED clone"; exit 12; }
cd "$HOME/open-fleet" && ts "  catalog $(git rev-parse HEAD)"
git config --global user.email first-run@clean-host.invalid; git config --global user.name "clean host"
for prof in ro rw; do
  ts "step 4-$prof: first_run.py run --worker live --agent claude --profile $prof"
  python3 runtime/scripts/first_run.py run --worker live --agent claude --profile $prof --workdir "$HOME/fr-$prof" --keep --json > /out/receipt-$prof.json 2> /out/stderr-$prof.txt
  rc=$?; ts "  rc=$rc verdict=$(python3 -c "import json;print(json.load(open('/out/receipt-$prof.json'))['verdict'])" 2>/dev/null)"
done
