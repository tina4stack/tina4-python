#!/usr/bin/env bash
#
# sync-tina4-skills.sh — keep the cross-repo Tina4 AI skills from drifting.
#
# Every port repo carries THREE skill trees, and all three ship to users of the
# agent that reads them:
#
#   .claude/skills/   Claude Code
#   .agents/skills/   Codex
#   .cursor/skills/   Cursor
#
# They are gated three different ways, because they hold three different kinds of
# file:
#
#   tina4-maintainer, tina4-js   ONE canonical file set each, mastered here in
#     tina4-python. Every sibling's copy of a given tree must match this repo's
#     copy of the SAME tree, byte for byte. Note that .agents/.cursor legitimately
#     differ from .claude for tina4-maintainer — those two are short entrypoint
#     stubs, not the full skill — so they are compared tree-to-tree, never against
#     .claude.
#
#   tina4-developer-<lang>       LANGUAGE-SPECIFIC, so there is no second repo to
#     drift against — but there are two more trees inside this one. .claude is
#     canonical; .agents and .cursor must match it. This is where a Codex or
#     Cursor user gets taught an API that the Claude copy has already corrected.
#
#   encoding                     No tracked skill file may carry a UTF-8 BOM or a
#     cp1252 mojibake sequence. A BOM sits in front of the opening `---` and some
#     frontmatter parsers reject the file outright; the mojibake lands inside the
#     `description`, which is the text that decides when the skill triggers. This
#     assertion is deliberately independent of the diff gates: the corrupted copies
#     were byte-identical to each other, so every diff reported clean while the
#     corruption sat in tracked files.
#
#   scripts/sync-tina4-skills.sh                     # push canonical -> every copy
#   scripts/sync-tina4-skills.sh --check             # verify (exits non-zero on drift)
#   scripts/sync-tina4-skills.sh --check --siblings-optional
#                                                    # ...but do not fail on repos
#                                                    #    that are not checked out
#
# A sibling repo that is not on disk is REPORTED and counts toward the exit status.
# It is not silently skipped: a gate that cannot see two thirds of what it guards
# must not answer "OK". Use --siblings-optional in a single-repo checkout, and know
# that what it prints is a partial result.
#
# Run --check before any release, from a checkout that has the sibling repos beside
# it. The layout is load-bearing: PARENT is $REPO_ROOT/.., so all the repos must
# share one parent directory.
#
set -euo pipefail

SHARED=(tina4-maintainer tina4-js)           # cross-repo-identical, per tree
TREES=(.claude .agents .cursor)
SIBLINGS=(tina4-php tina4-ruby tina4-nodejs)
DEV_GLOB='tina4-developer-*'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"     # tina4-python
PARENT="$(cd "$REPO_ROOT/.." && pwd)"         # the multi-repo root

mode=sync
siblings_optional=0
for arg in "$@"; do
  case "$arg" in
    --check)             mode=--check ;;
    --siblings-optional) siblings_optional=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

drift=0
absent=0
checking() { [ "$mode" = "--check" ]; }

# --------------------------------------------------------------------- helpers

# The global install is a SUBSET of the repo copy by design: `tina4 ai` fetches
# SKILL.md and references/, and never the eval fixtures or the packaged .skill
# bundle. Comparing those two into it makes the gate permanently red, and a gate
# that can never say OK is a gate everybody learns to ignore.
GLOBAL_EXCLUDE=(-x evals -x '*.skill')

# compare_dir CANON TARGET LABEL [extra diff args...]
compare_dir() {
  local canon="$1" target="$2" label="$3"; shift 3
  if checking; then
    if [ ! -d "$target" ] || ! diff -rq "$@" "$canon" "$target" >/dev/null 2>&1; then
      echo "DRIFT [$label]: $target"
      diff -rq "$@" "$canon" "$target" 2>&1 | sed 's/^/    /' || true
      drift=1
    else
      echo "ok    [$label]: $target"
    fi
  else
    mkdir -p "$target"
    rsync -a --delete "$canon/" "$target/"
    echo "synced [$label]: $target"
  fi
}

# --------------------------------------------- 1. shared skills, tree by tree

for skill in "${SHARED[@]}"; do
  for tree in "${TREES[@]}"; do
    CANON="$REPO_ROOT/$tree/skills/$skill"
    if [ ! -d "$CANON" ]; then
      echo "canonical not found: $CANON" >&2
      exit 2
    fi
    for s in "${SIBLINGS[@]}"; do
      if [ ! -d "$PARENT/$s" ]; then
        echo "ABSENT [$skill $tree]: $PARENT/$s is not checked out — NOT compared"
        absent=1
        continue
      fi
      compare_dir "$CANON" "$PARENT/$s/$tree/skills/$skill" "$skill $tree"
    done
  done
  # the global install mirrors .claude only
  if [ -d "$HOME/.claude/skills" ]; then
    compare_dir "$REPO_ROOT/.claude/skills/$skill" "$HOME/.claude/skills/$skill" "$skill global" "${GLOBAL_EXCLUDE[@]}"
  else
    echo "ABSENT [$skill global]: $HOME/.claude/skills — NOT compared"
    absent=1
  fi
done

# ------------------------------------ 2. tina4-developer-<lang>, inside each repo

for repo in "$REPO_ROOT" "${SIBLINGS[@]/#/$PARENT/}"; do
  [ -d "$repo" ] || continue                 # already reported above
  shopt -s nullglob
  for canon in "$repo/.claude/skills/"$DEV_GLOB; do
    skill="$(basename "$canon")"
    for tree in .agents .cursor; do
      compare_dir "$canon" "$repo/$tree/skills/$skill" "$skill $tree"
    done
  done
  shopt -u nullglob
done

# ------------------------------------------------- 3. encoding assertion

# Always runs, in both modes, and is never auto-repaired: rewriting the bytes of a
# tracked file is a decision for a human and a commit, not a side effect of a sync.
BOM=$'\xef\xbb\xbf'
MOJI_A=$'\xc3\xa2\xe2\x82\xac'   # "â€" — an em/en dash or a curly quote, cp1252-round-tripped
MOJI_B=$'\xc3\x82'               # "Â"  — a non-breaking space or symbol, same round trip
bad_encoding=0

for repo in "$REPO_ROOT" "${SIBLINGS[@]/#/$PARENT/}"; do
  [ -d "$repo" ] || continue
  for tree in "${TREES[@]}"; do
    [ -d "$repo/$tree/skills" ] || continue
    while IFS= read -r -d '' f; do
      why=""
      [ "$(head -c3 "$f")" = "$BOM" ] && why="UTF-8 BOM"
      if LC_ALL=C grep -qF "$MOJI_A" "$f" || LC_ALL=C grep -qF "$MOJI_B" "$f"; then
        why="${why:+$why + }cp1252 mojibake"
      fi
      if [ -n "$why" ]; then
        echo "ENCODING [$why]: $f"
        bad_encoding=1
      fi
    done < <(find "$repo/$tree/skills" -type f \( -name '*.md' -o -name '*.txt' \) -print0)
  done
done

# ------------------------------------------- 4. dangling reference pointers

# A SKILL.md that cites references/<file> must ship that file in ITS OWN tree.
# This is deliberately separate from the diff gates for the same reason the
# encoding assertion is: when every copy of a tree is missing the same file, a
# cross-repo comparison reports all of them clean.
dangling=0
for repo in "$REPO_ROOT" "${SIBLINGS[@]/#/$PARENT/}"; do
  [ -d "$repo" ] || continue
  for tree in "${TREES[@]}"; do
    [ -d "$repo/$tree/skills" ] || continue
    while IFS= read -r -d '' skillmd; do
      dir="$(dirname "$skillmd")"
      while IFS= read -r ref; do
        [ -e "$dir/$ref" ] || { echo "DANGLING [$ref]: $skillmd"; dangling=1; }
      done < <(grep -o 'references/[A-Za-z0-9._-]*' "$skillmd" | sort -u)
    done < <(find "$repo/$tree/skills" -name SKILL.md -print0)
  done
done

# --------------------------------------------------------------------- verdict

status=0
if [ "$dangling" -eq 1 ]; then
  echo "DANGLING REFERENCES — a SKILL.md cites files its own tree does not ship." >&2
  status=1
fi

if [ "$bad_encoding" -eq 1 ]; then
  echo "ENCODING FAILURE — rewrite the files above as UTF-8 without a BOM and repair the mangled characters." >&2
  status=1
fi

if checking; then
  if [ "$drift" -eq 1 ]; then
    echo "SKILL DRIFT — run scripts/sync-tina4-skills.sh to reconcile from canonical." >&2
    status=1
  fi
  if [ "$absent" -eq 1 ]; then
    if [ "$siblings_optional" -eq 1 ]; then
      echo "NOTE: some copies were not on disk and were not compared. This is a PARTIAL result."
    else
      echo "INCOMPLETE — copies listed as ABSENT above were never compared; this run does not clear them." >&2
      status=1
    fi
  fi
  if [ "$status" -eq 0 ]; then
    echo "OK: every Tina4 skill copy matches canonical, in all three trees, and every tracked skill file is clean UTF-8."
  fi
fi

exit "$status"
