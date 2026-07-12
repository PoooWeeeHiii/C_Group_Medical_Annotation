# Models

Do not commit large model weight files such as `.pth`, `.pt`, `.ckpt`, `.onnx`, or `.h5`.

Only keep model notes, configuration examples, or download links here.

Current notes:

- [spleen_nnunet.md](spleen_nnunet.md): local Dataset506 spleen nnUNet weights for `POST /api/ai/predict`

Recommended layout:

```text
models/
  README.md
  spleen_nnunet.md
  deepedit/
    model.ts          # local only, ignored by Git
  model_registry.md
```

## DeepEdit Service

The current real-model integration supports two weight formats.

### Option A: TorchScript

```text
models/deepedit/model.ts
```

The model service is started with:

```bash
export DEEPEDIT_MODEL_PATH=models/deepedit/model.ts
export DEEPEDIT_MODEL_FORMAT=torchscript
export DEEPEDIT_DEVICE=auto
uvicorn ai.deepedit_service:app --host 127.0.0.1 --port 8010
```

### Option B: MONAI 3D UNet Checkpoint

Use `ai/deepedit_config.example.json` as the template:

```bash
cp ai/deepedit_config.example.json models/deepedit/config.json
```

Then edit `models/deepedit/config.json` so `path/channels/strides/out_channels` match Person B's model:

```bash
export DEEPEDIT_CONFIG_PATH=models/deepedit/config.json
export DEEPEDIT_MODEL_PATH=models/deepedit/deepedit_unet.pth
export DEEPEDIT_MODEL_FORMAT=monai_unet_checkpoint
export DEEPEDIT_DEVICE=auto
uvicorn ai.deepedit_service:app --host 127.0.0.1 --port 8010
```

Input tensor contract:

```text
[batch, channels, depth, height, width]
channels = CT normalized to [0,1] + positive click channel + negative click channel + current mask
```

Output contract:

```text
[batch, 1, depth, height, width]
```

Large weights remain local or on a private server/object storage. Do not commit them.

### Bootstrap + TotalSeg training (spleen DeepEdit)

```powershell
# 1) Init contract-aligned weights (optional if you will train immediately)
D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe scripts\export_deepedit_init_checkpoint.py

# 2) Train from Dataset606_TotalSeg_Spleen under TOTALSEG_ROOT
$env:TOTALSEG_ROOT = "D:\hm_2_totalseg"
D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe scripts\train_deepedit.py --limit 12 --epochs 5 --crop 48 96 96

# 3) Start DeepEdit service (Windows)
.\scripts\start_deepedit.ps1
# health: curl http://127.0.0.1:8010/health  → model_loaded=true
```

## AI Predict: TotalSegmentator

Platform model IDs (select in UI):

- `totalseg_organs` — **推荐**：一次约 24 个器官，每个器官一条 `v2_ai` mask
- `totalseg_total` — 全量 100+ 结构（更慢）
- `totalseg_spleen` / `totalseg_liver` / `totalseg_lung` — 单器官

```powershell
# Install once into the inference env
D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe -m pip install TotalSegmentator

# .env
TOTALSEG_PYTHON=D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe
TOTALSEG_DEVICE=auto
# TOTALSEG_FAST=true   # recommended on CPU
```

First prediction downloads official weights. This is **inference**, separate from using TotalSeg zip as DeepEdit training data.

