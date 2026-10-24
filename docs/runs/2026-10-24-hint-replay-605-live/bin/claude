#!/Users/ravindra/.local/share/mise/installs/python/3.13/bin/python3 -I
"""Isolated claude for open-fleet live experiment arms (#596 #602 #604 #605 #606).

Execs a pinned claude binary with an allow-listed environment, an empty HOME and config dir, no
user-level settings, plugins, skills, hooks or MCP servers, and the owner's subscription token from
~/of-live/oauth-token (never printed). Project and local settings stay on: posix builders rely on the
deny hook written to <worktree>/.claude/settings.local.json. Exec keeps the caller's process group.
"""
import os, sys, tempfile
REAL = "/Users/ravindra/.local/share/claude/versions/2.1.304"   # pinned; not the auto-updated symlink
LIVE = os.path.expanduser("~ravindra/of-live")
PASS = ("USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "TERM", "ANTHROPIC_MODEL")
PREFIXES = ("OPEN_FLEET_", "ORCA_", "ABLATION_", "HINT_REPLAY_", "WIP_", "TRAJECTORY_", "FIRST_RUN_")
env = {k: v for k, v in os.environ.items() if k in PASS or k.startswith(PREFIXES)}
iso = os.environ.get("OF_ISO_HOME") or tempfile.mkdtemp(prefix="of-iso-", dir=os.path.join(LIVE, "homes"))
os.makedirs(os.path.join(iso, ".claude"), exist_ok=True)
env.update(HOME=iso, ZDOTDIR=iso, CLAUDE_CONFIG_DIR=os.path.join(iso, ".claude"), SHELL="/bin/sh",
           PATH=os.environ.get("OF_PATH", "/Users/ravindra/.local/share/mise/installs/python/3.13/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
           DISABLE_AUTOUPDATER="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
           CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=os.environ.get("OF_ENV_SCRUB", "1"),
           GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
for k in ("OF_ISO_HOME", "OF_MODEL", "OF_MAX_BUDGET_USD"):
    if os.environ.get(k):
        env[k] = os.environ[k]
argv = sys.argv[1:]
if argv[:1] in (["--version"], ["-v"]):
    os.execve(REAL, [REAL] + argv, env)
with open(os.path.join(LIVE, "oauth-token")) as f:
    env["CLAUDE_CODE_OAUTH_TOKEN"] = f.read().strip()
pre = []
def add(flag, *val):
    if flag not in argv:
        pre.extend((flag, *val))
add("--setting-sources", "project,local")
add("--strict-mcp-config")
add("--disable-slash-commands")
add("--no-session-persistence")
model = os.environ.get("ANTHROPIC_MODEL") or os.environ.get("OF_MODEL")
if model:
    add("--model", model)
if os.environ.get("OF_MAX_BUDGET_USD"):
    add("--max-budget-usd", os.environ["OF_MAX_BUDGET_USD"])
os.execve(REAL, [REAL] + pre + argv, env)
