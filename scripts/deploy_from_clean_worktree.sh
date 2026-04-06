#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

REF="HEAD"
PASSTHROUGH_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --ref"
        exit 1
      fi
      REF="$2"
      shift 2
      ;;
    *)
      PASSTHROUGH_ARGS+=("$1")
      shift
      ;;
  esac
done

REF_SHA="$(git -C "$REPO_ROOT" rev-parse --verify "$REF")"
DIRTY_STATUS="$(git -C "$REPO_ROOT" status --short)"
TEMP_WORKTREE="$(mktemp -d "${TMPDIR:-/tmp}/xiphos-deploy-XXXXXX")"

cleanup() {
  git -C "$REPO_ROOT" worktree remove "$TEMP_WORKTREE" --force >/dev/null 2>&1 || rm -rf "$TEMP_WORKTREE"
}

trap cleanup EXIT

echo "Preparing clean deploy worktree from $REF_SHA"
if [[ -n "$DIRTY_STATUS" ]]; then
  echo "Note: current workspace has uncommitted changes. This deploy will use committed ref $REF_SHA only."
fi

git -C "$REPO_ROOT" worktree add --detach "$TEMP_WORKTREE" "$REF_SHA" >/dev/null

(
  cd "$TEMP_WORKTREE"
  ./deploy.sh "${PASSTHROUGH_ARGS[@]}"
)
