#!/usr/bin/env bash
#
# sync-maintainer-skill.sh — keep the tina4-maintainer skill from drifting.
#
# The tina4-maintainer skill is ONE canonical file set, mastered here in
# tina4-python (`project_tina4_skills_drift`: canonical = the tina4-python copy).
# The copies in tina4-php / tina4-ruby / tina4-nodejs and the global ~/.claude
# install MUST match it byte-for-byte. Editing a single copy by hand is how the
# `send_request` example and a deleted plan path drifted for months.
#
# This script is the sanctioned way to change them. Edit tina4-python's copy, then:
#
#   scripts/sync-maintainer-skill.sh           # push canonical -> every copy
#   scripts/sync-maintainer-skill.sh --check   # verify every copy matches (exits non-zero on drift)
#
# Run --check before any release, and from any multi-repo checkout (dev box or the
# .99 lab) that has the sibling repos next to tina4-python.
#
set -euo pipefail

SKILL_REL="skills/tina4-maintainer"                 # path under each .claude dir
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANON="$SCRIPT_DIR/../.claude/${SKILL_REL}"
PARENT="$(cd "$SCRIPT_DIR/../.." && pwd)"            # the multi-repo root

[ -d "$CANON" ] || { echo "canonical skill not found: $CANON" >&2; exit 2; }

TARGETS=(
  "$PARENT/tina4-php/.claude/${SKILL_REL}"
  "$PARENT/tina4-ruby/.claude/${SKILL_REL}"
  "$PARENT/tina4-nodejs/.claude/${SKILL_REL}"
  "$HOME/.claude/${SKILL_REL}"
)

mode="${1:-sync}"
drift=0

for t in "${TARGETS[@]}"; do
  repo_root="$(cd "$(dirname "$t")/../.." 2>/dev/null && pwd || true)"
  # skip a sibling repo that is not checked out here (standalone clone / CI)
  if [ ! -d "$(dirname "$(dirname "$t")")" ]; then
    echo "skip (not present): $t"
    continue
  fi
  if [ "$mode" = "--check" ]; then
    if [ ! -d "$t" ] || ! diff -rq "$CANON" "$t" >/dev/null 2>&1; then
      echo "DRIFT: $t"
      diff -rq "$CANON" "$t" 2>&1 | sed 's/^/    /' || true
      drift=1
    else
      echo "ok:    $t"
    fi
  else
    mkdir -p "$t"
    rsync -a --delete "$CANON/" "$t/"
    echo "synced: $t"
  fi
done

if [ "$mode" = "--check" ]; then
  if [ "$drift" -eq 0 ]; then
    echo "OK: every tina4-maintainer skill copy matches canonical (tina4-python)."
  else
    echo "SKILL DRIFT — run scripts/sync-maintainer-skill.sh to reconcile from canonical." >&2
    exit 1
  fi
fi
