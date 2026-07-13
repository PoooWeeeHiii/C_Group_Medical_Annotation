# Person B — Plan A 多器官 nnUNet AI Predict 联调说明

与脾脏 `docs/10_spleen_ai_predict.md` 对齐：冒烟脚本、API e2e、Person B 短 ID、健康检查。

## 已验证结果（本机）

| 部位 | model_id | 平台别名 | Mean Val Dice | 冒烟 Dice（spleen_10 vs 伪标） | 耗时 |
| --- | --- | --- | --- | --- | --- |
| 心 | `heart_nnunet_ds510` | `Model0010` | 0.613 | 0.182（偏低，已知） | ~178s |
| 肝 | `liver_nnunet_ds511` | `Model0011` | 0.921 | ~0.885（先前冒烟） | ~184s |
| 肺 | `lung_nnunet_ds512` | `Model0012` | 0.950 | **0.978** | ~177s |
| 肾 | `kidney_nnunet_ds513` | `Model0013` | 0.813 | **0.876** | ~177s |

冒烟 Dice 对比的是 DeepEdit/TotalSeg **伪标签**，不是独立金标准。心脏单例偏低属已知；演示优先肝/肺。

平台病例：`Case9010`–`Case9013`（CT=`spleen_10`）。
权重根目录：`E:\lxy\hm_2_organs_nnunet\`（勿提交 `.pth`）。
API 健康：`organ nnUNet ready 4/4 (heart,liver,lung,kidney)`。

## 启动后端

```powershell
$env:ORGANS_NNUNET_ROOT = "E:\lxy\hm_2_organs_nnunet"
$env:ORGANS_NNUNET_PYTHON = "D:\anaconda\python.exe"
cd E:\lxy\C_Group_Medical_Annotation
D:\anaconda\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器：http://127.0.0.1:8000

## 联调命令

```powershell
# 1) 环境检查（不跑推理）
D:\anaconda\python.exe -u scripts\smoke_organ_predict.py --organ all --skip-predict

# 2) 单器官推理冒烟 + 注册病例（约 3 分钟/例，GPU）
D:\anaconda\python.exe -u scripts\smoke_organ_predict.py --organ heart --case spleen_10 --register
D:\anaconda\python.exe -u scripts\smoke_organ_predict.py --organ liver --case spleen_10 --register
D:\anaconda\python.exe -u scripts\smoke_organ_predict.py --organ lung --case spleen_10 --register
D:\anaconda\python.exe -u scripts\smoke_organ_predict.py --organ kidney --case spleen_10 --register

# 或一次跑四个
D:\anaconda\python.exe -u scripts\smoke_organ_predict.py --organ all --case spleen_10 --register

# 3) API 健康检查 / 病例可读
D:\anaconda\python.exe -u scripts\e2e_organ_api.py --organ all

# 4) 完整 API 推理（再跑 nnUNet）
D:\anaconda\python.exe -u scripts\e2e_organ_api.py --organ liver --predict
```

指标写入：`outputs/organ_smoke_metrics_{organ}.json`  
预测副本：`E:\lxy\hm_2_organs_nnunet\smoke_infer\`

## 前端操作

1. 病例中心应能看到 `Case9010`–`Case9013`
2. AI 推理选择对应模型（`Model0010`–`Model0013` 或 `*_nnunet_ds51x`）
3. Mask 列表出现 `v2_ai` / `heart|liver|lung|kidney`

## 接口

### `GET /api/ai/health`

`message` 中含 `organ nnUNet ready N/4 (...)`；任一器官权重就绪即可 `ready=true`。

### `POST /api/ai/predict`

```json
{
  "case_id": "Case9011",
  "image_id": "Image9011",
  "model_id": "Model0011",
  "label": "liver"
}
```

成功后写入：

- `dataset/labels/<Case>/v2_ai/..._{label}.nii.gz`
- `database/dev_masks.json`
- `database/dev_versions.json`（`v2_ai`）

期望：`model_status=organ_nnunet`，`backend=organ_nnunet_local`。

## 注意

- 大权重与 NIfTI **不要提交 Git**
- 肺/肾训练与推理均为 **左右合并二值**
- 心脏 Val Dice 偏低属已知；演示可优先用肝/肺
- 在线 demo 仍可用 `totalseg_*`；本组 ID 展示 Person B 自训多器官 nnUNet
