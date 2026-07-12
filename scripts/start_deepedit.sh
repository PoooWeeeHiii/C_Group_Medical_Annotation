#!/usr/bin/env bash
# Start the standalone DeepEdit inference service on :8010
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export DEEPEDIT_MODEL_PATH="${DEEPEDIT_MODEL_PATH:-models/deepedit/deepedit_unet.pth}"
export DEEPEDIT_MODEL_FORMAT="${DEEPEDIT_MODEL_FORMAT:-monai_unet_checkpoint}"
export DEEPEDIT_CONFIG_PATH="${DEEPEDIT_CONFIG_PATH:-models/deepedit/config.json}"
export DEEPEDIT_DEVICE="${DEEPEDIT_DEVICE:-auto}"
export DEEPEDIT_THRESHOLD="${DEEPEDIT_THRESHOLD:-0.5}"

mkdir -p "$ROOT/models/deepedit"

echo "[DeepEdit] PROJECT_ROOT=$ROOT"
echo "[DeepEdit] MODEL_PATH=$DEEPEDIT_MODEL_PATH"
echo "[DeepEdit] listening on http://127.0.0.1:8010"
echo "[DeepEdit] health: curl -s http://127.0.0.1:8010/health"
if [[ ! -f "$ROOT/$DEEPEDIT_MODEL_PATH" && ! -f "$DEEPEDIT_MODEL_PATH" ]]; then
  echo "[DeepEdit] WARNING: weight file not found. Service will start but /infer returns success=false;"
  echo "           platform will fall back to random_walker until you place TorchScript/MONAI weights."
fi

exec python -m uvicorn ai.deepedit_service:app --host 127.0.0.1 --port 8010 --reload
