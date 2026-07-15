#!/usr/bin/env bash
# Train platform 2.5D U-Net on a materialized Dataset export.
# Usage:
#   bash scripts/start_platform_train.sh Dataset_tumor
#   bash scripts/start_platform_train.sh Dataset_tumor 20 ModelUNet_tumor
#   RESUME=1 bash scripts/start_platform_train.sh Dataset_other 10 ModelUNet_other
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

DATASET_ID="${1:-}"
EPOCHS="${2:-20}"
MODEL_ID="${3:-}"
NUM_CLASSES="${NUM_CLASSES:-9}"
IMAGE_SIZE="${IMAGE_SIZE:-320}"
CONTEXT_RADIUS="${CONTEXT_RADIUS:-1}"
BATCH_SIZE="${BATCH_SIZE:-4}"
RESUME="${RESUME:-1}"

if [[ -z "$DATASET_ID" ]]; then
  echo "Usage: bash scripts/start_platform_train.sh <DatasetID> [epochs=20] [model_id]"
  echo "Example: bash scripts/start_platform_train.sh Dataset_tumor 20 ModelUNet_tumor"
  echo "Same-class incremental: keep Dataset_tumor / Dataset_other, append exports, RESUME=1 (default)"
  exit 1
fi

EXPORT_DIR="$ROOT/dataset/exports/$DATASET_ID"
if [[ ! -d "$EXPORT_DIR" ]]; then
  echo "[train] Missing export dir: $EXPORT_DIR"
  echo "[train] Run 标注台「按推荐流程执行」or Dataset 导出 (materialize + append) first."
  exit 1
fi

# Prefer a Python that already has torch (same probe order as DeepEdit).
if [[ -n "${PYTHON:-}" && -x "${PYTHON}" ]]; then
  :
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/venv/bin/python" ]]; then
  PYTHON="$ROOT/venv/bin/python"
elif [[ -x /opt/miniconda3/bin/python ]]; then
  PYTHON=/opt/miniconda3/bin/python
else
  PYTHON="${PYTHON:-python3}"
fi

if [[ -z "$MODEL_ID" ]]; then
  # Map Dataset_tumor → ModelUNet_tumor when possible.
  if [[ "$DATASET_ID" == Dataset_* ]]; then
    MODEL_ID="ModelUNet_${DATASET_ID#Dataset_}"
  else
    MODEL_ID="ModelUNet_${DATASET_ID}"
  fi
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

ARGS=(
  --dataset-id "$DATASET_ID"
  --model-id "$MODEL_ID"
  --epochs "$EPOCHS"
  --batch-size "$BATCH_SIZE"
  --num-classes "$NUM_CLASSES"
  --image-size "$IMAGE_SIZE"
  --context-radius "$CONTEXT_RADIUS"
  --export-dir "dataset/exports/$DATASET_ID"
)
if [[ "$RESUME" == "1" || "$RESUME" == "true" || "$RESUME" == "yes" ]]; then
  ARGS+=(--resume)
fi

echo "[train] PROJECT_ROOT=$ROOT"
echo "[train] PYTHON=$PYTHON"
echo "[train] dataset_id=$DATASET_ID model_id=$MODEL_ID epochs=$EPOCHS resume=$RESUME"
echo "[train] tip: other label_id=8 needs Classes≥9 (auto-raised if labels are higher)"

exec "$PYTHON" "$ROOT/ai/train.py" "${ARGS[@]}"
