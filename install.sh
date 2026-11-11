#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFIX="${1:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
TARGET="$BIN_DIR/csl"

mkdir -p "$BIN_DIR"
ln -sfn "$SCRIPT_DIR/csl" "$TARGET"

VERSION=$("$TARGET" --version)
PATH_CSL=$(command -v csl || true)

cat <<EOF
Installed csl to:
  $TARGET

Installed launcher version: $VERSION
Verify your shell command:
  csl --version

Make sure this is on PATH:
  $BIN_DIR

Then initialize the index:
  csl index --prune
EOF

if [ -n "$PATH_CSL" ]; then
  if ! python3 -c 'import os,sys; sys.exit(not os.path.samefile(sys.argv[1], sys.argv[2]))' "$PATH_CSL" "$TARGET" 2>/dev/null; then
    printf '\nPATH currently resolves csl to another launcher:\n  %s\nUse the installed launcher directly or adjust PATH so this bin directory comes first:\n  %s\n' "$PATH_CSL" "$BIN_DIR"
  fi
else
  printf '\ncsl is not currently on PATH. Add the bin directory above, then run csl --version.\n'
fi
