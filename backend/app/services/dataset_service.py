from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from backend.app.core.config import (
    CASES_DB_PATH,
    DATASETS_DB_PATH,
    IMAGES_DB_PATH,
    MASKS_DB_PATH,
    PROJECT_ROOT,
    SPLITS_DATA_DIR,
    ensure_project_dirs,
)
from backend.app.schemas.dataset import DatasetExportRequest, DatasetExportResponse
from backend.app.services.file_service import (
    load_json_list,
    next_entity_id,
    path_for_api,
    save_json_list,
)
from backend.app.services.version_service import VALID_VERSIONS


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: dict) -> None:
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
    return {case["case_id"]: case for case in load_json_list(CASES_DB_PATH)}


def _images_by_case() -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for image in load_json_list(IMAGES_DB_PATH):
        result.setdefault(str(image.get("case_id")), []).append(image)
    return result


def _masks_by_case_and_version() -> dict[tuple[str, str], list[dict]]:
    result: dict[tuple[str, str], list[dict]] = {}
    for mask in load_json_list(MASKS_DB_PATH):
        key = (str(mask.get("case_id")), str(mask.get("version")))
        result.setdefault(key, []).append(mask)
    return result


def _records_for_split(
    split_name: str,
    case_ids: list[str],
    version: str,
    cases: dict[str, dict],
    images: dict[str, list[dict]],
    masks: dict[tuple[str, str], list[dict]],
) -> list[dict]:
    records: list[dict] = []
    for case_id in case_ids:
        if case_id not in cases:
            raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")
        case_images = images.get(case_id, [])
        if not case_images:
            raise HTTPException(status_code=400, detail=f"Case {case_id} has no image")
        case_masks = masks.get((case_id, version), [])
        if not case_masks:
            raise HTTPException(
                status_code=400,
                detail=f"Case {case_id} has no {version} mask. Save mask or export another version.",
            )

        for image in case_images:
            image_masks = [mask for mask in case_masks if mask.get("image_id") == image.get("image_id")]
            if not image_masks:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image {image.get('image_id')} has no {version} mask",
                )
            for mask in image_masks:
                records.append(
                    {
                        "split": split_name,
                        "case_id": case_id,
                        "image_id": image.get("image_id"),
                        "image_path": image.get("path"),
                        "mask_id": mask.get("mask_id"),
                        "mask_path": mask.get("path"),
                        "version": version,
                        "label": mask.get("label", "label"),
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


def export_dataset(request: DatasetExportRequest) -> DatasetExportResponse:
    ensure_project_dirs()
    version = request.version.strip()
    if version not in VALID_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported version: {version}. Use one of {sorted(VALID_VERSIONS)}",
        )
    _validate_disjoint_splits(request.train, request.val, request.test)

    datasets = load_json_list(DATASETS_DB_PATH)
    dataset_id = request.dataset_id or next_entity_id("Dataset", datasets, "dataset_id")

    cases = _case_lookup()
    images = _images_by_case()
    masks = _masks_by_case_and_version()
    train_records = _records_for_split("train", request.train, version, cases, images, masks)
    val_records = _records_for_split("val", request.val, version, cases, images, masks)
    test_records = _records_for_split("test", request.test, version, cases, images, masks)
    records = train_records + val_records + test_records
    if not records:
        raise HTTPException(status_code=400, detail="Dataset export requires at least one case")

    split_payload = {
        "dataset_id": dataset_id,
        "version": version,
        "train": request.train,
        "val": request.val,
        "test": request.test,
    }
    label_map_payload = _label_map(records)
    manifest_payload = {
        "dataset_id": dataset_id,
        "name": request.name,
        "version": version,
        "format": request.format,
        "create_time": _now_iso(),
        "counts": {
            "train": len(train_records),
            "val": len(val_records),
            "test": len(test_records),
            "total": len(records),
        },
        "label_map": label_map_payload,
        "records": records,
    }

    manifest_path = SPLITS_DATA_DIR / f"{dataset_id}_manifest.json"
    split_path = SPLITS_DATA_DIR / f"{dataset_id}_split.json"
    label_map_path = SPLITS_DATA_DIR / f"{dataset_id}_label_map.json"
    _write_json(manifest_path, manifest_payload)
    _write_json(split_path, split_payload)
    _write_json(label_map_path, label_map_payload)

    dataset_record = {
        "dataset_id": dataset_id,
        "name": request.name,
        "version": version,
        "format": request.format,
        "manifest_path": path_for_api(manifest_path, PROJECT_ROOT),
        "split_path": path_for_api(split_path, PROJECT_ROOT),
        "label_map_path": path_for_api(label_map_path, PROJECT_ROOT),
        "train_count": len(train_records),
        "val_count": len(val_records),
        "test_count": len(test_records),
        "create_time": manifest_payload["create_time"],
    }
    existing_index = next(
        (index for index, item in enumerate(datasets) if item.get("dataset_id") == dataset_id),
        None,
    )
    if existing_index is None:
        datasets.append(dataset_record)
    else:
        datasets[existing_index] = dataset_record
    save_json_list(DATASETS_DB_PATH, datasets)

    return DatasetExportResponse(
        success=True,
        dataset_id=dataset_id,
        output_path=dataset_record["manifest_path"],
        split_path=dataset_record["split_path"],
        label_map_path=dataset_record["label_map_path"],
        train_count=len(train_records),
        val_count=len(val_records),
        test_count=len(test_records),
        message="export success",
    )
