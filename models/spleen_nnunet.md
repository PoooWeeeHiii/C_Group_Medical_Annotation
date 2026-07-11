# Spleen nnUNet Model (Model0002)

Do not commit `.pth` weights into git. Keep them outside the repository and point the platform to the local training output.

## Recommended local layout

```text
D:\hm_2_spleen\
  nnUNet_results\
    Dataset506_Spleen\
      nnUNetTrainer_100epochs__nnUNetPlans__2d\
        dataset.json
        plans.json
        fold_0\
          checkpoint_best.pth
          checkpoint_final.pth
  venv_nnunet\          # preferred GPU env with nnunetv2
  venv_nnunet_cpu\      # optional CPU fallback
```

## Platform wiring

- Model ID: `Model0002`
- Label: `spleen`
- Version written by AI: `v2_ai`
- Output path example:

```text
dataset/labels/Case0001/v2_ai/Case0001_Image0001_Mask0001_v2_ai_spleen.nii.gz
```

- API: `POST /api/ai/predict`

```json
{
  "case_id": "Case0001",
  "image_id": "Image0001",
  "model_id": "Model0002",
  "label": "spleen"
}
```

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `SPLEEN_NNUNET_ROOT` | `D:\hm_2_spleen` | Local spleen workspace root |
| `SPLEEN_MODEL_DIR` | `...\nnUNetTrainer_100epochs__nnUNetPlans__2d` | Trained model folder |
| `SPLEEN_CHECKPOINT_NAME` | `checkpoint_best.pth` | Prefer best over final |
| `SPLEEN_NNUNET_PYTHON` | `D:\hm_2_spleen\venv_nnunet\Scripts\python.exe` | Python that has `nnunetv2` |
| `nnUNet_results` | `D:\hm_2_spleen\nnUNet_results` | nnUNet results root |

## Which checkpoint to use

- Prefer `checkpoint_best.pth` for AI annotation.
- Use `checkpoint_final.pth` only if you intentionally want the last-epoch weights.

## Runtime note

The predictor prefers the configured `SPLEEN_NNUNET_PYTHON` via CLI when the current
interpreter is different. Default points to the CPU env:

```text
D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe
```

Switch to `venv_nnunet` when CUDA import works reliably.

## Local verification

```powershell
D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe -u scripts\smoke_spleen_predict.py --case spleen_59 --register
D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe -u scripts\e2e_spleen_api.py
```

See [docs/10_spleen_ai_predict.md](../docs/10_spleen_ai_predict.md) for the full联调流程.
