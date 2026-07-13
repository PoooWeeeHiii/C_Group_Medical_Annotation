# Plan A multi-organ nnUNet (Person B)

Do not commit `.pth` weights into git. Keep them outside the repository and point the platform to the local Plan A training output.

## Recommended local layout

```text
E:\lxy\hm_2_organs_nnunet\
  nnUNet_results\
    Dataset510_DeepEdit_Heart\nnUNetTrainer_100epochs__nnUNetPlans__3d_fullres\fold_0\checkpoint_best.pth
    Dataset511_DeepEdit_Liver\...
    Dataset512_DeepEdit_Lung\...
    Dataset513_DeepEdit_Kidney\...
```

## Platform wiring

| model_id | Person B alias | label | Mean Val Dice |
| --- | --- | --- | --- |
| `heart_nnunet_ds510` | `Model0010` | heart | 0.613 |
| `liver_nnunet_ds511` | `Model0011` | liver | 0.921 |
| `lung_nnunet_ds512` | `Model0012` | lung | 0.950 |
| `kidney_nnunet_ds513` | `Model0013` | kidney | 0.813 |

- Backend: `organ_nnunet_local` → `ai/organ_nnunet.py`
- Version written by AI: `v2_ai`
- Output path example:

```text
dataset/labels/Case9011/v2_ai/Case9011_Image9011_Mask9011_v2_ai_liver.nii.gz
```

- API: `POST /api/ai/predict`

```json
{
  "case_id": "Case9011",
  "image_id": "Image9011",
  "model_id": "Model0011",
  "label": "liver"
}
```

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `ORGANS_NNUNET_ROOT` | `E:\lxy\hm_2_organs_nnunet` | Plan A workspace root |
| `ORGANS_NNUNET_RESULTS` | `...\nnUNet_results` | Results root |
| `ORGANS_NNUNET_PYTHON` | `D:\anaconda\python.exe` | Python with `nnunetv2` |
| `ORGANS_TRAINER` | `nnUNetTrainer_100epochs` | Trainer name |
| `ORGANS_CONFIGURATION` | `3d_fullres` | Configuration |
| `ORGANS_CHECKPOINT_NAME` | `checkpoint_best.pth` | Prefer best over final |

## Local verification

```powershell
D:\anaconda\python.exe -u scripts\smoke_organ_predict.py --organ all --case spleen_10 --register
D:\anaconda\python.exe -u scripts\e2e_organ_api.py --organ all
```

See [docs/15_organ_ai_predict.md](../docs/15_organ_ai_predict.md) for the full联调流程.
See [docs/14_planA_organs_nnunet.md](../docs/14_planA_organs_nnunet.md) for training details.

## Notes

- Labels are TotalSeg **pseudo**; high Dice means fitting the teacher, not independent GT.
- Lung/kidney are **left+right merged** binary masks.
- Online demo can still prefer `totalseg_*`; these IDs show Person B self-trained multi-organ nnUNet.
