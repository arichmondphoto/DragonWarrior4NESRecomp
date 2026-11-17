#!/usr/bin/env bash
# Undo tools/apply_patches.sh: every file the patches touch goes back to the
# submodule's pinned commit and files they add are removed, so the submodules
# are pristine before a commit (never commit changes inside them).
set -euo pipefail
cd "$(dirname "$0")/.."
for dir in patches/*/; do
    sub="$(basename "$dir")"
    [ -d "$sub" ] || continue
    patches=("$dir"*.patch)
    [ -e "${patches[0]}" ] || continue
    files=$(grep -h '^diff --git a/' "${patches[@]}" | sed 's#^diff --git a/\([^ ]*\) b/.*#\1#' | sort -u)
    tracked=""
    for f in $files; do
        if git -C "$sub" cat-file -e "HEAD:$f" 2>/dev/null; then tracked="$tracked $f"
        else rm -f "$sub/$f"; fi
    done
    # shellcheck disable=SC2086
    [ -z "$tracked" ] || git -C "$sub" checkout -q HEAD -- $tracked
done
