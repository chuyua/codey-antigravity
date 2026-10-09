#!/usr/bin/env bash
# Verify an extracted portable bundle: exact file list, SHA256 and proxy version.
set -euo pipefail
bundle="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
root="$(cd "$bundle" && pwd)"
[ -f "$root/SHA256SUMS" ] || { echo "Missing SHA256SUMS" >&2; exit 1; }

python3 - "$root" <<'PY'
import hashlib, pathlib, sys

root = pathlib.Path(sys.argv[1])
listed = set()
for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
    if not line:
        continue
    expected, _, relative = line.partition("  ")
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise SystemExit("Malformed checksum file")
    if (relative.startswith("/") or ".." in pathlib.PurePosixPath(relative).parts
            or relative in ("", "SHA256SUMS") or relative in listed):
        raise SystemExit(f"Unsafe or duplicate checksum path: {relative}")
    target = root / relative
    if not target.is_file():
        raise SystemExit(f"Missing bundle file: {relative}")
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"Checksum mismatch: {relative}")
    listed.add(relative)
for path in root.rglob("*"):
    if path.is_symlink():
        raise SystemExit(f"Links are not allowed in a release bundle: {path}")
    if path.is_file():
        relative = path.relative_to(root).as_posix()
        if relative != "SHA256SUMS" and relative not in listed:
            raise SystemExit(f"Unlisted bundle file: {relative}")
PY

version="$("$root/bin/antigravity-proxy" --version)"
[ "$version" = "antigravity-proxy 0.9.0" ] || { echo "Unexpected executable version: $version" >&2; exit 1; }
echo "Portable bundle exact file list, SHA256 and executable version verified"
