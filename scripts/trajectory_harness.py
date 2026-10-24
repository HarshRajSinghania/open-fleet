#!/usr/bin/env python3
"""Record a live agent run as #602 trajectory events: the agent-command prefix of the live arms.

    python3 scripts/trajectory_harness.py [--trajectory-out PATH] [--] <agent command...>

#602's live runner (`eval.py run --suite trajectories --tier live`) and #606's paired runner
(`ablation.py run --harness-cmd ...`) both put this in front of the agent command. It:

1. prepares the cell workspace (its cwd): git-inits it when it is not a repository root, gives
   the repository a local identity with signing off, and commits the materialized state as the
   base the agent starts from;
2. runs the agent in the caller's process group, never a new one: scripts/_ablation_run.py kills
   a cell's whole group on a timeout or an interrupt, and an agent that left it would outlive its
   call. stdin is inherited; stdout is passed through byte for byte (the runners read usage from
   it) and kept; stderr is inherited;
3. once the agent exits, turns the kept Claude stream-json into #602 events
   (scripts/_trajectories.py, record_stream) and writes them to $ABLATION_OUT/trajectory.jsonl,
   or to --trajectory-out when ABLATION_OUT is unset. A destination is required before the agent
   starts, and a stale recording there is removed first, so a run that records nothing leaves
   nothing to be graded;
4. exits with the agent's exit code (128+N when signal N ended it).

Git isolation. The agent's environment points GIT_CONFIG_GLOBAL and GIT_CONFIG_SYSTEM at the null
device and drops every other GIT_* variable (GIT_CONFIG_PARAMETERS and GIT_CONFIG_COUNT pairs
inject config too), so the operator's ~/.gitconfig and system config are never read. The
workspace's own config sets commit and tag signing off and names `false` as every signing
program, and GNUPGHOME is an empty directory with no SSH agent socket. A commit the agent makes
is unsigned; one it forces with -S fails rather than reach the operator's key.

Stdlib only. Writes nothing outside the workspace, its private GNUPGHOME and the recording.
"""
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAJECTORY_FILE = "trajectory.jsonl"
EXIT_USAGE = 2
# The workspace repository's own config: an identity, and no way to sign.
LOCAL_CONFIG = (("user.name", "trajectory-harness"), ("user.email", "harness@example.invalid"),
                ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                ("gpg.program", "false"), ("gpg.ssh.program", "false"),
                ("gpg.x509.program", "false"))
# Never handed to the agent: an SSH or GPG agent could sign for it.
_DROPPED = ("SSH_AUTH_SOCK", "GPG_AGENT_INFO")
BASE_MESSAGE = "base: the cell's materialized initial state (trajectory_harness.py)"


def isolated_env(environ, gnupghome):
    """The agent's environment: the caller's, with git's global and system config gone, no
    other GIT_* variable, and gpg pointed at an empty home."""
    env = {k: v for k, v in environ.items() if not k.startswith("GIT_") and k not in _DROPPED}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_TERMINAL_PROMPT="0", GNUPGHOME=str(gnupghome))
    return env


def _git(workspace, env, *args):
    result = subprocess.run(["git", "-C", str(workspace), "-c", f"core.hooksPath={os.devnull}",
                             "-c", "core.fsmonitor=false", *args], capture_output=True, text=True,
                            env=env, stdin=subprocess.DEVNULL, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def prepare_workspace(workspace, env=None):
    """git-init `workspace` when it is not a repository root, set its local identity and signing
    off, commit whatever is there as the base when it has no commit or uncommitted changes, and
    return the base commit's sha."""
    workspace = Path(workspace)
    if env is None:
        env = isolated_env(os.environ, os.devnull)
    if not (workspace / ".git").exists():
        _git(workspace, env, "init", "-q", "-b", "main")
    for key, value in LOCAL_CONFIG:
        _git(workspace, env, "config", "--local", key, value)
    has_head = subprocess.run(["git", "-C", str(workspace), "rev-parse", "--verify", "-q", "HEAD"],
                              capture_output=True, env=env, stdin=subprocess.DEVNULL).returncode == 0
    if not has_head or _git(workspace, env, "status", "--porcelain", "--untracked-files=all"):
        _git(workspace, env, "add", "-A")
        _git(workspace, env, "commit", "-q", "--allow-empty", "-m", BASE_MESSAGE)
    return _git(workspace, env, "rev-parse", "HEAD").strip()


def parse_args(argv):
    """(trajectory-out or None, agent argv). Harness options come first; `--` or the first word
    that is not one of them starts the agent command, whose own options are never read here."""
    out, i = None, 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            i += 1
            break
        if arg == "--trajectory-out" and i + 1 < len(argv):
            out, i = argv[i + 1], i + 2
        elif arg.startswith("--trajectory-out="):
            out, i = arg.split("=", 1)[1], i + 1
        else:
            break
    return out, argv[i:]


def destination(environ, flag):
    if environ.get("ABLATION_OUT"):
        return Path(environ["ABLATION_OUT"]) / TRAJECTORY_FILE
    return Path(flag) if flag else None


def _engine():
    spec = importlib.util.spec_from_file_location("_trajectories_for_harness",
                                                  ROOT / "scripts" / "_trajectories.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _forward(fd, data, open_):
    """Write all of `data` to `fd` while the reader is there; False once it has gone."""
    view = memoryview(data)
    while open_ and view:
        try:
            view = view[os.write(fd, view):]
        except BrokenPipeError:
            return False
    return open_


def write_recording(dest, events):
    tmp = Path(f"{dest}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, dest)


def main(argv=None):
    flag, agent = parse_args(sys.argv[1:] if argv is None else argv)
    if not agent:
        print("trajectory_harness: usage: trajectory_harness.py [--trajectory-out PATH] [--] "
              "<agent command...>", file=sys.stderr)
        return EXIT_USAGE
    dest = destination(os.environ, flag)
    if dest is None:
        print("trajectory_harness: refusing to start: no recording destination (set ABLATION_OUT "
              "or pass --trajectory-out)", file=sys.stderr)
        return EXIT_USAGE
    dest = dest.resolve()
    dest.unlink(missing_ok=True)  # a stale recording must never be graded as this run's
    workspace = Path.cwd()
    gnupghome = Path(tempfile.mkdtemp(prefix="of-harness-gnupg-"))
    try:
        env = isolated_env(os.environ, gnupghome)
        try:
            base = prepare_workspace(workspace, env)
        except (OSError, RuntimeError, subprocess.SubprocessError) as err:
            print(f"trajectory_harness: cannot prepare the workspace: {err}", file=sys.stderr)
            return EXIT_USAGE
        try:
            proc = subprocess.Popen(agent, stdout=subprocess.PIPE, env=env)
        except OSError as err:
            print(f"trajectory_harness: cannot start the agent: {err}", file=sys.stderr)
            return 127
        previous = {sig: signal.signal(sig, lambda signum, _frame: proc.send_signal(signum))
                    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
        kept, open_ = bytearray(), True
        try:
            while True:
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                kept += chunk
                open_ = _forward(sys.stdout.fileno(), chunk, open_)
            code = proc.wait()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        try:
            events = _engine().record_stream(bytes(kept).decode("utf-8", "replace"), workspace, base)
            write_recording(dest, events)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as err:
            print(f"trajectory_harness: no recording written: {err}", file=sys.stderr)
        return code if code >= 0 else 128 - code
    finally:
        shutil.rmtree(gnupghome, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
