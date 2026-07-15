import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if load_dotenv is not None:
    # Prefer project-root .env so local REPORT_POLISH_* / DEEPEDIT_* win over stale shell env.
    load_dotenv(PROJECT_ROOT / ".env", override=True)

DATASET_DIR = PROJECT_ROOT / "dataset"
RAW_DATA_DIR = DATASET_DIR / "raw"
LABELS_DATA_DIR = DATASET_DIR / "labels"
SPLITS_DATA_DIR = DATASET_DIR / "splits"
EXPORTS_DATA_DIR = DATASET_DIR / "exports"
DATABASE_DIR = PROJECT_ROOT / "database"
SCHEMA_SQL_PATH = DATABASE_DIR / "schema.sql"
SQLITE_DB_PATH = DATABASE_DIR / "app.db"
DEEPEDIT_SERVICE_URL = os.getenv("DEEPEDIT_SERVICE_URL", "").strip()
DEEPEDIT_SERVICE_TIMEOUT_SECONDS = float(os.getenv("DEEPEDIT_SERVICE_TIMEOUT_SECONDS", "120"))
# OpenAI-compatible chat API for quality-report polish (optional).
# Providers: DeepSeek / OpenAI / Gemini(OpenAI-compat) via REPORT_POLISH_* in .env
REPORT_POLISH_API_KEY = os.getenv("REPORT_POLISH_API_KEY", "").strip()
REPORT_POLISH_BASE_URL = os.getenv("REPORT_POLISH_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
REPORT_POLISH_MODEL = os.getenv("REPORT_POLISH_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
REPORT_POLISH_TIMEOUT_SECONDS = float(os.getenv("REPORT_POLISH_TIMEOUT_SECONDS", "90"))
JWT_SECRET = os.getenv("JWT_SECRET", "label-platform-dev-secret-change-me").strip() or "label-platform-dev-secret"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

CASES_DB_PATH = DATABASE_DIR / "dev_cases.json"
IMAGES_DB_PATH = DATABASE_DIR / "dev_images.json"
MASKS_DB_PATH = DATABASE_DIR / "dev_masks.json"
VERSIONS_DB_PATH = DATABASE_DIR / "dev_versions.json"
DATASETS_DB_PATH = DATABASE_DIR / "dev_datasets.json"

ALLOWED_UPLOAD_EXTENSIONS = {
    ".dcm",
    ".dicom",
    ".zip",
    ".nii",
    ".gz",
    ".nrrd",
    ".png",
    ".jpg",
    ".jpeg",
}


def ensure_project_dirs() -> None:
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LABELS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SPLITS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
