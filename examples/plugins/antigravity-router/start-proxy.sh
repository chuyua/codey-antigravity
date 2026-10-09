#!/usr/bin/env bash
set -euo pipefail
port=28787
auth_path="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/auth.json"
state_dir=""
exe_path=""
while [ $# -gt 0 ]; do
  case "$1" in
    --port) port="$2"; shift 2 ;;
    --auth) auth_path="$2"; shift 2 ;;
    --state-dir) state_dir="$2"; shift 2 ;;
    --exe) exe_path="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
if ! [[ "$port" =~ ^[1-9][0-9]{0,4}$ ]] || [ "$port" -gt 65535 ]; then
  echo "--port must be an integer from 1 to 65535" >&2
  exit 2
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/scripts/runtime.sh"
[ -n "$state_dir" ] || state_dir="$here/.runtime"
[ -n "$exe_path" ] || exe_path="$here/bin/antigravity-proxy"
[ -x "$exe_path" ] || { echo "Proxy executable not found: $exe_path" >&2; exit 1; }
[ -f "$auth_path" ] || { echo "Auth file not found: $auth_path" >&2; exit 1; }
exe_path="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$exe_path")"
auth_path="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$auth_path")"
version="$("$exe_path" --version)"
[ "$version" = "antigravity-proxy 0.10.0" ] || { echo "Unexpected proxy version: $version" >&2; exit 1; }
mkdir -p "$state_dir"
state_dir="$(cd "$state_dir" && pwd)"
record="$state_dir/proxy.json"
if [ -f "$record" ]; then
  if fields="$(runtime_recorded_proxy "$record")"; then
    recorded_port="$(sed -n 4p <<<"$fields")"
    recorded_exe="$(sed -n 2p <<<"$fields")"
    recorded_auth="$(sed -n 3p <<<"$fields")"
    pid="$(sed -n 1p <<<"$fields")"
    if [ "$recorded_port" != "$port" ] || [ "$recorded_exe" != "$exe_path" ] || [ "$recorded_auth" != "$auth_path" ]; then
      echo "Existing recorded proxy has different settings" >&2
      exit 1
    fi
    runtime_assert_identity "$port" "$pid"
    echo "Already running PID=$pid port=$port"
    exit 0
  else
    status=$?
    if [ "$status" = 2 ]; then
      exit 1
    fi
    rm -f "$record"
  fi
fi
owner="$(runtime_port_owner "$port")" || exit $?
[ -z "$owner" ] || { echo "Port $port is occupied by PID $owner; nothing was stopped" >&2; exit 1; }
export PI_CODING_AGENT_DIR="$(dirname "$auth_path")"
export AG_IMAGE_DIR="$state_dir/images"
export NO_PROXY="$(python3 - <<'PY'
import os
parts = [p for p in os.environ.get("NO_PROXY", "").split(",") if p]
for item in ("127.0.0.1", "localhost", "::1"):
    if item not in parts:
        parts.append(item)
print(",".join(parts))
PY
)"
mkdir -p "$AG_IMAGE_DIR"
"$exe_path" serve --port "$port" --auth "$auth_path" >"$state_dir/proxy.out.log" 2>&1 &
pid=$!
started="$(runtime_process_start "$pid")"
ready=0
for _ in $(seq 1 50); do
  kill -0 "$pid" 2>/dev/null || { echo "Proxy exited during startup" >&2; exit 1; }
  if runtime_assert_identity "$port" "$pid"; then ready=1; break; fi
  sleep 0.2
done
if [ "$ready" != 1 ]; then
  kill "$pid" 2>/dev/null || true
  echo "Proxy health identity check timed out (check the Google login)" >&2
  exit 1
fi
python3 - "$record" "$pid" "$exe_path" "$auth_path" "$port" "$started" <<'PY'
import json, sys
path, pid, exe, auth, port, started = sys.argv[1:]
record = {"pid": int(pid), "exePath": exe, "authPath": auth, "startTimeUtc": started, "port": int(port)}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(record, handle)
PY
echo "Started verified Antigravity proxy PID=$pid port=$port"
