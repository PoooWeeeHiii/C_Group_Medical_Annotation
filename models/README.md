# Models

Do not commit large model weight files such as `.pth`, `.pt`, `.ckpt`, `.onnx`, or `.h5`.

Only keep model notes, configuration examples, or download links here.

Recommended future layout:

```text
models/
  README.md
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
