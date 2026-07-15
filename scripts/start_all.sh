#!/usr/bin/env bash
# Start the full Label Platform stack for local demo:
#   - DeepEdit inference service  :8010  (精修；无权重时可降级)
#   - Main FastAPI + Legacy UI    :8000  (标注/3D/手势/手术/审核/导出/AI代理)
#
# Optional:
#   START_REACT=1  — also start Vite React UI on :5173
#
# Usage:
#   bash scripts/start_all.sh
#   bash scripts/start_all.sh --no-deepedit
#   START_REACT=1 bash scripts/start_all.sh
#   bash scripts/stop_all.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RUN_DIR="$ROOT/.run"
LOG_DIR="$RUN_DIR/logs"
PID_FILE="$RUN_DIR/platform.pids"
mkdir -p "$LOG_DIR"

START_DEEPEDIT=1
START_REACT="${START_REACT:-0}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
DEEPEDIT_HOST="${DEEPEDIT_HOST:-127.0.0.1}"
DEEPEDIT_PORT="${DEEPEDIT_PORT:-8010}"
REACT_PORT="${REACT_PORT:-5173}"

for arg in "$@"; do
  case "$arg" in
    --no-deepedit) START_DEEPEDIT=0 ;;
    --react) START_REACT=1 ;;
    --help|-h)
      sed -n '2,20p' "$0"
      exit 0
      ;;
  esac
done

# Prefer project venv python if present; DeepEdit needs torch+monai.
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/venv/bin/python" ]]; then
  PYTHON="$ROOT/venv/bin/python"
elif [[ -x /opt/miniconda3/bin/python ]]; then
  PYTHON=/opt/miniconda3/bin/python
else
  PYTHON="${PYTHON:-python3}"
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
  echo "[start_all] loaded .env"
else
  echo "[start_all] WARNING: .env not found — copying from .env.example"
  if [[ -f "$ROOT/.env.example" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
  fi
fi

# Keep DeepEdit URL aligned with this script's port unless user overrode it.
export DEEPEDIT_SERVICE_URL="${DEEPEDIT_SERVICE_URL:-http://${DEEPEDIT_HOST}:${DEEPEDIT_PORT}}"
export DEEPEDIT_MODEL_PATH="${DEEPEDIT_MODEL_PATH:-models/deepedit/deepedit_unet.pth}"
export DEEPEDIT_MODEL_FORMAT="${DEEPEDIT_MODEL_FORMAT:-monai_unet_checkpoint}"
export DEEPEDIT_CONFIG_PATH="${DEEPEDIT_CONFIG_PATH:-models/deepedit/config.json}"
export DEEPEDIT_DEVICE="${DEEPEDIT_DEVICE:-auto}"
# Full annotation/3D/gesture/surgery live in legacy frontend
export USE_REACT_FRONTEND="${USE_REACT_FRONTEND:-0}"

port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

wait_http() {
  local url="$1"
  local name="$2"
  local tries="${3:-40}"
  local i
  for ((i = 1; i <= tries; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[start_all] $name ready: $url"
      return 0
    fi
    sleep 0.5
  done
  echo "[start_all] WARNING: $name not ready yet ($url) — check $LOG_DIR"
  return 1
}

append_pid() {
  local name="$1"
  local pid="$2"
  echo "${name}:${pid}" >>"$PID_FILE"
}

# Stop previous managed processes if pid file exists
if [[ -f "$PID_FILE" ]]; then
  echo "[start_all] found previous pid file — stopping old stack first"
  bash "$ROOT/scripts/stop_all.sh" || true
fi
: >"$PID_FILE"

echo "[start_all] ROOT=$ROOT"
echo "[start_all] PYTHON=$PYTHON"
echo "[start_all] DEEPEDIT_SERVICE_URL=$DEEPEDIT_SERVICE_URL"

# Ensure SQLite schema is ready (idempotent)
if [[ -f "$ROOT/scripts/init_sqlite.py" ]]; then
  echo "[start_all] ensuring SQLite schema..."
  "$PYTHON" "$ROOT/scripts/init_sqlite.py" || true
fi

mkdir -p "$ROOT/models/deepedit"

# ---- DeepEdit :8010 ----
if [[ "$START_DEEPEDIT" == "1" ]]; then
  if port_in_use "$DEEPEDIT_PORT"; then
    echo "[start_all] port $DEEPEDIT_PORT already in use — assume DeepEdit is running"
  else
    if [[ ! -f "$ROOT/$DEEPEDIT_MODEL_PATH" && ! -f "$DEEPEDIT_MODEL_PATH" ]]; then
      echo "[start_all] WARNING: DeepEdit weights missing ($DEEPEDIT_MODEL_PATH)"
      echo "            service will start; /infer may fail and platform can fall back."
    fi
    echo "[start_all] starting DeepEdit on ${DEEPEDIT_HOST}:${DEEPEDIT_PORT} ..."
    nohup "$PYTHON" -m uvicorn ai.deepedit_service:app \
      --host "$DEEPEDIT_HOST" --port "$DEEPEDIT_PORT" \
      >"$LOG_DIR/deepedit.log" 2>&1 &
    append_pid "deepedit" $!
  fi
else
  echo "[start_all] skip DeepEdit (--no-deepedit)"
fi

# ---- Main backend + Legacy frontend :8000 ----
if port_in_use "$BACKEND_PORT"; then
  echo "[start_all] ERROR: port $BACKEND_PORT already in use."
  echo "            Stop the existing process or run: bash scripts/stop_all.sh"
  exit 1
fi

echo "[start_all] starting backend+frontend on ${BACKEND_HOST}:${BACKEND_PORT} ..."
nohup "$PYTHON" -m uvicorn backend.app.main:app \
  --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload \
  >"$LOG_DIR/backend.log" 2>&1 &
append_pid "backend" $!

# ---- Optional React :5173 ----
if [[ "$START_REACT" == "1" ]]; then
  if port_in_use "$REACT_PORT"; then
    echo "[start_all] port $REACT_PORT already in use — skip React"
  elif [[ -f "$ROOT/web/package.json" ]]; then
    if [[ ! -d "$ROOT/web/node_modules" ]]; then
      echo "[start_all] installing web dependencies (first run)..."
      (cd "$ROOT/web" && npm install) || echo "[start_all] WARNING: npm install failed"
    fi
    echo "[start_all] starting React Vite on :${REACT_PORT} ..."
    nohup npm --prefix "$ROOT/web" run dev -- --host 127.0.0.1 --port "$REACT_PORT" \
      >"$LOG_DIR/react.log" 2>&1 &
    append_pid "react" $!
  else
    echo "[start_all] WARNING: web/package.json not found — skip React"
  fi
fi

# Health waits
if [[ "$START_DEEPEDIT" == "1" ]]; then
  wait_http "http://${DEEPEDIT_HOST}:${DEEPEDIT_PORT}/health" "DeepEdit" 50 || true
fi
wait_http "http://${BACKEND_HOST}:${BACKEND_PORT}/api/health" "Backend" 60 || true

cat <<EOF

========================================
  Label Platform stack is up
========================================
  Legacy UI (full features):
    http://${BACKEND_HOST}:${BACKEND_PORT}/

  API docs:
    http://${BACKEND_HOST}:${BACKEND_PORT}/docs

  DeepEdit health:
    http://${DEEPEDIT_HOST}:${DEEPEDIT_PORT}/health

  Demo login:
    annotator / annotator123
    reviewer  / reviewer123
    admin     / admin123

  Logs:
    $LOG_DIR/backend.log
    $LOG_DIR/deepedit.log

  Stop all:
    bash scripts/stop_all.sh
========================================
EOF

if [[ "$START_REACT" == "1" ]]; then
  echo "  React UI (optional): http://127.0.0.1:${REACT_PORT}/"
  echo "  React log: $LOG_DIR/react.log"
  echo "========================================"
fi

echo "[start_all] Tip: for 3D / gesture / surgery, open the Legacy UI and use a multi-slice CT."
echo "[start_all] Tip: TotalSeg / nnU-Net need TOTALSEG_PYTHON or ORGANS_NNUNET_* in .env (no extra process)."
