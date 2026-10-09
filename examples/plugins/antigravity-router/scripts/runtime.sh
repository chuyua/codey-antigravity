#!/usr/bin/env bash
# Shared helpers for the portable POSIX (macOS/Linux) launcher scripts.

runtime_read_record() {
  local record="$1"
  python3 - "$record" <<'PY'
import json, sys
record = json.load(open(sys.argv[1], encoding="utf-8"))
if (type(record.get('pid')) is not int or record['pid'] <= 0
    or type(record.get('port')) is not int or not 1 <= record['port'] <= 65535
    or any(not isinstance(record.get(key), str) or not record[key]
           or any(c in record[key] for c in '\r\n')
           for key in ('exePath', 'authPath', 'startTimeUtc'))):
    raise SystemExit('Invalid process record')
print(record["pid"])
print(record["exePath"])
print(record["authPath"])
print(record["port"])
print(record["startTimeUtc"])
PY
}

# Prints the five record fields on separate lines, or returns 1 when stale/foreign.
runtime_recorded_proxy() {
  local record="$1"
  [ -f "$record" ] || return 1
  local fields
  fields="$(runtime_read_record "$record" 2>/dev/null)" || return 1
  local pid exe auth port started
  pid="$(sed -n 1p <<<"$fields")"
  exe="$(sed -n 2p <<<"$fields")"
  auth="$(sed -n 3p <<<"$fields")"
  port="$(sed -n 4p <<<"$fields")"
  started="$(sed -n 5p <<<"$fields")"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  local actual_exe actual_start
  actual_exe="$(runtime_process_exe "$pid")" || return 1
  actual_start="$(runtime_process_start "$pid")" || return 1
  [ "$actual_exe" = "$exe" ] || { echo "Recorded PID now belongs to another process; refusing operation" >&2; return 2; }
  [ "$actual_start" = "$started" ] || { echo "Recorded PID was reused by another process; refusing operation" >&2; return 2; }
  printf '%s\n%s\n%s\n%s\n%s\n' "$pid" "$exe" "$auth" "$port" "$started"
}

runtime_process_exe() {
  local pid="$1"
  if [ -r "/proc/$pid/exe" ]; then
    readlink -f "/proc/$pid/exe"
    return
  fi
  # macOS exposes the full executable path through libproc. `ps comm` can
  # truncate paths, and comparing only a basename cannot detect a foreign PID.
  python3 - "$pid" <<'PY'
import ctypes, sys
libproc = ctypes.CDLL('/usr/lib/libproc.dylib')
libproc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
libproc.proc_pidpath.restype = ctypes.c_int
buffer = ctypes.create_string_buffer(4096)
if libproc.proc_pidpath(int(sys.argv[1]), buffer, len(buffer)) <= 0:
    raise SystemExit(1)
print(buffer.value.decode('utf-8'))
PY
}

runtime_process_start() {
  local pid="$1"
  if [ -r "/proc/$pid/stat" ]; then
    python3 - "$pid" <<'PY'
import pathlib, sys
stat = pathlib.Path(f'/proc/{int(sys.argv[1])}/stat').read_text()
# comm is parenthesized and may contain spaces; starttime is field 22.
print(stat.rsplit(')', 1)[1].split()[19])
PY
    return
  fi
  ps -o lstart= -p "$pid" 2>/dev/null | awk '{$1=$1};1'
}

runtime_port_owner() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    local owners status=0
    owners="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)" || status=$?
    [ "$status" -le 1 ] || return 3
    printf '%s\n' "$owners" | head -n1
    return
  fi
  echo "Cannot inspect TCP port owners: install lsof" >&2
  return 3
}

runtime_assert_identity() {
  local port="$1" expected_pid="$2"
  local owner
  owner="$(runtime_port_owner "$port")" || return 3
  [ -n "$owner" ] || { echo "No listener owns port $port" >&2; return 1; }
  [ "$owner" = "$expected_pid" ] || { echo "Port $port is owned by PID $owner, not $expected_pid" >&2; return 1; }
  local health
  health="$(curl -fsS --max-time 3 "http://127.0.0.1:$port/health")" || { echo "Health request failed" >&2; return 1; }
  python3 - "$health" <<'PY' || return 1
import json, sys
payload = json.loads(sys.argv[1])
raise SystemExit(0 if payload.get("ok") and payload.get("service") == "codey-antigravity-proxy" else 1)
PY
}
