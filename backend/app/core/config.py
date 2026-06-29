from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATASET_DIR = PROJECT_ROOT / "dataset"
RAW_DATA_DIR = DATASET_DIR / "raw"
DATABASE_DIR = PROJECT_ROOT / "database"

CASES_DB_PATH = DATABASE_DIR / "dev_cases.json"
IMAGES_DB_PATH = DATABASE_DIR / "dev_images.json"

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
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)

