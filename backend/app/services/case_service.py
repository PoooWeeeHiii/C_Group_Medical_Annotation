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
    if suffix == "dicom":
        return "dcm"
    return suffix or "unknown"


def _is_allowed_upload(filename: str) -> bool:
    name = filename.lower()
    if name.endswith(".nii.gz"):
        return True
    suffix = Path(name).suffix
    if suffix in ALLOWED_UPLOAD_EXTENSIONS:
        return True
    # DICOM series members are sometimes named without an extension.
    return suffix == "" and name != ""


def _looks_like_dicom_name(filename: str) -> bool:
    name = filename.lower()
    return name.endswith(".dcm") or name.endswith(".dicom") or Path(name).suffix == ""


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
    files: list[UploadFile] | UploadFile | None = None,
    *,
    file: UploadFile | None = None,
    source_group: str = "local",
    patient_id: str | None = None,
    modality: str | None = None,
) -> UploadResponse:
    from backend.app.services.gold_label_service import (
        attach_gold_labels_for_case,
        classify_upload_path,
        find_ct_and_labels_in_zip_extract,
        is_label_filename,
    )

    ensure_project_dirs()

    uploads: list[UploadFile] = []
    if isinstance(files, list):
        uploads.extend(files)
    elif files is not None:
        uploads.append(files)
    if file is not None:
        uploads.append(file)
    uploads = [item for item in uploads if item is not None and (item.filename or "").strip()]
    if not uploads:
        raise HTTPException(status_code=400, detail="请选择至少一个 CT / DICOM / NIfTI / NRRD / ZIP 文件")

    for item in uploads:
        if not _is_allowed_upload(item.filename or ""):
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {item.filename}. 请上传 DICOM、NIfTI、NRRD、PNG/JPG 或 zip。",
            )

    case_id = next_sqlite_entity_id("Case", "cases", "case_id")
    image_id = next_sqlite_entity_id("Image", "images", "image_id")
    case_patient_id = patient_id or case_id
    case_modality = (modality or "CT").upper()

    case_raw_dir = RAW_DATA_DIR / case_id
    case_raw_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for item in uploads:
        saved_paths.append(await save_upload_file(item, case_raw_dir))

    label_paths: list[Path] = []
    rtstruct_paths: list[Path] = []
    dicom_series_dir: Path | None = None
    primary_path: Path | None = None
    width, height, slice_count = 0, 0, None
    file_format = "unknown"
    filename = ""

    classified = [(path, classify_upload_path(path)) for path in saved_paths]
    ct_paths = [p for p, k in classified if k == "ct"]
    label_paths = [p for p, k in classified if k in {"label", "dicom_seg"}]
    rtstruct_paths = [p for p, k in classified if k == "rtstruct"]
    dicom_paths = [p for p, k in classified if k == "dicom"]
    archive_paths = [p for p, k in classified if k == "archive"]

    # Multi-file: CT volume + gold labels / RTSTRUCT
    if len(saved_paths) > 1 and (ct_paths or dicom_paths) and (label_paths or rtstruct_paths or len(dicom_paths) > 1):
        if ct_paths:
            primary_path = ct_paths[0]
            width, height, slice_count = _infer_dimensions(primary_path)
            file_format = _infer_format(primary_path)
            filename = primary_path.name
        elif dicom_paths:
            if not all(_looks_like_dicom_name(path.name) or classify_upload_path(path) in {"dicom", "rtstruct", "dicom_seg"} for path in saved_paths):
                # Allow mixed DICOM + RTSTRUCT / SEG
                pass
            series_only = [p for p in dicom_paths]
            if not series_only and not ct_paths:
                raise HTTPException(status_code=400, detail="未找到可用的 CT / DICOM 序列")
            primary_path = series_only[0] if series_only else saved_paths[0]
            width, height, slice_count = _infer_dicom_dimensions(primary_path) or (0, 0, None)
            if slice_count is None:
                slice_count = len(series_only) or None
            file_format = "dcm"
            filename = f"{len(series_only)}_dicom_slices"
            dicom_series_dir = primary_path.parent
        else:
            raise HTTPException(status_code=400, detail="多文件上传需要包含 CT 体积或 DICOM 序列")
    elif len(saved_paths) > 1 and all(_looks_like_dicom_name(path.name) for path in saved_paths):
        primary_path = next((path for path in saved_paths if path.suffix.lower() in {".dcm", ".dicom"}), saved_paths[0])
        width, height, slice_count = _infer_dicom_dimensions(primary_path) or (0, 0, None)
        if slice_count is None:
            slice_count = len(saved_paths)
        file_format = "dcm"
        filename = f"{len(saved_paths)}_dicom_slices"
        dicom_series_dir = primary_path.parent
    else:
        primary_path = saved_paths[0]
        # Zip may contain CT + label
        if _infer_format(primary_path) == "zip":
            extract_dir = case_raw_dir / "_extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with ZipFile(primary_path) as archive:
                archive.extractall(extract_dir)
            ct_inside, labels_inside = find_ct_and_labels_in_zip_extract(extract_dir)
            if ct_inside is not None:
                primary_path = ct_inside
                label_paths.extend(labels_inside)
                # Also discover RTSTRUCT inside zip
                for path in extract_dir.rglob("*"):
                    if path.is_file() and classify_upload_path(path) == "rtstruct":
                        rtstruct_paths.append(path)
                width, height, slice_count = _infer_dimensions(primary_path)
                file_format = _infer_format(primary_path)
                filename = primary_path.name
                if file_format == "dcm" or _looks_like_dicom_name(primary_path.name):
                    dicom_series_dir = primary_path.parent
            else:
                width, height, slice_count = _infer_dimensions(saved_paths[0])
                file_format = "zip"
                filename = saved_paths[0].name
                primary_path = saved_paths[0]
        elif is_label_filename(primary_path.name) and classify_upload_path(primary_path) == "label":
            raise HTTPException(
                status_code=400,
                detail="请同时上传 CT 图像与标签文件（或包含二者的 zip），不能只上传 label。",
            )
        else:
            width, height, slice_count = _infer_dimensions(primary_path)
            file_format = _infer_format(primary_path)
            filename = primary_path.name
            if classify_upload_path(primary_path) == "label":
                raise HTTPException(status_code=400, detail="请上传 CT，并将 label 作为附加文件一起选择")

    assert primary_path is not None
    image_path = primary_path

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
        "path": path_for_api(image_path, PROJECT_ROOT),
        "width": width,
        "height": height,
        "filename": filename,
        "file_format": file_format,
        "slice_count": slice_count,
    }

    upsert_record("cases", case_record)
    upsert_record("images", image_record)

    attached: list[dict] = []
    if label_paths or rtstruct_paths:
        try:
            attached = attach_gold_labels_for_case(
                case_id=case_id,
                image_id=image_id,
                label_paths=label_paths,
                rtstruct_paths=rtstruct_paths,
                dicom_series_dir=dicom_series_dir,
            )
            if attached:
                case_record["status"] = "annotated"
                upsert_record("cases", case_record)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"病例已创建，但金标准标签挂载失败: {exc}") from exc

    mask_ids = [str(item.get("mask_id")) for item in attached if item.get("mask_id")]
    message = "upload success"
    if mask_ids:
        message = f"upload success; attached {len(mask_ids)} gold mask(s)"

    return UploadResponse(
        success=True,
        case_id=case_id,
        image_id=image_id,
        patient_id=case_patient_id,
        modality=case_modality,
        path=image_record["path"],
        width=width or 0,
        height=height or 0,
        message=message,
        attached_masks=attached,
        attached_mask_ids=mask_ids,
        attached_mask_count=len(mask_ids),
    )
