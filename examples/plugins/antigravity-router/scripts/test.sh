#!/usr/bin/env bash
# Native ABI tests, proxy unit tests and the mock proxy E2E on POSIX hosts.
set -euo pipefail
cargo_bin="${CARGO:-cargo}"
node_bin="${NODE:-node}"
example="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="$(cd "$example/../../.." && pwd)"

"$cargo_bin" build --manifest-path "$example/Cargo.toml" -p codey-plugin-antigravity-router \
  --locked --target-dir "$repo/target"
"$cargo_bin" test --manifest-path "$example/Cargo.toml" -p codey-plugin-antigravity-router \
  --locked --target-dir "$repo/target"
ANTIGRAVITY_NO_SEARCH_TOOL=0 "$cargo_bin" test --manifest-path "$example/proxy-rust/Cargo.toml" --locked
"$cargo_bin" build --manifest-path "$example/proxy-rust/Cargo.toml" --release --locked
"$node_bin" "$example/tests/e2e-rust-proxy.test.mjs"
