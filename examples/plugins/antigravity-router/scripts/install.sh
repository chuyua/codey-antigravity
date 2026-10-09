#!/usr/bin/env bash
# Copy a verified portable bundle into a clean destination directory.
set -euo pipefail
destination=""
while [ $# -gt 0 ]; do
  case "$1" in
    --destination) destination="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$destination" ] || { echo "A destination directory is required" >&2; exit 2; }
bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
destination="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$destination")"
case "$destination/" in
  "$bundle/"*) echo "Destination must be outside the release bundle" >&2; exit 1 ;;
esac
[ -L "$destination" ] && { echo "Destination cannot be a link" >&2; exit 1; }
if [ -e "$destination" ]; then
  [ -d "$destination" ] || { echo "Destination must be a directory" >&2; exit 1; }
  [ -z "$(ls -A "$destination")" ] || { echo "Destination must be a clean directory" >&2; exit 1; }
else
  mkdir -p "$destination"
fi
"$bundle/scripts/verify-bundle.sh" "$bundle"
for entry in "$bundle"/*; do
  cp -R "$entry" "$destination/"
done
chmod +x "$destination/bin/antigravity-proxy" "$destination/scripts/"*.sh "$destination/"*.sh
echo "Portable files installed: $destination"
echo "Next: import the .codey-plugin via the Codey Plugins UI; import stays disabled until you explicitly enable. This script does not modify Codey state."
