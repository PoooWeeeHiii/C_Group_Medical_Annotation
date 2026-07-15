#!/usr/bin/env bash
# Run system tests against a live backend and write a markdown/JSON report.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${ROOT}/.test_deps:${ROOT}:${PYTHONPATH:-}"
export SYSTEM_TEST_BASE_URL="${SYSTEM_TEST_BASE_URL:-http://127.0.0.1:8000}"

PY="${PYTHON:-/opt/miniconda3/bin/python}"
if ! "$PY" -c "import pytest,httpx" 2>/dev/null; then
  echo "[setup] installing pytest/httpx into .test_deps ..."
  "$PY" -m pip install pytest httpx --target "${ROOT}/.test_deps" -q
fi

mkdir -p "${ROOT}/docs/report" "${ROOT}/tests/system/output"
STAMP="$(date '+%Y%m%d_%H%M%S')"
JUNIT="${ROOT}/tests/system/output/junit_${STAMP}.xml"
JSONL="${ROOT}/tests/system/output/report_${STAMP}.json"
MD="${ROOT}/docs/report/system_test_report.md"

echo "[run] SYSTEM_TEST_BASE_URL=${SYSTEM_TEST_BASE_URL}"
set +e
"$PY" -m pytest tests/system -v --tb=short \
  --junitxml="${JUNIT}" \
  -o cache_dir=tests/system/output/.pytest_cache
CODE=$?
set -e

"$PY" "${ROOT}/tests/system/generate_report.py" \
  --junit "${JUNIT}" \
  --markdown "${MD}" \
  --json "${JSONL}" \
  --base-url "${SYSTEM_TEST_BASE_URL}" \
  --exit-code "${CODE}"

echo "[done] report -> ${MD}"
exit "${CODE}"
