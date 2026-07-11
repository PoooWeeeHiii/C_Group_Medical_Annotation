# Person B — Spleen nnUNet AI Predict 联调说明

## 已验证结果（本机）

| 项目 | 结果 |
| --- | --- |
| 测试病例 | `spleen_59` → 平台 `Case9001` / `Image9001` |
| Checkpoint | `checkpoint_best.pth` |
| Dice / IoU | **0.967 / 0.936** |
| 输出 | `dataset/labels/Case9001/v2_ai/Case9001_Image9001_Mask9001_v2_ai_spleen.nii.gz` |
| CPU 耗时 | 约 6–7 分钟 / 例 |
| API 健康检查 | `GET /api/ai/health` → `ready=true` |

## 启动后端（推荐用 nnUNet CPU 环境）

```powershell
$env:SPLEEN_NNUNET_PYTHON = "D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe"
cd D:\label_platform\C_Group_Medical_Annotation
D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开：http://127.0.0.1:8000

## 联调命令

```powershell
# 1) 推理冒烟 + 注册样例病例（约 6–7 分钟）
D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe -u scripts\smoke_spleen_predict.py --case spleen_59 --register

# 2) API 健康检查 / 病例可读性
D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe -u scripts\e2e_spleen_api.py

# 3) 完整 API 推理（再跑一遍 nnUNet，较慢）
D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe -u scripts\e2e_spleen_api.py --predict
```

## 前端操作

1. 打开「病例中心」，应能看到 `Case9001`
2. 进入标注工作台或 AI 推理中心
3. 点击 **AI预测** / **开始脾推理**
4. Mask 列表出现 `v2_ai` / `spleen`

## 接口

### `GET /api/ai/health`

检查权重与 nnUNet Python 是否就绪。

### `POST /api/ai/predict`

```json
{
  "case_id": "Case9001",
  "image_id": "Image9001",
  "model_id": "Model0002",
  "label": "spleen"
}
```

成功后写入：

- `dataset/labels/<Case>/v2_ai/..._spleen.nii.gz`
- `database/dev_masks.json`
- `database/dev_versions.json`（`v2_ai`）

## 注意

- 大权重与 NIfTI **不要提交 Git**
- GPU 环境 `venv_nnunet` 若 import 卡住，改用 `venv_nnunet_cpu`
- 当前仅支持 `label=spleen`
