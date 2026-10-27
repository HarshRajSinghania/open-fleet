#!/usr/bin/env sh
# wtree.sh — print a working-tree CONTENT fingerprint (a git tree hash).
#
# Ported from gstack `bin/gstack-wtree` (MIT, garrytan/gstack v1.84.1) — the mechanism is theirs,
# the POSIX-sh spelling and the fail-closed exit are ours. See
# docs/research/2026-09-10-upstream-audit/gstack.md §4.2.
#
# Builds a TEMP index, stages the full working tree into it (`git add -A`, so .gitignore'd scratch
# stays out and UNTRACKED source is included), and prints `git write-tree` of that index. Why this
# and not `git rev-parse HEAD^{tree}`:
#
#   - committing identical content does NOT change the fingerprint, so a record made on a dirty
#     tree stays valid once that exact content is committed;
#   - an untracked new source file DOES change it, so "tests passed" cannot stay fresh after a new
#     file appears;
#   - rebase / amend / squash that preserve content do not change it.
#
# The REAL repo index is never touched. Seeding the temp index by COPYING the real one preserves the
# stat cache, so `git add -A` only re-hashes files whose stat changed. gstack's #2687 hardening is
# kept verbatim in spirit: `cp` stamps the copy "now", which defeats git's racy-index protection and
# can hide a same-second rewrite, so `touch -r` restores the original mtime — and if that touch
# FAILS we fall through to the slower `read-tree HEAD` seed rather than trusting a stale stat cache.
#
# Staged blobs land in the object store as unreachable objects and are gc'd like stash churn (so the
# CONTENT of untracked, non-ignored files enters .git/objects until gc — the same property
# `git stash -u` has).
#
# IGNORED FILES ARE OUT BY CONTRACT, and that is a stated limit, not an oversight. The consumer
# (verify.py check_commands, evidence-manifest.md) compares this value to `<head_sha>^{tree}`, a
# commit's tree, and an ignored file can never be in one: hashing ignored files in would make every
# record STALE, and would re-hash node_modules/ and build output on every run. The cost: a run whose
# outcome depended on ignored content (.env, a stale build artifact, a file hidden by a local
# .git/info/exclude or global core.excludesFile) still fingerprints as the committed tree. This
# value binds a run to COMMITTABLE content only; the coordinator's clean-env re-run at head_sha is
# what catches a pass that leaned on anything else.
#
# Usage:
#   wtree.sh [repo-dir]                            # default: the current directory
#   wtree.sh predict-merge <base> <branch> [repo]  # 3-way merge conflict prediction in memory
# Exit 1 outside a git repo, or in a repo with no commits and no usable index — callers MUST treat
# a non-zero exit as "no fingerprint" and fail closed, never as an empty one.
# Exit 3, with the reason on stderr, when a path staged differently from HEAD is selected by a
# filter driver the REPOSITORY declares (#629, PR #649 review). Such a filter is never run here: it
# is a command the worker wrote. But without it, a smudged file's bytes cannot be mapped back to
# the committed clean blob, so for that path the comparison is genuinely unverifiable — touching
# an unchanged expanded file would otherwise fingerprint it as different from HEAD and a good run
# would read as STALE. Exit 3 says so instead of printing a misleading value. An untouched file is
# never re-hashed (the stat cache holds), so a clean checkout still fingerprints normally; a filter
# declared in the coordinator's OWN global/system config is trusted and still runs. The
# coordinator's clean-env re-run at head_sha remains the authority for a unit this refuses.
set -eu

if [ "${1:-}" = "predict-merge" ]; then
  if [ $# -lt 3 ]; then
    echo "usage: wtree.sh predict-merge <base> <branch> [repo-dir]" >&2
    exit 2
  fi
  _BASE="$2"
  _BRANCH="$3"
  _REPO="${4:-.}"
  exec python3 -I "$(dirname -- "$0")/diff_scope.py" --repo "$_REPO" --predict-merge "$_BASE" "$_BRANCH"
fi
if [ "${2:-}" = "predict-merge" ]; then
  if [ $# -lt 4 ]; then
    echo "usage: wtree.sh <repo-dir> predict-merge <base> <branch>" >&2
    exit 2
  fi
  exec python3 -I "$(dirname -- "$0")/diff_scope.py" --repo "$1" --predict-merge "$3" "$4"
fi

# #629: this script runs git over a repo it does not own (evidence-run.py, verify.py predict-merge
# both point it at a worker's worktree), so close the repo-config command channels before any git
# call. Set at command-line precedence (GIT_CONFIG_COUNT), which overrides the repo's own
# .git/config: core.fsmonitor (a program git runs on `add`/`status`), core.hooksPath (every hook),
# and the ext:: transport; plus replacement objects and grafts off, so a planted refs/replace or
# .git/info/grafts cannot change the tree this fingerprints. A filter the REPOSITORY declares is
# blanked below and never runs (exit 3 covers what that costs). Global/system config is left in
# force for fidelity — it is the coordinator's own (a global core.excludesFile governs what the
# committed tree omits, and a global filter such as Git LFS still maps content to its committed
# form). The coordinator's clean-env re-run is the backstop.
GIT_TERMINAL_PROMPT=0
GIT_NO_REPLACE_OBJECTS=1
GIT_GRAFT_FILE=/dev/null
GIT_CONFIG_COUNT=3
GIT_CONFIG_KEY_0=core.fsmonitor;   GIT_CONFIG_VALUE_0=false
GIT_CONFIG_KEY_1=core.hooksPath;   GIT_CONFIG_VALUE_1=/dev/null
GIT_CONFIG_KEY_2=protocol.ext.allow; GIT_CONFIG_VALUE_2=never
export GIT_TERMINAL_PROMPT GIT_NO_REPLACE_OBJECTS GIT_GRAFT_FILE GIT_CONFIG_COUNT
export GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0 GIT_CONFIG_KEY_1 GIT_CONFIG_VALUE_1
export GIT_CONFIG_KEY_2 GIT_CONFIG_VALUE_2
# No git call (nor any hook or filter one runs) may read this script's stdin: an inherited pipe
# that never closes would block the fingerprint, and the gate behind it, forever (#629).
exec </dev/null

TARGET="${1:-.}"
TOP=$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null) || exit 1

# #629: `git add -A` below materialises worktree content, running a repo-config clean/smudge
# filter a .gitattributes selects. The command comes only from a declared filter.<n>.* key, and
# -c cannot wildcard the <n>, so read the declared names and blank each. A filter runs only for a
# file whose stat changed since the index, so a clean checkout re-stages nothing and this never
# alters the fingerprint; it bites only on a currently-dirty filtered file (uncommitted anyway).
# The names are BYTES (PR #649 review): git accepts 0xff, an invalid UTF-8 sequence, `.` or `=` in
# one, and an attribute selects that exact name. So the keys are handled under LC_ALL=C (a UTF-8
# `tr` aborts at the first invalid byte and drops every key after it), split on newline with
# globbing off, and collected as GIT_CONFIG_KEY_n/VALUE_n pairs: an env pair keeps key and value
# apart, where `-c <key>=` splits a name holding `=` at its first `=` and blanks another key.
# The pairs are POSITIONAL `NAME=value` arguments that `env "$@" git ...` applies to each call
# that can run a filter: env(1) splits each one at its first `=` (the variable name holds none),
# so the key's bytes reach git intact and no shell text is ever built from them and re-parsed.
# Only a key the REPOSITORY supplies is blanked: `--show-scope` names each key's origin, a key a
# repo config includes from elsewhere is reported in the including file's scope, and a key from
# the coordinator's own global/system file is trusted. A repo key that merely shadows a global
# driver's name still blanks that driver whole. DECLARED keeps the blanked filter names, one per
# line, for the exit-3 check after staging.
LC_ALL=C
export LC_ALL
NL='
'
TAB=$(printf '\t')
DECLARED=
# PR #649 review (PRRT_kwDOTWxN9c6vzAIE): an unreadable driver list must stop the fingerprint,
# never run with nothing blanked. `$(git ... | tr ...)` reported tr's exit status and hid git's,
# so the listing goes to a temp file and git's own status decides. git answers an empty but valid
# config with exit 0 and no output; anything else — a non-zero exit (128 for an unreadable or
# malformed config), output that is not NUL-terminated, a scope without its key — is "no
# fingerprint", exit 1 with the reason on stderr.
set --
_n=$GIT_CONFIG_COUNT
CFG=$(mktemp "${TMPDIR:-/tmp}/orca-wtree-cfg-XXXXXX") || exit 1
trap 'rm -f "$CFG"' EXIT INT TERM
if ! git -C "$TOP" config --list --show-scope -z --name-only >"$CFG" 2>/dev/null; then
  echo "wtree: cannot read $TOP's config, so its filter drivers cannot be neutralised; no fingerprint (#629)" >&2
  exit 1
fi
if [ -s "$CFG" ] && [ "$(tail -c 1 "$CFG" | od -An -tx1 | tr -d ' \n')" != 00 ]; then
  echo "wtree: $TOP's config listing is not NUL-terminated keys; no fingerprint (#629)" >&2
  exit 1
fi
BLANK_KEYS=$(tr '\0' '\n' <"$CFG")
rm -f "$CFG"
OLDIFS=$IFS
IFS=$NL
set -f
_scope=
for _k in $BLANK_KEYS; do
  if [ -z "$_scope" ]; then
    _scope=$_k
    continue
  fi
  _from=$_scope
  _scope=
  case "$_from" in system|global) continue ;; esac
  case "$_k" in
    filter.*.*)
      # A filter is neutralised WHOLE: commands blank AND required=false, since git dies on a
      # required filter that runs nothing — blanked, or with no command declared (PR #649).
      # Repeats for a name's other keys are harmless (same pairs, last one wins).
      _d=${_k#filter.}
      _d=${_d%.*}
      DECLARED="$DECLARED$_d$NL"
      for _v in clean smudge process required; do
        _val=
        [ "$_v" = required ] && _val=false
        set -- "$@" "GIT_CONFIG_KEY_$_n=filter.$_d.$_v" "GIT_CONFIG_VALUE_$_n=$_val"
        _n=$((_n + 1))
      done ;;
    diff.*.textconv|diff.*.command)
      set -- "$@" "GIT_CONFIG_KEY_$_n=$_k" "GIT_CONFIG_VALUE_$_n="
      _n=$((_n + 1)) ;;
  esac
done
set +f
IFS=$OLDIFS
if [ -n "$_scope" ]; then
  echo "wtree: $TOP's config listing has a scope without its key; no fingerprint (#629)" >&2
  exit 1
fi
set -- "$@" "GIT_CONFIG_COUNT=$_n"

# Resolve the REAL index path BEFORE exporting GIT_INDEX_FILE: with the variable set,
# `rev-parse --git-path index` returns the temp index itself and the stat-cache seed self-copies.
REAL_INDEX=$(git -C "$TOP" rev-parse --git-path index 2>/dev/null || true)
case "$REAL_INDEX" in
  ""|/*) ;;
  *) REAL_INDEX="$TOP/$REAL_INDEX" ;;
esac

TMPIDX=$(mktemp "${TMPDIR:-/tmp}/orca-wtree-XXXXXX") || exit 1
trap 'rm -f "$TMPIDX"' EXIT INT TERM
GIT_INDEX_FILE="$TMPIDX"
export GIT_INDEX_FILE

seed_from_head() {
  rm -f "$TMPIDX" 2>/dev/null || true
  git -C "$TOP" read-tree HEAD 2>/dev/null || return 1
}

if [ -n "$REAL_INDEX" ] && [ -f "$REAL_INDEX" ] && cp "$REAL_INDEX" "$TMPIDX" 2>/dev/null; then
  if ! touch -r "$REAL_INDEX" "$TMPIDX" 2>/dev/null; then
    seed_from_head || exit 1
  fi
else
  seed_from_head || exit 1
fi

env "$@" git -C "$TOP" add -A 2>/dev/null || exit 1
# write-tree too: a racily-clean index entry (its mtime equals the temp index's, which `touch -r`
# above makes likely) is re-hashed here, which re-runs the clean filter — so the blanks (#629)
# ride this call as well, not only `add -A`.
TREE=$(env "$@" git -C "$TOP" write-tree 2>/dev/null) || exit 1

# Exit 3 (see the header): a path staged differently from HEAD that a repo-declared driver filters.
# `diff-index --cached` compares the temp index to HEAD's tree and `check-attr` reads attributes;
# neither runs any command. check-attr -z prints `path NUL filter NUL value NUL`: NUL and newline
# are swapped so each field is one line (a newline inside a path becomes a NUL that `read` drops,
# which keeps every third line the value). A value is never a path, and holds no whitespace.
if [ -n "$DECLARED" ]; then
  HEAD_TREE=$(git -C "$TOP" rev-parse -q --verify 'HEAD^{tree}' 2>/dev/null) \
    || HEAD_TREE=$(git -C "$TOP" hash-object -t tree /dev/null)
  HIT=$(git -C "$TOP" diff-index --cached -z --name-only --no-renames --diff-filter=AMT \
          "$HEAD_TREE" -- 2>/dev/null \
        | git -C "$TOP" check-attr --stdin -z filter 2>/dev/null \
        | tr '\0\n' '\n\0' \
        | { _i=0; _path=
            while IFS= read -r _f; do
              # `(pattern)`: a bare `pattern)` inside $( ) trips bash 3.2's parser (macOS /bin/sh).
              case $((_i % 3)) in
                (0) _path=$_f ;;
                (2) case "$NL$DECLARED" in
                      (*"$NL$_f$NL"*) printf '%s%s%s\n' "$_f" "$TAB" "$_path"; break ;;
                    esac ;;
              esac
              _i=$((_i + 1))
            done; }) || HIT=
  if [ -n "$HIT" ]; then
    printf 'wtree: %s: filtered by repo-declared driver %s and staged differently from HEAD; its content cannot be compared to the committed tree without running repository-supplied commands, so no fingerprint (#629)\n' \
      "${HIT#*"$TAB"}" "${HIT%%"$TAB"*}" >&2
    exit 3
  fi
fi
printf '%s\n' "$TREE"
