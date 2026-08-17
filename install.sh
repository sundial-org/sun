#!/bin/sh
# Install sun: curl -fsSL <raw-url>/install.sh | sh   (or run from a checkout)
set -e
dest="${SUN_BIN:-$HOME/.local/bin}"
mkdir -p "$dest"
src="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/sun.py"
[ -f "$src" ] || { curl -fsSL "${SUN_URL:?set SUN_URL to a raw sun.py url}" -o "$dest/sun"; src=""; }
[ -n "$src" ] && cp "$src" "$dest/sun"
chmod +x "$dest/sun"
echo "sun installed to $dest/sun — run 'sun init' inside your repo (agent hooks are installed by init)"
