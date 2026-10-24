#!/usr/bin/env bash
# Apply this project's fixes to the pinned framework checkouts (idempotent).
# patches/<submodule>/*.patch are applied in name order; an already-applied
# patch is skipped. These are framework bug fixes intended for upstream.
set -euo pipefail
cd "$(dirname "$0")/.."
for dir in patches/*/; do
    sub="$(basename "$dir")"
    [ -d "$sub" ] || continue
    for p in "$dir"*.patch; do
        [ -e "$p" ] || continue
        if git -C "$sub" apply --reverse --check "$PWD/$p" 2>/dev/null; then
            echo "  already applied: $p"
        elif git -C "$sub" apply --check "$PWD/$p" 2>/dev/null; then
            git -C "$sub" apply "$PWD/$p"; echo "  applied: $p"
        else
            echo "ERROR: $p does not apply to $sub (was the submodule updated?)" >&2; exit 1
        fi
    done
done
