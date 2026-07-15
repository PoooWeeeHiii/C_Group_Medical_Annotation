# 半成品最大范围落地说明

本文档对应平台半成品收尾：诚实 AI 状态、金标准上传（含 RTSTRUCT）、多标签、多类导出、平台 U-Net 训练注册。

## P0 诚实 AI / DeepEdit

- `POST /api/ai/predict` 默认 `allow_baseline=false`；无真实后端时返回 422。
- 响应含 `model_status` / `backend` / `fallback_reason`。
- `POST /api/deepedit/refine` 默认 `require_neural=true`；失败请用标注台「图割修正」。

## P1 多标签

- 标注台可选肝/肾/肺/肿瘤/脾等类别；橡皮擦默认可只清当前类。
- 传播 / 图割会按 `label_id` 过滤并写回。

## P2–P3 金标准上传

- 支持：CT + `*label*.nii.gz/nrrd`、zip 内 CT+label、DICOM SEG、DICOM 序列 + RTSTRUCT。
- 成功时响应含 `attached_mask_ids`。

## P4 多类导出

- `materialize=true` 时按 case 合并多器官 mask 为单个多类 `labelsTr/*.nii.gz`。
- `dataset.json` 含平台 label 映射；报告含 `multiclass` 与 `class_voxel_counts`。

## P5–P6 训练与推理

**推荐流程（肿瘤 / 其他 → Dataset → 训练）：**

1. 标注时选「肿瘤」或「其他」（可起自定义名，体素仍是 8）
2. 保存 → 一键传播 / 精修 → 尽量确认到 `final`（精标），至少保留 `v3_preview`（弱标）
3. Dataset 导出：精标选 `final`、弱标选 `v3_preview`，勾选 **materialize**
4. 智能训练中心：填导出的 Dataset ID，开始训练（含「其他」时 **Classes ≥ 9**）

**一键执行（标注台）：** 右侧「推荐流程」卡片点 **「按推荐流程执行」**，自动：保存 → 传播 `v3_preview` →（有审核权时可选 promote `final`）→ **append** 进同类 Dataset（`Dataset_tumor` / `Dataset_other`）→ 跳转智能训练中心并预填 Dataset/Model ID（**不自动开训**；默认勾选 resume 增量续训）。

操作对应：

1. 导出 Dataset（勾选 materialize；同类增量固定 ID 并勾选 append）
2. 打开「智能训练中心」，填 Dataset ID / Model ID，勾选 resume，开始训练（默认 **20 epoch / 320² / 2.5D radius=1**，Classes 默认 9）
3. 任务完成后自动 `register_model(backend=platform_unet)`
4. 在「标注工作台」选用该模型预测（推理含 3D 填洞 + 最大连通域后处理）

CLI：

```bash
# 推荐：探测 torch Python；默认 resume 增量；num_classes=9（更高 id 会自动抬升）
bash scripts/start_platform_train.sh Dataset_tumor
RESUME=1 bash scripts/start_platform_train.sh Dataset_other 10 ModelUNet_other

# 或直接：
python ai/train.py --dataset-id Dataset_tumor --model-id ModelUNet_tumor --epochs 20 --resume --num-classes 9
```

说明：平台模型是 **2.5D 切片 U-Net**（邻层上下文），正式高精度请继续用 TotalSeg / nnUNet。同类新病例 append 进同一 Dataset 后，用 `--resume` 从已有 checkpoint 增量续训。

## 验收建议

1. 无权重时点 AI 预测 → 应失败并提示，而非 HU baseline 伪成功。
2. DeepEdit 服务未启动 → 「DeepEdit 神经网络」失败；「图割修正」仍可用。
3. 上传 `ct.nii.gz` + `ct-label.nii.gz` → 病例带 v1_manual mask。
4. 多标签画肝+脾 → 导出 labels 含多个非零 id。
5. 训练完成后模型列表出现 `platform_unet`，推理可选用。

## RTSTRUCT 改进要点

上传时请尽量使用 **同一次检查的 CT DICOM 序列 + RTSTRUCT**。

平台已做：
- 按 `FrameOfReferenceUID` 匹配 CT 序列
- 轮廓点越界比例质控（>50% 直接拒绝；>10% 告警并在上传 toast 提示）
- ROI 名映射可配置：`config/rtstruct_roi_map.json`

仍建议人工打开 2D 叠图确认一两层，再当金标准使用。
