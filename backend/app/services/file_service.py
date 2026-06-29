import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import UploadFile


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list")
    return data


def save_json_list(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def next_entity_id(prefix: str, items: list[dict[str, Any]], key: str) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    max_number = 0
    for item in items:
        value = str(item.get(key, ""))
        match = pattern.match(value)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"{prefix}{max_number + 1:04d}"


def safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        return "upload.bin"
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


async def save_upload_file(upload_file: UploadFile, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_filename(upload_file.filename or "upload.bin")

    with target_path.open("wb") as f:
        while True:
            chunk = await upload_file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    await upload_file.close()
    return target_path


def path_for_api(path: Path, project_root: Path) -> str:
    return str(path.resolve().relative_to(project_root.resolve()))

