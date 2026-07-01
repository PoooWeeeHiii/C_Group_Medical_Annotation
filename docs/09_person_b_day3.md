# Person B — Day3: Dataset & DataLoader

## Goals (规划.docx)

Person B Day3: **Dataset 制作、DataLoader**，与 Person A Day3（DICOM/NIfTI 浏览、切片显示）联调。

## Implemented

| Module | Role |
|--------|------|
| `ai/datasets/lung_dataset.py` | Read split + manifest, load PNG/NIfTI, train-time augment |
| `ai/train.py` | DataLoader smoke test for train/val/test |
| `scripts/verify_dataloader.py` | Quick local validation |

## Manifest formats supported

### Day2 (Person B preprocess export)

```json
{
  "entries": [
    {"case_id": "Case0001", "image_path": "...", "label_path": "..."}
  ]
}
```

Split file lists case IDs per split: `train` / `val` / `test`.

### Person A platform export (`POST /api/export`)

```json
{
  "records": [
    {
      "split": "train",
      "case_id": "Case0001",
      "image_path": "...",
      "mask_path": "...",
      "version": "final"
    }
  ]
}
```

`LungSegmentationDataset` accepts both formats.

## Usage

```bash
# After Day2 conversion (local PNG pairs)
python scripts/verify_dataloader.py
python ai/train.py
```

Train split applies `augment.augment_pair()`; val/test do not.

## Person A alignment

- Reads paths from `dataset/splits/Dataset0001_manifest.json` produced by `backend/app/services/dataset_service.py`
- Mask paths follow `dataset/labels/{case_id}/{version}/...` (PNG from Day2 or nii.gz from platform)
- Split JSON matches `Dataset0001_split.json` from export API

## Day4 handoff

- Implement `UNet2D`, `loss.py`, and training loop in `train.py`
- Save best checkpoint to `ai/checkpoints/Model0001.pt`
