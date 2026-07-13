#!/usr/bin/env python3
"""Convert local Lung sample data into dataset/images + dataset/labels (Person B Day2)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.pipeline import convert_lung_examples, write_manifest  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Lung examples to standardized dataset layout")
    parser.add_argument(
        "--lung-root",
        type=Path,
        default=Path("/Users/liuyue/Desktop/pl/Lung"),
        help="Path to local Lung sample directory",
    )
    parser.add_argument("--dataset-id", default="Dataset0001")
    args = parser.parse_args()
    if not args.lung_root.exists():
        raise SystemExit(f"Lung root not found: {args.lung_root}")
    entries = convert_lung_examples(args.lung_root)
    manifest_path = write_manifest(entries, args.dataset_id)
    print(f"Converted {len(entries)} cases.")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
