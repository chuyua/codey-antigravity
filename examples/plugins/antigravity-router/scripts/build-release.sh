#!/usr/bin/env bash
# Build and package the native plugin and proxy for one POSIX target.
set -euo pipefail
cargo_bin="${CARGO:-cargo}"
python_bin="${PYTHON:-python3}"
target=""
output_dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target) target="$2"; shift 2 ;;
    --output-dir) output_dir="$2"; shift 2 ;;
    --cargo) cargo_bin="$2"; shift 2 ;;
    --python) python_bin="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$target" ] || { echo "--target is required" >&2; exit 2; }
case "$(uname -s)" in
  Darwin|Linux) ;;
  *) echo "Portable POSIX builds require macOS or Linux" >&2; exit 1 ;;
esac
example="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="$(cd "$example/../../.." && pwd)"
[ -n "$output_dir" ] || output_dir="$example/dist/$target"
[ -e "$output_dir" ] && { echo "Output directory already exists; select a new directory" >&2; exit 1; }

"$cargo_bin" fmt --manifest-path "$example/Cargo.toml" -p codey-plugin-antigravity-router -- --check
"$cargo_bin" fmt --manifest-path "$example/proxy-rust/Cargo.toml" -- --check
"$cargo_bin" build --manifest-path "$example/Cargo.toml" -p codey-plugin-antigravity-router \
  --target "$target" --release --locked --target-dir "$repo/target"
"$cargo_bin" build --manifest-path "$example/proxy-rust/Cargo.toml" \
  --target "$target" --release --locked --target-dir "$example/proxy-rust/target"
"$python_bin" "$example/scripts/package-release.py" "$example" "$output_dir" \
  --cargo "$cargo_bin" --target "$target"
echo "Portable release built: $output_dir"
