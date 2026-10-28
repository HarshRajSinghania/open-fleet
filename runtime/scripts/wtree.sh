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
# Staging runs in GIT CUSTODY (W4 custody sweep): against a git dir this script builds in a temp
# dir, whose config it writes and which defines no filter or diff driver, over the repository's
# objects (read through `objects/info/alternates`) and work tree. The blobs `add -A` writes and the
# tree `write-tree` writes land in that dir's own object store and are removed with it, so the
# repository's store is never written.
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
# Exit 1 too when the repository cannot be staged in custody: an `extensions.*` the custody git dir
# cannot honour (a partial clone above all), or a non-regular `info/exclude`, `shallow`, shared
# index or `info/sparse-checkout` where git would read one.
# Exit 3, with the reason on stderr, when a path staged differently from HEAD is selected by a
# filter driver a config DECLARES — the repository's, or a global/system file, which on a one-uid
# host the worker can write as well (#629, PR #649 review, W4-02). No filter ever runs here: the
# command is the worker's to name, and staging reads no config the worker can write, so not even
# one added while this script runs is defined there (W4 custody sweep). But without it, a smudged file's bytes cannot be mapped back to
# the committed clean blob, so for that path the comparison is genuinely unverifiable — touching
# an unchanged expanded file would otherwise fingerprint it as different from HEAD and a good run
# would read as STALE. Exit 3 says so instead of printing a misleading value. An untouched file is
# never re-hashed (the stat cache holds), so a clean checkout still fingerprints normally (Git LFS
# included). The coordinator's clean-env re-run at head_sha remains the authority for such a unit.
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
# both point it at a worker's worktree), so close the config command channels before any git
# call. Set at command-line precedence (GIT_CONFIG_COUNT), which overrides the repo's own
# .git/config: core.fsmonitor (a program git runs on `add`/`status`), core.hooksPath (every hook),
# and the ext:: transport; plus replacement objects and grafts off, so a planted refs/replace or
# .git/info/grafts cannot change the tree this fingerprints. A filter a config declares is
# blanked below and never runs (exit 3 covers what that costs). W4-02: global and system config
# are off as well, as in gitexec.py. On a one-uid host ~/.gitconfig is the worker's to write, and
# a global clean filter both ran here and CHOSE the fingerprint (it mapped a tampered file back to
# its committed blob, so verify graded a tree no test saw as FRESH). `safe.directory=*` stands in
# for the one legitimate use of the dropped global file, as gitexec's does. A global
# core.excludesFile is dropped with it, so an untracked file only it hid now counts (fails STALE).
# W4-07: the environment pointers that outrank `-C` (GIT_DIR, GIT_WORK_TREE, GIT_COMMON_DIR,
# GIT_INDEX_FILE, the object directories, GIT_ATTR_SOURCE) and the inherited config channels that
# outrank or blind this belt (GIT_CONFIG_PARAMETERS is read after the GIT_CONFIG_COUNT pairs;
# GIT_CONFIG is the one file `git config --list` reads) are the caller's, never the fingerprint's.
# And git is resolved ONCE, to an absolute path (gitexec.py's rule), not per call against PATH.
# GIT_EXEC_PATH names the directory git runs its own helper programs from, GIT_TEMPLATE_DIR what an
# init copies and GIT_NAMESPACE the refs a call sees: the caller's too, never the fingerprint's.
# GIT_NO_LAZY_FETCH=1 and GIT_ALLOW_PROTOCOL=file (gitexec.py CUSTODY_ENV): a planted promisor
# remote cannot make a read of a missing object fetch, so no `uploadpack`, credential helper or
# ssh command it names runs.
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
  GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_ATTR_SOURCE GIT_EXTERNAL_DIFF GIT_CONFIG GIT_CONFIG_PARAMETERS \
  GIT_EXEC_PATH GIT_TEMPLATE_DIR GIT_NAMESPACE
GIT_NO_LAZY_FETCH=1
GIT_ALLOW_PROTOCOL=file
export GIT_NO_LAZY_FETCH GIT_ALLOW_PROTOCOL
GIT=$(command -v git 2>/dev/null) || GIT=
case "$GIT" in
  /*) ;;
  *) echo "wtree: no git on PATH that resolves to an absolute path; no fingerprint" >&2; exit 1 ;;
esac
# The caller's own global/system view, kept for ONE read below: the driver NAMES those files
# declare, so a changed path one selects is reported unverifiable (exit 3), never staged raw.
_CALLER_GLOBAL=${GIT_CONFIG_GLOBAL-}; _CALLER_GLOBAL_SET=${GIT_CONFIG_GLOBAL+1}
_CALLER_NOSYSTEM=${GIT_CONFIG_NOSYSTEM-}; _CALLER_NOSYSTEM_SET=${GIT_CONFIG_NOSYSTEM+1}
GIT_TERMINAL_PROMPT=0
GIT_NO_REPLACE_OBJECTS=1
GIT_GRAFT_FILE=/dev/null
GIT_CONFIG_GLOBAL=/dev/null
GIT_CONFIG_NOSYSTEM=1
GIT_CONFIG_COUNT=4
GIT_CONFIG_KEY_0=core.fsmonitor;   GIT_CONFIG_VALUE_0=false
GIT_CONFIG_KEY_1=core.hooksPath;   GIT_CONFIG_VALUE_1=/dev/null
GIT_CONFIG_KEY_2=protocol.ext.allow; GIT_CONFIG_VALUE_2=never
GIT_CONFIG_KEY_3=safe.directory;   GIT_CONFIG_VALUE_3='*'
export GIT_TERMINAL_PROMPT GIT_NO_REPLACE_OBJECTS GIT_GRAFT_FILE GIT_CONFIG_COUNT
export GIT_CONFIG_GLOBAL GIT_CONFIG_NOSYSTEM
export GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0 GIT_CONFIG_KEY_1 GIT_CONFIG_VALUE_1
export GIT_CONFIG_KEY_2 GIT_CONFIG_VALUE_2 GIT_CONFIG_KEY_3 GIT_CONFIG_VALUE_3
# No git call (nor any hook or filter one runs) may read this script's stdin: an inherited pipe
# that never closes would block the fingerprint, and the gate behind it, forever (#629).
exec </dev/null

TARGET="${1:-.}"
TOP=$("$GIT" -C "$TARGET" rev-parse --show-toplevel 2>/dev/null) || exit 1

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
# The pairs are POSITIONAL `NAME=value` arguments that `env "$@" "$GIT" ...` applies to each call
# that can run a filter: env(1) splits each one at its first `=` (the variable name holds none),
# so the key's bytes reach git intact and no shell text is ever built from them and re-parsed.
# The listing alone reads the CALLER's global/system view (W4-02): every git call that stages
# content runs with those files off, so a driver they declare never runs, but its NAME is
# collected with the repository's — DECLARED keeps every blanked filter name, one per line, for
# the exit-3 check after staging, whichever scope (`--show-scope`) declared it.
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
if ! (
  if [ -n "$_CALLER_GLOBAL_SET" ]; then GIT_CONFIG_GLOBAL=$_CALLER_GLOBAL; export GIT_CONFIG_GLOBAL
  else unset GIT_CONFIG_GLOBAL; fi
  if [ -n "$_CALLER_NOSYSTEM_SET" ]; then GIT_CONFIG_NOSYSTEM=$_CALLER_NOSYSTEM; export GIT_CONFIG_NOSYSTEM
  else unset GIT_CONFIG_NOSYSTEM; fi
  exec "$GIT" -C "$TOP" config --list --show-scope -z --name-only
) >"$CFG" 2>/dev/null; then
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
  _scope=
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

# W4 custody sweep: the listing above and `add -A` below are two git calls, and `add -A` used to
# read the repository's config again — a filter a still-running worker declared in between ran
# here unblanked (and, mapping a tampered file back to its committed blob, chose the fingerprint).
# So everything that stages or hashes content runs against CUSTODY, a git dir built here (the
# shared custody of runtime/scripts/gitexec.py, custody_git_dir, spelled in sh): its own config
# (format only, no driver of any kind), HEAD at the repository's HEAD commit, the repository's
# objects as a read-only alternate, and regular-file copies of what git reads there: the common
# `info/exclude` and `shallow`, and the per-worktree `info/sparse-checkout` and split-index
# `sharedindex.*`. The work tree is the repository's own (`--work-tree "$TOP"`). The pairs listed
# above still ride as a belt; the repository's data-only core.* settings (line endings, file modes,
# name folding, stat fields, sparse flags) ride too, read here by `config --get`, so a checkout
# still fingerprints as its committed tree. `core.excludesFile` is NOT carried: honouring a file
# the worker names could hide an untracked file, so it counts (fails STALE) instead.
_gitdir=$("$GIT" -C "$TOP" rev-parse --absolute-git-dir 2>/dev/null) || exit 1
_common=$("$GIT" -C "$TOP" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 1
_format=$("$GIT" -C "$TOP" rev-parse --show-object-format 2>/dev/null) || exit 1
case "$_format" in
  sha1) _rfv=0 ;;
  sha256) _rfv=1 ;;
  *) echo "wtree: unknown object format '$_format'; no fingerprint" >&2; exit 1 ;;
esac
case "$_common" in
  /*"$NL"*|*'"'*) echo "wtree: cannot name $TOP's object store in an alternates file; no fingerprint" >&2; exit 1 ;;
  /*) ;;
  *) echo "wtree: $TOP's common git dir is not absolute; no fingerprint" >&2; exit 1 ;;
esac
# Any extensions.* the custody dir cannot reproduce is refused, never guessed (a partial clone's
# missing objects, above all). `config --get-regexp` exits 1 when there is none.
_rc=0
_ext=$("$GIT" -C "$TOP" config --name-only --get-regexp '^extensions\.' 2>/dev/null) || _rc=$?
if [ "$_rc" -ne 0 ] && [ "$_rc" -ne 1 ]; then
  echo "wtree: cannot read $TOP's extensions; no fingerprint" >&2
  exit 1
fi
OLDIFS=$IFS
IFS=$NL
set -f
for _k in $_ext; do
  case "$_k" in
    extensions.objectformat|extensions.compatobjectformat|extensions.worktreeconfig) ;;
    extensions.refstorage|extensions.relativeworktrees) ;;
    *) echo "wtree: $TOP declares $_k, which the custody git dir cannot honour; no fingerprint" >&2
       exit 1 ;;
  esac
done
set +f
IFS=$OLDIFS
for _k in filemode symlinks ignorecase precomposeunicode protecthfs protectntfs sparsecheckout \
    sparsecheckoutcone autocrlf eol checkstat trustctime; do
  _v=$("$GIT" -C "$TOP" config --get "core.$_k" 2>/dev/null) || continue
  set -- "$@" "GIT_CONFIG_KEY_$_n=core.$_k" "GIT_CONFIG_VALUE_$_n=$_v"
  _n=$((_n + 1))
done
_head=$("$GIT" -C "$TOP" rev-parse -q --verify 'HEAD^{commit}' 2>/dev/null) || _head=
set -- "$@" "GIT_CONFIG_COUNT=$_n"

CUSTODY=$(mktemp -d "${TMPDIR:-/tmp}/orca-wtree-git-XXXXXX") || exit 1
trap 'rm -rf "$CUSTODY"' EXIT INT TERM
# A regular file is copied (mtime kept); a missing one is skipped; anything else (a symlink, a
# FIFO) where git would read one is refused, never followed.
copy_regular() {
  if [ -L "$1" ]; then return 1; fi
  if [ -e "$1" ]; then
    [ -f "$1" ] || return 1
    cp -p "$1" "$2" || return 1
  fi
  return 0
}
mkdir "$CUSTODY/refs" "$CUSTODY/refs/heads" "$CUSTODY/refs/tags" "$CUSTODY/info" \
  "$CUSTODY/objects" "$CUSTODY/objects/info" || exit 1
printf '[core]\n\trepositoryformatversion = %s\n\tbare = true\n' "$_rfv" >"$CUSTODY/config" || exit 1
if [ "$_format" = sha256 ]; then
  printf '[extensions]\n\tobjectformat = sha256\n' >>"$CUSTODY/config" || exit 1
fi
if [ -n "$_head" ]; then
  printf '%s\n' "$_head" >"$CUSTODY/HEAD" || exit 1
else
  printf 'ref: refs/heads/open-fleet-unborn\n' >"$CUSTODY/HEAD" || exit 1
fi
printf '%s/objects\n' "$_common" >"$CUSTODY/objects/info/alternates" || exit 1
for _pair in "info/exclude:$_common" "shallow:$_common" "info/sparse-checkout:$_gitdir"; do
  _rel=${_pair%%:*}
  if ! copy_regular "${_pair#*:}/$_rel" "$CUSTODY/$_rel"; then
    echo "wtree: ${_pair#*:}/$_rel is not a regular file; no fingerprint" >&2
    exit 1
  fi
done
for _f in "$_gitdir"/sharedindex.*; do
  [ -e "$_f" ] || [ -L "$_f" ] || continue
  if ! copy_regular "$_f" "$CUSTODY/${_f##*/}"; then
    echo "wtree: $_f is not a regular file; no fingerprint" >&2
    exit 1
  fi
done

# Resolve the REAL index path BEFORE exporting GIT_INDEX_FILE: with the variable set,
# `rev-parse --git-path index` returns the temp index itself and the stat-cache seed self-copies.
REAL_INDEX=$("$GIT" -C "$TOP" rev-parse --git-path index 2>/dev/null || true)
case "$REAL_INDEX" in
  ""|/*) ;;
  *) REAL_INDEX="$TOP/$REAL_INDEX" ;;
esac

TMPIDX=$(mktemp "${TMPDIR:-/tmp}/orca-wtree-XXXXXX") || exit 1
trap 'rm -f "$TMPIDX"; rm -rf "$CUSTODY"' EXIT INT TERM
GIT_INDEX_FILE="$TMPIDX"
export GIT_INDEX_FILE

seed_from_head() {
  rm -f "$TMPIDX" 2>/dev/null || true
  "$GIT" -C "$TOP" --git-dir="$CUSTODY" --work-tree="$TOP" read-tree HEAD 2>/dev/null || return 1
}

if [ -n "$REAL_INDEX" ] && [ -f "$REAL_INDEX" ] && cp "$REAL_INDEX" "$TMPIDX" 2>/dev/null; then
  if ! touch -r "$REAL_INDEX" "$TMPIDX" 2>/dev/null; then
    seed_from_head || exit 1
  fi
else
  seed_from_head || exit 1
fi

env "$@" "$GIT" -C "$TOP" --git-dir="$CUSTODY" --work-tree="$TOP" add -A 2>/dev/null || exit 1
# write-tree too: a racily-clean index entry (its mtime equals the temp index's, which `touch -r`
# above makes likely) is re-hashed here, which would re-run a clean filter — so it runs in custody
# with the blanks (#629), as `add -A` does.
TREE=$(env "$@" "$GIT" -C "$TOP" --git-dir="$CUSTODY" --work-tree="$TOP" write-tree 2>/dev/null) || exit 1

# Exit 3 (see the header): a path staged differently from HEAD that a declared driver filters.
# `diff-index --cached` compares the temp index to HEAD's tree (in custody, where the blobs it
# staged live) and `check-attr` reads the repository's attributes (in the repository, against its
# real index: the temp one may name a shared index only the custody dir holds); neither runs any
# command. A driver declared only after the listing is not in DECLARED: it never ran, so its path
# was hashed from its raw bytes and the fingerprint states that content, as for any changed file.
# check-attr -z prints `path NUL filter NUL value NUL`: NUL and newline
# are swapped so each field is one line (a newline inside a path becomes a NUL that `read` drops,
# which keeps every third line the value). A value is never a path, and holds no whitespace.
if [ -n "$DECLARED" ]; then
  HEAD_TREE=$("$GIT" -C "$TOP" rev-parse -q --verify 'HEAD^{tree}' 2>/dev/null) \
    || HEAD_TREE=$("$GIT" -C "$TOP" hash-object -t tree /dev/null)
  HIT=$(env "$@" "$GIT" -C "$TOP" --git-dir="$CUSTODY" --work-tree="$TOP" diff-index --cached \
          --no-ext-diff -z --name-only --no-renames --diff-filter=AMT "$HEAD_TREE" -- 2>/dev/null \
        | GIT_INDEX_FILE=${REAL_INDEX:-$TMPIDX} "$GIT" -C "$TOP" check-attr --stdin -z filter 2>/dev/null \
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
    printf 'wtree: %s: filtered by declared driver %s and staged differently from HEAD; its content cannot be compared to the committed tree without running repository-supplied commands, so no fingerprint (#629)\n' \
      "${HIT#*"$TAB"}" "${HIT%%"$TAB"*}" >&2
    exit 3
  fi
fi
printf '%s\n' "$TREE"
