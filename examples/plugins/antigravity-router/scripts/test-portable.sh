#!/usr/bin/env bash
# Exercise install/start/stop/verify hardening of an extracted POSIX bundle.
set -euo pipefail
bundle="${1:-}"
[ -n "$bundle" ] || { echo "Usage: test-portable.sh <bundle directory>" >&2; exit 2; }
bundle="$(cd "$bundle" && pwd)"
temp_root="$(mktemp -d "${TMPDIR:-/tmp}/codey-portable-XXXXXX-中 space")"
installed="$temp_root/installed"
state="$temp_root/runtime"
cleanup() {
  if [ -f "$state/proxy.json" ]; then
    "$installed/stop-proxy.sh" --state-dir "$state" >/dev/null 2>&1 || true
  fi
  rm -rf "$temp_root"
}
trap cleanup EXIT

expect_failure() {
  if "$@" >/dev/null 2>&1; then
    echo "Expected refusal did not occur: $*" >&2
    exit 1
  fi
}

"$bundle/scripts/install.sh" --destination "$installed"
expect_failure "$bundle/scripts/install.sh" --destination "$installed"
expect_failure "$bundle/scripts/install.sh" --destination "$bundle/nested-install"

auth="$temp_root/auth.json"
python3 - "$auth" <<'PY'
import json, sys, time
fixture = {"antigravity": {
    "type": "oauth", "refresh": "1/mock-refresh-only", "access": "ya29.mock-access-only",
    "expires": int(time.time() * 1000) + 86_400_000,
    "accountId": "portable-test", "projectId": "mock-project",
}}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(fixture, handle)
PY

port="$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
"$installed/start-proxy.sh" --port "$port" --auth "$auth" --state-dir "$state"
first_pid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["pid"])' "$state/proxy.json")"
"$installed/start-proxy.sh" --port "$port" --auth "$auth" --state-dir "$state"
second_pid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["pid"])' "$state/proxy.json")"
[ "$first_pid" = "$second_pid" ] || { echo "Repeated start changed PID" >&2; exit 1; }
"$installed/stop-proxy.sh" --state-dir "$state"
kill -0 "$first_pid" 2>/dev/null && { echo "Proxy remained after stop" >&2; exit 1; }
"$installed/stop-proxy.sh" --state-dir "$state"

occupied_file="$temp_root/occupied-port"
python3 - "$occupied_file" <<'PY' &
import socket, sys, time
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
sock.listen(1)
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(str(sock.getsockname()[1]))
time.sleep(30)
PY
holder=$!
for _ in $(seq 1 50); do
  [ -s "$occupied_file" ] && break
  sleep 0.1
done
occupied="$(cat "$occupied_file")"
[ -n "$occupied" ] || { echo "Could not reserve an occupied port" >&2; exit 1; }
expect_failure "$installed/start-proxy.sh" --port "$occupied" --auth "$auth" --state-dir "$state"
kill "$holder" 2>/dev/null || true
wait "$holder" 2>/dev/null || true

python3 - "$state/proxy.json" "$$" <<'PY'
import json, sys
record = {"pid": int(sys.argv[2]), "exePath": "x", "authPath": "y", "startTimeUtc": "z", "port": 8787}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(record, handle)
PY
expect_failure "$installed/stop-proxy.sh" --state-dir "$state"
rm -f "$state/proxy.json"
printf 'tamper' >>"$installed/README.md"
expect_failure "$installed/scripts/verify-bundle.sh" "$installed"
echo "PASS portable: clean install / no overwrite / nested refusal / Unicode paths / idempotent start-stop / occupied port / tamper refusal"
