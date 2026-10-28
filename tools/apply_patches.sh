#!/usr/bin/env bash
# Apply this project's fixes to the pinned framework checkouts.
#
# For each patches/<submodule>/ directory, every file the patches touch is
# first restored to the submodule's pinned commit, then all patches are
# applied in name order. The result is the same whatever state an earlier
# build left behind (including a partially patched tree), and files the
# patches don't touch are left alone. These are framework bug fixes intended
# for upstream; see README.md "Framework patches".
set -euo pipefail
cd "$(dirname "$0")/.."
for dir in patches/*/; do
    sub="$(basename "$dir")"
    [ -d "$sub" ] || continue
    patches=("$dir"*.patch)
    [ -e "${patches[0]}" ] || continue
    # Files touched by any patch (paths relative to the submodule).
    files=$(grep -h '^diff --git a/' "${patches[@]}" | sed 's#^diff --git a/\([^ ]*\) b/.*#\1#' | sort -u)
    # Restore them to the pinned commit; files a patch adds are removed.
    tracked=""
    for f in $files; do
        if git -C "$sub" cat-file -e "HEAD:$f" 2>/dev/null; then tracked="$tracked $f"
        else rm -f "$sub/$f"; fi
    done
    # shellcheck disable=SC2086
    [ -z "$tracked" ] || git -C "$sub" checkout -q HEAD -- $tracked
    for p in "${patches[@]}"; do
        if ! git -C "$sub" apply --check "$PWD/$p" 2>/dev/null; then
            echo "ERROR: $p does not apply to $sub's pinned commit (was the submodule updated?)" >&2
            exit 1
        fi
        git -C "$sub" apply "$PWD/$p"
        echo "  applied: $p"
    done
done
