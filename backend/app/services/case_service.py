from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from fastapi import HTTPException, UploadFile

from backend.app.core.config import (
    ALLOWED_UPLOAD_EXTENSIONS,
    PROJECT_ROOT,
    RAW_DATA_DIR,
    ensure_project_dirs,
)
from backend.app.schemas.case import CaseListItem, CaseRecord
from backend.app.schemas.image import ImageRecord
from backend.app.schemas.upload import UploadResponse
from backend.app.services.file_service import (
    path_for_api,
    save_upload_file,
)
from backend.app.services.sqlite_service import (
    get_record,
    list_records,
    next_sqlite_entity_id,
    upsert_record,
)
from backend.app.services.workflow_service import latest_reject_note


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _infer_format(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".nii.gz"):
        return "nii.gz"
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "unknown"


def _is_allowed_upload(filename: str) -> bool:
    name = filename.lower()
    if name.endswith(".nii.gz"):
        return True
    return Path(name).suffix in ALLOWED_UPLOAD_EXTENSIONS


def _parse_nrrd_sizes_from_text(text: str) -> tuple[int, int, int | None] | None:
    for line in text.splitlines():
        if line.lower().startswith("sizes:"):
            values = line.split(":", 1)[1].strip().split()
            if len(values) >= 2:
                width = int(values[0])
                height = int(values[1])
                slices = int(values[2]) if len(values) >= 3 else None
                return width, height, slices
    return None


def _infer_nrrd_dimensions(path: Path) -> tuple[int, int, int | None] | None:
    with path.open("rb") as f:
        header = f.read(8192).decode("utf-8", errors="ignore")
    return _parse_nrrd_sizes_from_text(header)


def _infer_zip_dimensions(path: Path) -> tuple[int, int, int | None] | None:
    with ZipFile(path) as archive:
        for name in archive.namelist():
            lower_name = name.lower()
            if lower_name.endswith(".nrrd"):
                header = archive.read(name, pwd=None)[:8192].decode("utf-8", errors="ignore")
                parsed = _parse_nrrd_sizes_from_text(header)
                if parsed:
                    return parsed
            if lower_name.endswith(".dcm"):
                try:
                    import pydicom

                    with archive.open(name) as dcm_file:
                        dataset = pydicom.dcmread(dcm_file, stop_before_pixels=True, force=True)
                    rows = int(getattr(dataset, "Rows", 0) or 0)
                    columns = int(getattr(dataset, "Columns", 0) or 0)
                    if rows and columns:
                        return columns, rows, None
                except Exception:
                    continue
    return None


def _infer_dicom_dimensions(path: Path) -> tuple[int, int, int | None] | None:
    try:
        import pydicom

        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        rows = int(getattr(dataset, "Rows", 0) or 0)
        columns = int(getattr(dataset, "Columns", 0) or 0)
        if rows and columns:
            return columns, rows, None
    except Exception:
        return None
    return None


def _infer_dimensions(path: Path) -> tuple[int, int, int | None]:
    file_format = _infer_format(path)
    try:
        if file_format == "nrrd":
            parsed = _infer_nrrd_dimensions(path)
            if parsed:
                return parsed
        if file_format == "zip":
            parsed = _infer_zip_dimensions(path)
            if parsed:
                return parsed
        if file_format == "dcm":
            parsed = _infer_dicom_dimensions(path)
            if parsed:
                return parsed
    except Exception:
        pass

    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            return width, height, None
    except Exception:
        return 0, 0, None


def _load_cases() -> list[dict]:
    return list_records("cases")


def _load_images() -> list[dict]:
    return list_records("images")


def _load_masks() -> list[dict]:
    return list_records("masks")


def list_cases() -> list[CaseListItem]:
    cases = _load_cases()
    images = _load_images()
    masks = _load_masks()

    result: list[CaseListItem] = []
    for case in cases:
        image_count = sum(1 for image in images if image.get("case_id") == case.get("case_id"))
        mask_count = sum(1 for mask in masks if mask.get("case_id") == case.get("case_id"))
        enriched = {
            **case,
            "reject_note": latest_reject_note(str(case.get("case_id") or "")),
        }
        result.append(CaseListItem(**enriched, image_count=image_count, mask_count=mask_count))
    return result


def get_case(case_id: str) -> tuple[CaseRecord, list[ImageRecord]]:
    images = _load_images()

    case_data = get_record("cases", "case_id", case_id)
    if case_data is None:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")

    case_images = [ImageRecord(**image) for image in images if image.get("case_id") == case_id]
    enriched = {**case_data, "reject_note": latest_reject_note(case_id)}
    return CaseRecord(**enriched), case_images


def get_image(image_id: str) -> ImageRecord:
    image_data = get_record("images", "image_id", image_id)
    if image_data is None:
        raise HTTPException(status_code=404, detail=f"Image not found: {image_id}")
    return ImageRecord(**image_data)


async def create_case_from_upload(
    file: UploadFile,
    source_group: str = "local",
    patient_id: str | None = None,
    modality: str | None = None,
) -> UploadResponse:
    ensure_project_dirs()
    if not file.filename or not _is_allowed_upload(file.filename):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload DICOM, NIfTI, NRRD, PNG/JPG, or zip.",
        )

    case_id = next_sqlite_entity_id("Case", "cases", "case_id")
    image_id = next_sqlite_entity_id("Image", "images", "image_id")
    case_patient_id = patient_id or case_id
    case_modality = (modality or "CT").upper()

    case_raw_dir = RAW_DATA_DIR / case_id
    saved_path = await save_upload_file(file, case_raw_dir)
    width, height, slice_count = _infer_dimensions(saved_path)
    file_format = _infer_format(saved_path)

    case_record = {
        "case_id": case_id,
        "patient_id": case_patient_id,
        "modality": case_modality,
        "create_time": _now_iso(),
        "source_group": source_group or "local",
        "status": "unannotated",
    }
    image_record = {
        "image_id": image_id,
        "case_id": case_id,
        "path": path_for_api(saved_path, PROJECT_ROOT),
        "width": width,
        "height": height,
        "filename": saved_path.name,
        "file_format": file_format,
        "slice_count": slice_count,
    }

    upsert_record("cases", case_record)
    upsert_record("images", image_record)

    return UploadResponse(
        success=True,
        case_id=case_id,
        image_id=image_id,
        patient_id=case_patient_id,
        modality=case_modality,
        path=image_record["path"],
        width=width,
        height=height,
        message="upload success",
    )
