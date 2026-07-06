from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATASET_DIR = PROJECT_ROOT / "dataset"
RAW_DATA_DIR = DATASET_DIR / "raw"
LABELS_DATA_DIR = DATASET_DIR / "labels"
SPLITS_DATA_DIR = DATASET_DIR / "splits"
DATABASE_DIR = PROJECT_ROOT / "database"
SCHEMA_SQL_PATH = DATABASE_DIR / "schema.sql"
SQLITE_DB_PATH = DATABASE_DIR / "app.db"

CASES_DB_PATH = DATABASE_DIR / "dev_cases.json"
IMAGES_DB_PATH = DATABASE_DIR / "dev_images.json"
MASKS_DB_PATH = DATABASE_DIR / "dev_masks.json"
VERSIONS_DB_PATH = DATABASE_DIR / "dev_versions.json"
DATASETS_DB_PATH = DATABASE_DIR / "dev_datasets.json"

ALLOWED_UPLOAD_EXTENSIONS = {
    ".dcm",
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
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
