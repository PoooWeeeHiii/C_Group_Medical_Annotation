from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import HTTPException

from backend.app.core.config import (
    EXPORTS_DATA_DIR,
    PROJECT_ROOT,
    SPLITS_DATA_DIR,
    ensure_project_dirs,
)
from backend.app.schemas.dataset import (
    DatasetExportReport,
    DatasetExportRequest,
    DatasetExportResponse,
    MissingMaskItem,
    SpacingCheckItem,
)
from backend.app.services.file_service import path_for_api
from backend.app.services.sqlite_service import list_records, next_sqlite_entity_id, upsert_record
from backend.app.services.version_service import VALID_VERSIONS


SPACING_TOLERANCE = 1e-3


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: dict | list) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def _validate_disjoint_splits(train: list[str], val: list[str], test: list[str]) -> None:
    seen: dict[str, str] = {}
    for split_name, case_ids in (("train", train), ("val", val), ("test", test)):
        for case_id in case_ids:
            if case_id in seen:
                raise HTTPException(
                    status_code=400,
                    detail=f"Case {case_id} appears in both {seen[case_id]} and {split_name}",
                )
            seen[case_id] = split_name


def _case_lookup() -> dict[str, dict]:
    return {case["case_id"]: case for case in list_records("cases")}


def _images_by_case() -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for image in list_records("images"):
        result.setdefault(str(image.get("case_id")), []).append(image)
    return result


def _masks_by_case_and_version() -> dict[tuple[str, str], list[dict]]:
    result: dict[tuple[str, str], list[dict]] = {}
    for mask in list_records("masks"):
        key = (str(mask.get("case_id")), str(mask.get("version")))
        result.setdefault(key, []).append(mask)
    return result


def _is_nifti_mask(mask: dict) -> bool:
    path = str(mask.get("path") or "")
    return mask.get("mask_format") == "nii.gz" or path.endswith(".nii.gz") or path.endswith(".nii")


def _pick_best_mask(masks: list[dict]) -> dict | None:
    if not masks:
        return None
    nifti = [mask for mask in masks if _is_nifti_mask(mask)]
    pool = nifti or masks
    return sorted(pool, key=lambda item: str(item.get("create_time") or ""), reverse=True)[0]


def _resolve_project_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    path = (PROJECT_ROOT / str(relative)).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return None
    return path


def _nnunet_case_id(case_id: str, image_id: str, multi_image: bool) -> str:
    safe_case = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in case_id)
    if not multi_image:
        return safe_case
    safe_image = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in image_id)
    return f"{safe_case}_{safe_image}"


def _collect_split_records(
    split_name: str,
    case_ids: list[str],
    version: str,
    cases: dict[str, dict],
    images: dict[str, list[dict]],
    masks: dict[tuple[str, str], list[dict]],
    *,
    strict: bool,
    missing: list[MissingMaskItem],
) -> list[dict]:
    records: list[dict] = []
    for case_id in case_ids:
        if case_id not in cases:
            if strict:
                raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")
            missing.append(MissingMaskItem(case_id=case_id, version=version, reason="case_not_found"))
            continue
        case_images = images.get(case_id, [])
        if not case_images:
            if strict:
                raise HTTPException(status_code=400, detail=f"Case {case_id} has no image")
            missing.append(MissingMaskItem(case_id=case_id, version=version, reason="no_image"))
            continue
        case_masks = masks.get((case_id, version), [])
        multi_image = len(case_images) > 1
        for image in case_images:
            image_id = str(image.get("image_id"))
            image_masks = [mask for mask in case_masks if mask.get("image_id") == image_id]
            best = _pick_best_mask(image_masks)
            if best is None:
                item = MissingMaskItem(
                    case_id=case_id,
                    image_id=image_id,
                    version=version,
                    reason=f"no_{version}_mask",
                )
                missing.append(item)
                if strict:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Image {image_id} has no {version} mask",
                    )
                continue
            if not _is_nifti_mask(best):
                item = MissingMaskItem(
                    case_id=case_id,
                    image_id=image_id,
                    version=version,
                    reason="mask_not_nifti_3d",
                )
                missing.append(item)
                if strict:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Image {image_id} {version} mask is not 3D NIfTI (got {best.get('mask_format')})",
                    )
                continue
            records.append(
                {
                    "split": split_name,
                    "case_id": case_id,
                    "image_id": image_id,
                    "image_path": image.get("path"),
                    "mask_id": best.get("mask_id"),
                    "mask_path": best.get("path"),
                    "version": version,
                    "label": best.get("label", "label"),
                    "nnunet_id": _nnunet_case_id(case_id, image_id, multi_image),
                    "spacing_check": "pending",
                }
            )
    return records


def _label_map(records: list[dict]) -> dict:
    labels = sorted({str(record.get("label") or "label") for record in records})
    return {
        "background": 0,
        **{label: index + 1 for index, label in enumerate(labels)},
    }


def _read_sitk_image(path: Path):
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required to materialize nnU-Net export") from exc
    return sitk.ReadImage(str(path))


def _write_sitk_image(image, path: Path) -> None:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required to materialize nnU-Net export") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(path))


def _ensure_nifti_image(source_path: Path, target_path: Path, *, image_id: str | None = None):
    """Copy or convert an image to .nii.gz, returning the SimpleITK image."""
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required to materialize nnU-Net export") from exc

    suffix = "".join(source_path.suffixes).lower()
    if suffix.endswith(".nii.gz") or source_path.suffix.lower() == ".nii":
        if source_path.resolve() != target_path.resolve():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
        return sitk.ReadImage(str(target_path))

    # Prefer platform volume loader (handles zip / DICOM / NRRD).
    if image_id:
        from backend.app.services.medical_image_service import load_volume

        _, volume = load_volume(image_id)
        image = sitk.GetImageFromArray(volume.array.astype(np.float32, copy=False))
        image.SetSpacing(tuple(float(value) for value in volume.spacing[:3]))
        if getattr(volume, "origin", None):
            image.SetOrigin(tuple(float(value) for value in volume.origin[:3]))
        direction = getattr(volume, "direction", None)
        if direction is not None:
            flat = [float(value) for value in list(direction)[:9]]
            if len(flat) == 9:
                image.SetDirection(flat)
        _write_sitk_image(image, target_path)
        return image

    if source_path.is_dir() or source_path.suffix.lower() == ".dcm":
        series_dir = source_path if source_path.is_dir() else source_path.parent
        names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(series_dir))
        if not names:
            raise HTTPException(status_code=400, detail=f"No DICOM series found at {source_path}")
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(names)
        image = reader.Execute()
    else:
        image = sitk.ReadImage(str(source_path))
    _write_sitk_image(image, target_path)
    return image


def _ensure_nifti_mask(source_path: Path, target_path: Path, label_value: int = 1):
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required to materialize nnU-Net export") from exc

    image = sitk.ReadImage(str(source_path))
    array = sitk.GetArrayFromImage(image)
    binary = (array > 0).astype(np.uint8) * int(label_value)
    out = sitk.GetImageFromArray(binary)
    out.CopyInformation(image)
    _write_sitk_image(out, target_path)
    return out


def _spacing_of(image) -> list[float]:
    return [float(value) for value in image.GetSpacing()[:3]]


def _shape_of(image) -> list[int]:
    # SimpleITK Size is x,y,z; report z,y,x to align with numpy arrays.
    size = image.GetSize()
    return [int(size[2]), int(size[1]), int(size[0])]


def _check_spacing(image, mask, *, case_id: str, image_id: str, mask_id: str) -> SpacingCheckItem:
    image_spacing = _spacing_of(image)
    mask_spacing = _spacing_of(mask)
    image_shape = _shape_of(image)
    mask_shape = _shape_of(mask)
    spacing_ok = all(abs(a - b) <= SPACING_TOLERANCE for a, b in zip(image_spacing, mask_spacing))
    shape_ok = image_shape == mask_shape
    if spacing_ok and shape_ok:
        status = "ok"
        detail = None
    elif not shape_ok:
        status = "shape_mismatch"
        detail = f"shape image={image_shape} mask={mask_shape}"
    else:
        status = "spacing_mismatch"
        detail = f"spacing image={image_spacing} mask={mask_spacing}"
    return SpacingCheckItem(
        case_id=case_id,
        image_id=image_id,
        mask_id=mask_id,
        status=status,
        image_spacing=image_spacing,
        mask_spacing=mask_spacing,
        image_shape=image_shape,
        mask_shape=mask_shape,
        detail=detail,
    )


def _materialize_nnunet(
    dataset_id: str,
    name: str,
    version: str,
    records: list[dict],
    train_ids: list[str],
    val_ids: list[str],
    test_ids: list[str],
    label_map: dict[str, int],
) -> tuple[Path, Path, Path, DatasetExportReport]:
    export_root = EXPORTS_DATA_DIR / dataset_id
    if export_root.exists():
        shutil.rmtree(export_root)
    for folder in ("imagesTr", "labelsTr", "imagesTs", "labelsTs"):
        (export_root / folder).mkdir(parents=True, exist_ok=True)

    report = DatasetExportReport(export_dir=path_for_api(export_root, PROJECT_ROOT))
    label_to_id = {str(k): int(v) for k, v in label_map.items() if k != "background"}

    for record in records:
        case_id = str(record["case_id"])
        image_id = str(record["image_id"])
        mask_id = str(record["mask_id"])
        nnunet_id = str(record["nnunet_id"])
        is_test = record["split"] == "test"
        image_dir = export_root / ("imagesTs" if is_test else "imagesTr")
        label_dir = export_root / ("labelsTs" if is_test else "labelsTr")
        image_out = image_dir / f"{nnunet_id}_0000.nii.gz"
        label_out = label_dir / f"{nnunet_id}.nii.gz"

        image_src = _resolve_project_path(str(record.get("image_path") or ""))
        mask_src = _resolve_project_path(str(record.get("mask_path") or ""))
        if image_src is None or not image_src.exists():
            report.missing_masks.append(
                MissingMaskItem(case_id=case_id, image_id=image_id, version=version, reason="image_file_missing")
            )
            report.skipped_count += 1
            continue
        if mask_src is None or not mask_src.exists():
            report.missing_masks.append(
                MissingMaskItem(case_id=case_id, image_id=image_id, version=version, reason="mask_file_missing")
            )
            report.skipped_count += 1
            continue

        try:
            image = _ensure_nifti_image(image_src, image_out, image_id=image_id)
            label_value = label_to_id.get(str(record.get("label") or "label"), 1)
            mask = _ensure_nifti_mask(mask_src, label_out, label_value=label_value)
            check = _check_spacing(image, mask, case_id=case_id, image_id=image_id, mask_id=mask_id)
            report.spacing_checks.append(check)
            record["spacing_check"] = check.status
            if check.status != "ok":
                # Keep files but mark warning; nnU-Net will fail later if shape mismatches.
                pass
            report.materialized_files.append(path_for_api(image_out, PROJECT_ROOT))
            report.materialized_files.append(path_for_api(label_out, PROJECT_ROOT))
            report.success_count += 1
        except HTTPException:
            raise
        except Exception as exc:
            report.missing_masks.append(
                MissingMaskItem(
                    case_id=case_id,
                    image_id=image_id,
                    version=version,
                    reason=f"materialize_failed: {exc}",
                )
            )
            report.skipped_count += 1

    # dataset.json — nnU-Net v2 style
    labels_payload = {"background": 0, **{name: idx for name, idx in label_to_id.items()}}
    training_count = sum(1 for record in records if record["split"] in {"train", "val"} and record.get("spacing_check") != "pending")
    # Prefer counting successfully written train/val pairs.
    training_count = len(list((export_root / "imagesTr").glob("*_0000.nii.gz")))
    dataset_json = {
        "name": name or dataset_id,
        "description": f"Exported from label_platform version={version}",
        "channel_names": {"0": "CT"},
        "labels": labels_payload,
        "numTraining": training_count,
        "file_ending": ".nii.gz",
        "overwrite_image_reader_writer": "SimpleITKIO",
    }
    dataset_json_path = export_root / "dataset.json"
    _write_json(dataset_json_path, dataset_json)

    # splits_final.json — train/val identifiers (without _0000 suffix)
    train_nnunet_ids = sorted({str(r["nnunet_id"]) for r in records if r["split"] == "train"})
    val_nnunet_ids = sorted({str(r["nnunet_id"]) for r in records if r["split"] == "val"})
    # Also include original case lists for readability.
    splits_final = [
        {
            "train": train_nnunet_ids,
            "val": val_nnunet_ids,
            "train_cases": train_ids,
            "val_cases": val_ids,
            "test_cases": test_ids,
        }
    ]
    splits_final_path = export_root / "splits_final.json"
    _write_json(splits_final_path, splits_final)

    report.export_dir = path_for_api(export_root, PROJECT_ROOT)
    return export_root, dataset_json_path, splits_final_path, report


def export_dataset(request: DatasetExportRequest) -> DatasetExportResponse:
    ensure_project_dirs()
    label_set = (request.label_set or "dense").strip().lower()
    if label_set not in {"dense", "weak"}:
        raise HTTPException(status_code=400, detail="label_set must be 'dense' or 'weak'")

    version = request.version.strip()
    # 弱标签约定：未显式改 version 时默认导出 v3_preview（伪标）；精标默认 final。
    if label_set == "weak" and version == "final":
        version = "v3_preview"
    if label_set == "dense" and version == "v3_preview":
        # 允许显式用 v3_preview 作 dense 预览导出，但不自动改写。
        pass
    if version not in VALID_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported version: {version}. Use one of {sorted(VALID_VERSIONS)}",
        )
    _validate_disjoint_splits(request.train, request.val, request.test)

    dataset_id = request.dataset_id or next_sqlite_entity_id("Dataset", "datasets", "dataset_id")

    cases = _case_lookup()
    images = _images_by_case()
    masks = _masks_by_case_and_version()
    missing: list[MissingMaskItem] = []
    # When materializing, allow non-strict collection so UI can show missing list;
    # still raise if strict and anything missing after collection.
    collect_strict = request.strict and not request.materialize
    train_records = _collect_split_records(
        "train", request.train, version, cases, images, masks, strict=collect_strict, missing=missing
    )
    val_records = _collect_split_records(
        "val", request.val, version, cases, images, masks, strict=collect_strict, missing=missing
    )
    test_records = _collect_split_records(
        "test", request.test, version, cases, images, masks, strict=collect_strict, missing=missing
    )
    records = train_records + val_records + test_records

    if request.materialize and request.strict and missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Export validation failed: missing or non-NIfTI masks",
                "missing_masks": [item.model_dump() for item in missing],
            },
        )
    if not records:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Dataset export requires at least one valid case with 3D NIfTI mask",
                "missing_masks": [item.model_dump() for item in missing],
            },
        )

    label_map_payload = _label_map(records)
    split_payload = {
        "dataset_id": dataset_id,
        "version": version,
        "label_set": label_set,
        "train": request.train,
        "val": request.val,
        "test": request.test,
    }
    manifest_payload = {
        "dataset_id": dataset_id,
        "name": request.name,
        "version": version,
        "label_set": label_set,
        "format": request.format,
        "materialize": request.materialize,
        "create_time": _now_iso(),
        "counts": {
            "train": len(train_records),
            "val": len(val_records),
            "test": len(test_records),
            "total": len(records),
        },
        "label_map": label_map_payload,
        "records": records,
        "missing_masks": [item.model_dump() for item in missing],
        "notes": {
            "weak": "weak label_set typically uses v3_preview (pseudo) propagated from sparse v1_manual coarse/scribble",
            "dense": "dense label_set typically uses final / v3_fusion refined annotations",
        }.get(label_set),
    }

    manifest_path = SPLITS_DATA_DIR / f"{dataset_id}_manifest.json"
    split_path = SPLITS_DATA_DIR / f"{dataset_id}_split.json"
    label_map_path = SPLITS_DATA_DIR / f"{dataset_id}_label_map.json"
    _write_json(manifest_path, manifest_payload)
    _write_json(split_path, split_payload)
    _write_json(label_map_path, label_map_payload)

    export_dir = None
    dataset_json_path = None
    splits_final_path = None
    report = DatasetExportReport(missing_masks=missing)

    if request.materialize:
        if request.format not in {"nnunet", "nnUNet", "NNUNET"}:
            raise HTTPException(status_code=400, detail="materialize=true currently supports format=nnunet only")
        export_root, dataset_json_file, splits_final_file, report = _materialize_nnunet(
            dataset_id=dataset_id,
            name=request.name,
            version=version,
            records=records,
            train_ids=request.train,
            val_ids=request.val,
            test_ids=request.test,
            label_map=label_map_payload,
        )
        # Preserve previously collected missing items that blocked materialization of some cases.
        if missing:
            seen = {(item.case_id, item.image_id, item.reason) for item in report.missing_masks}
            for item in missing:
                key = (item.case_id, item.image_id, item.reason)
                if key not in seen:
                    report.missing_masks.append(item)
        export_dir = path_for_api(export_root, PROJECT_ROOT)
        dataset_json_path = path_for_api(dataset_json_file, PROJECT_ROOT)
        splits_final_path = path_for_api(splits_final_file, PROJECT_ROOT)
        manifest_payload["export_dir"] = export_dir
        manifest_payload["dataset_json"] = dataset_json_path
        manifest_payload["splits_final"] = splits_final_path
        manifest_payload["report"] = report.model_dump()
        _write_json(manifest_path, manifest_payload)

    dataset_record = {
        "dataset_id": dataset_id,
        "name": request.name,
        "version": version,
        "format": request.format,
        "train": request.train,
        "val": request.val,
        "test": request.test,
        "manifest_path": path_for_api(manifest_path, PROJECT_ROOT),
        "split_path": path_for_api(split_path, PROJECT_ROOT),
        "label_map_path": path_for_api(label_map_path, PROJECT_ROOT),
        "export_dir": export_dir,
        "train_count": len(train_records),
        "val_count": len(val_records),
        "test_count": len(test_records),
        "create_time": manifest_payload["create_time"],
    }
    upsert_record("datasets", dataset_record)

    message = "export success"
    if request.materialize:
        message = (
            f"materialized nnU-Net dataset at {export_dir} "
            f"(ok={report.success_count}, skipped={report.skipped_count})"
        )
    if label_set == "weak":
        message = f"[weak/{version}] {message}"
    else:
        message = f"[dense/{version}] {message}"

    return DatasetExportResponse(
        success=True,
        dataset_id=dataset_id,
        output_path=dataset_record["manifest_path"],
        split_path=dataset_record["split_path"],
        label_map_path=dataset_record["label_map_path"],
        train_count=len(train_records),
        val_count=len(val_records),
        test_count=len(test_records),
        message=message,
        materialize=request.materialize,
        label_set=label_set,
        version=version,
        export_dir=export_dir,
        dataset_json_path=dataset_json_path,
        splits_final_path=splits_final_path,
        report=report if request.materialize or missing else None,
    )
