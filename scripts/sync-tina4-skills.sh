#!/usr/bin/env bash
#
# sync-tina4-skills.sh — keep the cross-repo Tina4 AI skills from drifting.
#
# tina4-maintainer and tina4-js are ONE canonical file set each, mastered here in
# tina4-python (`project_tina4_skills_drift`: canonical = the tina4-python copy).
# Their copies in tina4-php / tina4-ruby / tina4-nodejs and the global ~/.claude
# install MUST match canonical byte-for-byte. Editing a single copy by hand is how
# the `api.send_request` example and a whole "Staying current" section drifted for
# months.
#
#   scripts/sync-tina4-skills.sh           # push canonical -> every copy
#   scripts/sync-tina4-skills.sh --check   # verify every copy matches (exits non-zero on drift)
#
# NOT gated here, on purpose:
#   * tina4-developer-<lang> is LANGUAGE-SPECIFIC — each repo owns its own copy and
#     there is no second repo to drift against; the global install legitimately lags
#     by release design (install-skills.sh pins a tag).
#   * The tina4-js REPO's own copy is a soft mirror on its own release cadence; sync
#     it from canonical when that repo is not mid-release. It is not gated here.
#
# Run --check before any release, and from any multi-repo checkout (a dev box or the
# .99 lab) that has the sibling repos next to tina4-python. Missing siblings / a
# missing global install are skipped, not flagged.
#
set -euo pipefail

SKILLS=(tina4-maintainer tina4-js)           # the cross-repo-identical skills
SIBLINGS=(tina4-php tina4-ruby tina4-nodejs)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"     # tina4-python
PARENT="$(cd "$REPO_ROOT/.." && pwd)"         # the multi-repo root

mode="${1:-sync}"
drift=0

for skill in "${SKILLS[@]}"; do
  CANON="$REPO_ROOT/.claude/skills/$skill"
  [ -d "$CANON" ] || { echo "canonical not found: $CANON" >&2; exit 2; }

  targets=()
  for s in "${SIBLINGS[@]}"; do
    [ -d "$PARENT/$s/.claude/skills" ] && targets+=("$PARENT/$s/.claude/skills/$skill")
  done
  [ -d "$HOME/.claude/skills" ] && targets+=("$HOME/.claude/skills/$skill")

  for t in "${targets[@]}"; do
    if [ "$mode" = "--check" ]; then
      if [ ! -d "$t" ] || ! diff -rq "$CANON" "$t" >/dev/null 2>&1; then
        echo "DRIFT [$skill]: $t"
        diff -rq "$CANON" "$t" 2>&1 | sed 's/^/    /' || true
        drift=1
      else
        echo "ok    [$skill]: $t"
      fi
    else
      mkdir -p "$t"
      rsync -a --delete "$CANON/" "$t/"
      echo "synced [$skill]: $t"
    fi
  done
done

if [ "$mode" = "--check" ]; then
  if [ "$drift" -eq 0 ]; then
    echo "OK: every cross-repo Tina4 skill copy matches canonical (tina4-python)."
  else
    echo "SKILL DRIFT — run scripts/sync-tina4-skills.sh to reconcile from canonical." >&2
    exit 1
  fi
fi
