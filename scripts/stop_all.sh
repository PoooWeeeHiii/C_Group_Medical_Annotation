#!/usr/bin/env bash
# Stop processes started by scripts/start_all.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/.run/platform.pids"

stop_port() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
    if [[ -n "${pids}" ]]; then
      echo "[stop_all] killing listeners on :$port -> $pids"
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
      sleep 0.4
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}

if [[ -f "$PID_FILE" ]]; then
  echo "[stop_all] stopping PIDs from $PID_FILE"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    name="${line%%:*}"
    pid="${line##*:}"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "[stop_all] stop $name pid=$pid"
      kill "$pid" 2>/dev/null || true
      # also stop uvicorn --reload children
      pkill -P "$pid" 2>/dev/null || true
    fi
  done <"$PID_FILE"
  rm -f "$PID_FILE"
else
  echo "[stop_all] no pid file — falling back to ports 8000/8010/5173"
fi

# Fallback: free common ports (safe for local demo)
stop_port 8000
stop_port 8010
stop_port 5173

echo "[stop_all] done"
