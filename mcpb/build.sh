#!/bin/sh
# SPDX-License-Identifier: LGPL-2.1-or-later
# Build Agent Link for OrcaSlicer as a Claude Desktop extension (.mcpb): this
# manifest, the launcher, and the server's files (FILES, less tests and this
# folder) as the copy that serves when GitHub cannot be reached.
# Usage: mcpb/build.sh [OUT]
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
OUT=${1:-$HERE/orcaslicer-agentlink.mcpb}
STAGE=$(mktemp -d)
cp "$HERE/manifest.json" "$HERE/icon.png" "$STAGE/"
mkdir -p "$STAGE/server" "$STAGE/app"
cp "$HERE/server/index.js" "$STAGE/server/"
grep -v -E '^(tests|mcpb)/|^#|^$' "$ROOT/FILES" | while read -r f; do
  mkdir -p "$STAGE/app/$(dirname "$f")"
  cp "$ROOT/$f" "$STAGE/app/$f"
done
git -C "$ROOT" rev-parse --short HEAD > "$STAGE/app/VERSION" 2>/dev/null || true
rm -f "$OUT"
(cd "$STAGE" && zip -qr "$OUT" .)
rm -rf "$STAGE"
echo "$OUT"
