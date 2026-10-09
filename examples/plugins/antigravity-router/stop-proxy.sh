#!/usr/bin/env bash
set -euo pipefail
state_dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --state-dir) state_dir="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/scripts/runtime.sh"
[ -n "$state_dir" ] || state_dir="$here/.runtime"
record="$state_dir/proxy.json"
if [ ! -f "$record" ]; then
  echo "No recorded proxy to stop"
  exit 0
fi
if fields="$(runtime_recorded_proxy "$record")"; then
  :
else
  status=$?
  if [ "$status" = 2 ]; then
    exit 1
  fi
  rm -f "$record"
  echo "Recorded process has exited; stale record cleared"
  exit 0
fi
pid="$(sed -n 1p <<<"$fields")"
port="$(sed -n 4p <<<"$fields")"
runtime_assert_identity "$port" "$pid"
kill "$pid"
for _ in $(seq 1 50); do
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.1
done
kill -0 "$pid" 2>/dev/null && { echo "Proxy did not exit" >&2; exit 1; }
rm -f "$record"
echo "Stopped verified Antigravity proxy PID=$pid"
