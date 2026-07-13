# Person B — Day2: preprocessing & augmentation

## Goals

1. Implement `ai/preprocess.py` (load / normalize / resize / crop / save)
2. Add `ai/augment.py` for training-time augmentation
3. Convert Lung sample data into `dataset/images/` and `dataset/labels/` using group naming rules
4. Stay compatible with Person A uploads under `dataset/raw/{Case_id}/`

## Modules

| File | Role |
|------|------|
| `ai/preprocess.py` | DICOM series, DICOM SEG, NRRD, PNG load; CT HU window; 2D export |
| `ai/augment.py` | flip / rotate / brightness (train only) |
| `ai/pipeline.py` | Lung example conversion + raw upload hook |
| `scripts/convert_lung_examples.py` | CLI entry for local Lung data |

## Naming (aligned with docs/01)

- Image: `dataset/images/Case0001/Case0001_Image0001_lung_nodule.png`
- AI mask: `dataset/labels/Case0001/v2_ai/Case0001_Image0001_Mask0001_v2_ai_lung_nodule.png`
- Manual mask: `dataset/labels/Case0004/v1_manual/...`

## Case mapping

| Case | Source | Label version |
|------|--------|---------------|
| Case0001 | LUNG1-001 DICOM + SEG | v2_ai |
| Case0002 | LUNG1-002 DICOM + SEG | v2_ai |
| Case0003 | LUNG1-003 DICOM + SEG | v2_ai |
| Case0004 | patient1 NRRD | v1_manual |

## Run locally

```bash
pip install highdicom pynrrd
python scripts/convert_lung_examples.py --lung-root /path/to/Lung
```

Output manifest: `dataset/splits/Dataset0001_manifest.json` (committed; image files are gitignored).

## Person A integration

After upload via `POST /api/upload`, raw files land in `dataset/raw/CaseXXXX/`.
Call `ai.pipeline.process_raw_upload(case_id)` to export a preview PNG into `dataset/images/`.

## Day3 已完成

见 [09_person_b_day3.md](09_person_b_day3.md)：`LungSegmentationDataset` + `build_dataloader()`，兼容 Person A `POST /api/export` manifest。
