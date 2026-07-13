# Plan A：心/肝/肺/肾 nnUNet `3d_fullres` 自训

目标：用 DeepEdit 同源伪标签（MSD CT + TotalSeg）体现多器官 nnUNet 自训工作量，**非**追求超过官方 TotalSeg 的精度。

## 数据集

| 器官 | Dataset ID | 标签来源 |
|------|------------|----------|
| heart | 510 | `heart` |
| liver | 511 | `liver` |
| lung | 512 | `left_lung \| right_lung` |
| kidney | 513 | `left_kidney \| right_kidney` |

- 根目录（本机，不进 Git）：`E:\lxy\hm_2_organs_nnunet\`
- 训练例数：**12**（伪标签；验证为 nnUNet fold 0）
- 配置：`3d_fullres`，`batch_size=1`（RTX 4060 8GB）
- 训练器：`nnUNetTrainer_100epochs`

## 100 epoch 结果（已完成）

以各 fold 训练日志末尾 **Mean Validation Dice** 为准：

| 器官 | Dataset | 耗时 | Mean Validation Dice | 状态 |
|------|---------|------|----------------------|------|
| 肺 | 512 | ≈ 2.5 h | **0.950** | ok |
| 肝 | 511 | ≈ 2.4 h | **0.921** | ok |
| 肾 | 513 | ≈ 2.5 h | **0.813** | ok |
| 心 | 510 | ≈ 2.5 h | **0.613** | ok |

合计约 **10 小时**（`PLAN_A_100EP_EXIT=0`）。

权重路径（本地）：

```text
E:\lxy\hm_2_organs_nnunet\nnUNet_results\
  Dataset510_DeepEdit_Heart\nnUNetTrainer_100epochs__nnUNetPlans__3d_fullres\fold_0\checkpoint_best.pth
  Dataset511_DeepEdit_Liver\...\checkpoint_best.pth
  Dataset512_DeepEdit_Lung\...\checkpoint_best.pth
  Dataset513_DeepEdit_Kidney\...\checkpoint_best.pth
```

机器可读摘要：`docs/planA_train_summary.json`（解析值为训练过程峰值，报告请以上表 Mean Validation Dice 为准）。

## 命令

```powershell
$env:Path = "D:\anaconda;D:\anaconda\Scripts;" + $env:Path

# 1) 伪标签 → nnUNet raw
D:\anaconda\python.exe scripts\prepare_organs_nnunet_from_deepedit.py --limit 12

# 2) 预处理 + 100 epoch（已预处理器官可 --auto-skip-preprocess）
D:\anaconda\python.exe -u scripts\run_organs_nnunet_planA.py --skip-convert --auto-skip-preprocess --epochs 100
```

脚本：

- `scripts/prepare_organs_nnunet_from_deepedit.py`
- `scripts/run_organs_nnunet_planA.py`

日志：`E:\lxy\hm_2_organs_nnunet\logs\planA_runner_100ep.log`

## 报告写法

- 脾：`Dataset506` 完整 `3d_fullres` 100 epoch（主自训结果，MSD 金标）
- 心/肝/肺/肾：同流程扩展 100 epoch（工作量 + 管线可扩展性）
- 线上自动标注仍优先 **TotalSeg**；本结果证明「伪标可驱动多器官自训」
- 诚实说明：高分部分来自拟合 TotalSeg 伪标，非独立金标准测试集

## 解读

- 肺/肝最好，肾中上，心最弱（结构更难、伪标噪声更大）
- 与 DeepEdit 交互修正、人机闭环互补：nnUNet 负责初标扩展，DeepEdit 负责点击精修

## 平台推理接入（已接线）

模型 ID（前端可选）：

| model_id | Person B 别名 | label |
|----------|---------------|-------|
| `heart_nnunet_ds510` | `Model0010` | heart |
| `liver_nnunet_ds511` | `Model0011` | liver |
| `lung_nnunet_ds512` | `Model0012` | lung |
| `kidney_nnunet_ds513` | `Model0013` | kidney |

实现：`ai/organ_nnunet.py` ← `ai_service`（`backend=organ_nnunet_local`）。  
说明：`models/organ_nnunet.md`；联调：`docs/15_organ_ai_predict.md`。

```powershell
D:\anaconda\python.exe -u scripts\smoke_organ_predict.py --organ all --case spleen_10 --register
D:\anaconda\python.exe -u scripts\e2e_organ_api.py --organ all
```
