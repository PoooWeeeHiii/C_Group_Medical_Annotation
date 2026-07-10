from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.core.config import (
    CASES_DB_PATH,
    DATASETS_DB_PATH,
    DATABASE_DIR,
    IMAGES_DB_PATH,
    MASKS_DB_PATH,
    SCHEMA_SQL_PATH,
    SQLITE_DB_PATH,
    VERSIONS_DB_PATH,
)


_MIGRATED = False


JSON_PATH_TO_TABLE = {
    CASES_DB_PATH.resolve(): "cases",
    IMAGES_DB_PATH.resolve(): "images",
    MASKS_DB_PATH.resolve(): "masks",
    VERSIONS_DB_PATH.resolve(): "versions",
    DATASETS_DB_PATH.resolve(): "datasets",
}


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _create_time(item: dict[str, Any]) -> str:
    return str(item.get("create_time") or datetime.now().replace(microsecond=0).isoformat())


def _read_json_list_direct(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list")
    return data


def connect() -> sqlite3.Connection:
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(SQLITE_DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_sqlite_database() -> None:
    if not SCHEMA_SQL_PATH.exists():
        raise FileNotFoundError(f"schema.sql not found: {SCHEMA_SQL_PATH}")
    with connect() as connection:
        connection.executescript(SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
        _ensure_preview_version_supported(connection)


def _table_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return str(row["sql"] if row and row["sql"] else "")


def _ensure_preview_version_supported(connection: sqlite3.Connection) -> None:
    schema_sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    changed = False
    if _table_sql(connection, "masks") and "v3_preview" not in _table_sql(connection, "masks"):
        connection.executescript(
            """
            PRAGMA foreign_keys = OFF;
            ALTER TABLE masks RENAME TO masks_old;
            CREATE TABLE masks (
                mask_id TEXT PRIMARY KEY,
                annotation_id TEXT,
                case_id TEXT NOT NULL,
                image_id TEXT NOT NULL,
                path TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT 'v1_manual'
                    CHECK (version IN ('v1_manual', 'v2_ai', 'v3_preview', 'v3_fusion', 'final')),
                label TEXT NOT NULL DEFAULT 'label',
                label_id INTEGER,
                mask_format TEXT NOT NULL DEFAULT 'nii.gz' CHECK (mask_format IN ('json', 'nii.gz', 'nrrd')),
                slice_index INTEGER CHECK (slice_index IS NULL OR slice_index >= 0),
                width INTEGER CHECK (width IS NULL OR width >= 0),
                height INTEGER CHECK (height IS NULL OR height >= 0),
                encoding TEXT,
                source_mask_ids TEXT,
                shape TEXT,
                spacing TEXT,
                origin TEXT,
                direction TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (annotation_id) REFERENCES annotations(annotation_id) ON DELETE SET NULL,
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE,
                FOREIGN KEY (image_id) REFERENCES images(image_id) ON DELETE CASCADE
            );
            INSERT INTO masks (
                mask_id, annotation_id, case_id, image_id, path, version, label, label_id,
                mask_format, slice_index, width, height, encoding, source_mask_ids,
                shape, spacing, origin, direction, create_time
            )
            SELECT
                mask_id, annotation_id, case_id, image_id, path, version, label, label_id,
                mask_format, slice_index, width, height, encoding, source_mask_ids,
                shape, spacing, origin, direction, create_time
            FROM masks_old;
            DROP TABLE masks_old;
            PRAGMA foreign_keys = ON;
            """
        )
        changed = True
    if _table_sql(connection, "datasets") and "v3_preview" not in _table_sql(connection, "datasets"):
        connection.executescript(
            """
            PRAGMA foreign_keys = OFF;
            ALTER TABLE datasets RENAME TO datasets_old;
            CREATE TABLE datasets (
                dataset_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT 'medical_segmentation_dataset',
                version TEXT NOT NULL DEFAULT 'final'
                    CHECK (version IN ('v1_manual', 'v2_ai', 'v3_preview', 'v3_fusion', 'final')),
                train TEXT NOT NULL DEFAULT '[]',
                val TEXT NOT NULL DEFAULT '[]',
                test TEXT NOT NULL DEFAULT '[]',
                format TEXT NOT NULL DEFAULT 'nnunet',
                manifest_path TEXT,
                split_path TEXT,
                label_map_path TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO datasets (
                dataset_id, name, version, train, val, test, format,
                manifest_path, split_path, label_map_path, create_time
            )
            SELECT
                dataset_id, name, version, train, val, test, format,
                manifest_path, split_path, label_map_path, create_time
            FROM datasets_old;
            DROP TABLE datasets_old;
            PRAGMA foreign_keys = ON;
            """
        )
        changed = True
    if _table_sql(connection, "versions") and "v3_preview" not in _table_sql(connection, "versions"):
        connection.executescript(
            """
            PRAGMA foreign_keys = OFF;
            ALTER TABLE versions RENAME TO versions_old;
            CREATE TABLE versions (
                version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                version TEXT NOT NULL CHECK (version IN ('v1_manual', 'v2_ai', 'v3_preview', 'v3_fusion', 'final')),
                annotation TEXT,
                model TEXT,
                dataset TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (case_id, version),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE,
                FOREIGN KEY (model) REFERENCES models(model_id) ON DELETE SET NULL,
                FOREIGN KEY (dataset) REFERENCES datasets(dataset_id) ON DELETE SET NULL
            );
            INSERT INTO versions (version_id, case_id, version, annotation, model, dataset, create_time)
            SELECT version_id, case_id, version, annotation, model, dataset, create_time
            FROM versions_old;
            DROP TABLE versions_old;
            PRAGMA foreign_keys = ON;
            """
        )
        changed = True
    if changed:
        connection.executescript(schema_sql)


def ensure_sqlite_ready() -> None:
    global _MIGRATED
    init_sqlite_database()
    if not _MIGRATED and not sqlite_has_core_data():
        migrate_json_to_sqlite()
    _MIGRATED = True


def sqlite_has_core_data() -> bool:
    with connect() as connection:
        for table in ("cases", "images", "masks", "versions", "datasets"):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if int(count) > 0:
                return True
    return False


def _upsert_case(connection: sqlite3.Connection, item: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO cases (case_id, patient_id, modality, source_group, status, create_time)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(case_id) DO UPDATE SET
            patient_id=excluded.patient_id,
            modality=excluded.modality,
            source_group=excluded.source_group,
            status=excluded.status,
            create_time=excluded.create_time
        """,
        (
            item.get("case_id"),
            item.get("patient_id") or item.get("case_id"),
            item.get("modality") or "CT",
            item.get("source_group") or "local",
            item.get("status") or "unannotated",
            _create_time(item),
        ),
    )


def _upsert_image(connection: sqlite3.Connection, item: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO images (
            image_id, case_id, path, filename, file_format, width, height, slice_count,
            spacing, origin, direction, create_time
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(image_id) DO UPDATE SET
            case_id=excluded.case_id,
            path=excluded.path,
            filename=excluded.filename,
            file_format=excluded.file_format,
            width=excluded.width,
            height=excluded.height,
            slice_count=excluded.slice_count,
            spacing=excluded.spacing,
            origin=excluded.origin,
            direction=excluded.direction,
            create_time=excluded.create_time
        """,
        (
            item.get("image_id"),
            item.get("case_id"),
            item.get("path") or "",
            item.get("filename"),
            item.get("file_format"),
            int(item.get("width") or 0),
            int(item.get("height") or 0),
            item.get("slice_count"),
            _json_text(item.get("spacing")),
            _json_text(item.get("origin")),
            _json_text(item.get("direction")),
            _create_time(item),
        ),
    )


def _ensure_annotation(connection: sqlite3.Connection, annotation_id: str | None, image_id: str | None, source: str) -> None:
    if not annotation_id or not image_id:
        return
    connection.execute(
        """
        INSERT OR IGNORE INTO annotations (annotation_id, image_id, user_id, source, create_time)
        VALUES (?, ?, NULL, ?, CURRENT_TIMESTAMP)
        """,
        (annotation_id, image_id, source),
    )


def _upsert_mask(connection: sqlite3.Connection, item: dict[str, Any]) -> None:
    source = "ai" if item.get("version") == "v2_ai" else "manual"
    if item.get("version") in {"v3_preview", "v3_fusion"}:
        source = "fusion"
    _ensure_annotation(connection, item.get("annotation_id"), item.get("image_id"), source)
    connection.execute(
        """
        INSERT INTO masks (
            mask_id, annotation_id, case_id, image_id, path, version, label, label_id,
            mask_format, slice_index, width, height, encoding, source_mask_ids,
            shape, spacing, origin, direction, create_time
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mask_id) DO UPDATE SET
            annotation_id=excluded.annotation_id,
            case_id=excluded.case_id,
            image_id=excluded.image_id,
            path=excluded.path,
            version=excluded.version,
            label=excluded.label,
            label_id=excluded.label_id,
            mask_format=excluded.mask_format,
            slice_index=excluded.slice_index,
            width=excluded.width,
            height=excluded.height,
            encoding=excluded.encoding,
            source_mask_ids=excluded.source_mask_ids,
            shape=excluded.shape,
            spacing=excluded.spacing,
            origin=excluded.origin,
            direction=excluded.direction,
            create_time=excluded.create_time
        """,
        (
            item.get("mask_id"),
            item.get("annotation_id"),
            item.get("case_id"),
            item.get("image_id"),
            item.get("path") or "",
            item.get("version") or "v1_manual",
            item.get("label") or "label",
            item.get("label_id"),
            item.get("mask_format") or "nii.gz",
            item.get("slice_index"),
            item.get("width"),
            item.get("height"),
            item.get("encoding"),
            _json_text(item.get("source_mask_ids")),
            _json_text(item.get("shape")),
            _json_text(item.get("spacing")),
            _json_text(item.get("origin")),
            _json_text(item.get("direction")),
            _create_time(item),
        ),
    )


def _ensure_model(connection: sqlite3.Connection, model_id: str | None) -> None:
    if not model_id:
        return
    connection.execute(
        """
        INSERT OR IGNORE INTO models (model_id, version, dice, path, metrics_json, create_time)
        VALUES (?, ?, NULL, NULL, NULL, CURRENT_TIMESTAMP)
        """,
        (model_id, model_id),
    )


def _upsert_model(connection: sqlite3.Connection, item: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO models (model_id, version, dice, path, metrics_json, create_time)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(model_id) DO UPDATE SET
            version=excluded.version,
            dice=excluded.dice,
            path=excluded.path,
            metrics_json=excluded.metrics_json,
            create_time=excluded.create_time
        """,
        (
            item.get("model_id"),
            item.get("version") or item.get("model_id"),
            item.get("dice"),
            item.get("path"),
            _json_text(item.get("metrics_json")),
            _create_time(item),
        ),
    )


def _ensure_dataset(connection: sqlite3.Connection, dataset_id: str | None) -> None:
    if not dataset_id:
        return
    connection.execute(
        """
        INSERT OR IGNORE INTO datasets (dataset_id, name, version, train, val, test, format, create_time)
        VALUES (?, ?, 'final', '[]', '[]', '[]', 'nnunet', CURRENT_TIMESTAMP)
        """,
        (dataset_id, dataset_id),
    )


def _upsert_version(connection: sqlite3.Connection, item: dict[str, Any]) -> None:
    _ensure_model(connection, item.get("model"))
    _ensure_dataset(connection, item.get("dataset"))
    connection.execute(
        """
        INSERT INTO versions (case_id, version, annotation, model, dataset, create_time)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(case_id, version) DO UPDATE SET
            annotation=excluded.annotation,
            model=excluded.model,
            dataset=excluded.dataset,
            create_time=excluded.create_time
        """,
        (
            item.get("case_id"),
            item.get("version") or "v1_manual",
            item.get("annotation"),
            item.get("model"),
            item.get("dataset"),
            _create_time(item),
        ),
    )


def _upsert_dataset(connection: sqlite3.Connection, item: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO datasets (
            dataset_id, name, version, train, val, test, format,
            manifest_path, split_path, label_map_path, create_time
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset_id) DO UPDATE SET
            name=excluded.name,
            version=excluded.version,
            train=excluded.train,
            val=excluded.val,
            test=excluded.test,
            format=excluded.format,
            manifest_path=excluded.manifest_path,
            split_path=excluded.split_path,
            label_map_path=excluded.label_map_path,
            create_time=excluded.create_time
        """,
        (
            item.get("dataset_id"),
            item.get("name") or "medical_segmentation_dataset",
            item.get("version") or "final",
            _json_text(item.get("train") or []),
            _json_text(item.get("val") or []),
            _json_text(item.get("test") or []),
            item.get("format") or "nnunet",
            item.get("manifest_path") or item.get("output_path"),
            item.get("split_path"),
            item.get("label_map_path"),
            _create_time(item),
        ),
    )


UPSERT_BY_TABLE = {
    "cases": _upsert_case,
    "images": _upsert_image,
    "masks": _upsert_mask,
    "models": _upsert_model,
    "versions": _upsert_version,
    "datasets": _upsert_dataset,
}


def sync_items_to_sqlite(path: Path, items: list[dict[str, Any]]) -> bool:
    table = JSON_PATH_TO_TABLE.get(path.resolve())
    if table is None:
        return False
    ensure_sqlite_ready()
    upsert = UPSERT_BY_TABLE[table]
    with connect() as connection:
        for item in items:
            upsert(connection, item)
    return True


def migrate_json_to_sqlite() -> None:
    init_sqlite_database()
    with connect() as connection:
        for path, table in JSON_PATH_TO_TABLE.items():
            upsert = UPSERT_BY_TABLE[table]
            for item in _read_json_list_direct(path):
                upsert(connection, item)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in row.keys()} for row in rows]


def list_records(table: str) -> list[dict[str, Any]]:
    if table not in UPSERT_BY_TABLE:
        raise ValueError(f"Unsupported table: {table}")
    ensure_sqlite_ready()
    with connect() as connection:
        if table == "versions":
            rows = connection.execute(
                "SELECT case_id, version, annotation, model, dataset, create_time FROM versions ORDER BY version_id"
            ).fetchall()
        else:
            rows = connection.execute(f"SELECT * FROM {table}").fetchall()
    return _rows_to_dicts(rows)


def get_record(table: str, key: str, value: str) -> dict[str, Any] | None:
    if table not in UPSERT_BY_TABLE:
        raise ValueError(f"Unsupported table: {table}")
    ensure_sqlite_ready()
    with connect() as connection:
        row = connection.execute(f"SELECT * FROM {table} WHERE {key} = ?", (value,)).fetchone()
    return dict(row) if row else None


def upsert_record(table: str, item: dict[str, Any]) -> None:
    if table not in UPSERT_BY_TABLE:
        raise ValueError(f"Unsupported table: {table}")
    ensure_sqlite_ready()
    with connect() as connection:
        UPSERT_BY_TABLE[table](connection, item)


def upsert_records(table: str, items: list[dict[str, Any]]) -> None:
    if table not in UPSERT_BY_TABLE:
        raise ValueError(f"Unsupported table: {table}")
    ensure_sqlite_ready()
    with connect() as connection:
        upsert = UPSERT_BY_TABLE[table]
        for item in items:
            upsert(connection, item)


def next_sqlite_entity_id(prefix: str, table: str, key: str) -> str:
    records = list_records(table)
    import re

    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    max_number = 0
    for record in records:
        match = pattern.match(str(record.get(key) or ""))
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"{prefix}{max_number + 1:04d}"


def load_items_from_sqlite(path: Path) -> list[dict[str, Any]] | None:
    table = JSON_PATH_TO_TABLE.get(path.resolve())
    if table is None:
        return None
    ensure_sqlite_ready()
    with connect() as connection:
        if table == "versions":
            rows = connection.execute(
                "SELECT case_id, version, annotation, model, dataset, create_time FROM versions ORDER BY version_id"
            ).fetchall()
        else:
            rows = connection.execute(f"SELECT * FROM {table}").fetchall()
    return _rows_to_dicts(rows)
