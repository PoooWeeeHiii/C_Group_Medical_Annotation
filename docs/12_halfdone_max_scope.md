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

1. 导出 Dataset（勾选 materialize，尽量多 case）
2. 打开「AI训练中心」，填 Dataset ID，开始训练（默认 **20 epoch / 320² / 2.5D radius=1**）
3. 任务完成后自动 `register_model(backend=platform_unet)`
4. 在「AI推理中心」选用该模型预测（推理含 3D 填洞 + 最大连通域后处理）

CLI：

```bash
python ai/train.py --dataset-id Dataset0001 --model-id ModelUNet0001 --epochs 20 --image-size 320 --context-radius 1
```

说明：平台模型是 **2.5D 切片 U-Net**（邻层上下文），正式高精度请继续用 TotalSeg / nnUNet。旧版纯 2D checkpoint 仍可推理；新训模型需重新训练才能获得 2.5D 收益。

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
