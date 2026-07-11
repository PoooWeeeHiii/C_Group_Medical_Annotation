# TotalSegmentator v2 → nnUNet 训练集准备

数据与权重都放在仓库外：`D:\hm_2_totalseg\`，不要提交到 Git。

## 你现在有什么

| 路径 | 状态 |
| --- | --- |
| `D:\hm_2_totalseg\raw_archives\Totalsegmentator_dataset_v201.zip` | 已下载（约 22GB） |
| `extracted/` | 解压后的原始病例（`sXXXX/ct.nii.gz` + `segmentations/`） |
| `nnUNet_raw/Dataset601_...` | 转换后的 nnUNet 训练集 |

官方划分（`meta.csv`）：

- train: 1082
- val: 57
- test: 89

## 推荐产物（本项目）

| Dataset ID | 文件夹 | 用途 |
| --- | --- | --- |
| **606** | `Dataset606_TotalSeg_Spleen` | **优先**：单标签脾，对接平台 AI |
| 601 | `Dataset601_TotalSeg_Organs` | 官方 organs 24 类（含 spleen/liver/kidney…） |
| 602–605 | Vertebrae / Cardiac / Muscles / Ribs | 官方其余 4 个 part 模型 |

## 一步步命令

在 nnUNet CPU 环境中执行：

```powershell
$py = "D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe"
cd D:\label_platform\C_Group_Medical_Annotation
$env:nnUNet_raw = "D:\hm_2_totalseg\nnUNet_raw"
$env:nnUNet_preprocessed = "D:\hm_2_totalseg\nnUNet_preprocessed"
$env:nnUNet_results = "D:\hm_2_totalseg\nnUNet_results"
```

### 1) 查看状态

```powershell
& $py -u scripts\prepare_totalseg_nnunet.py status
```

### 2) 解压 zip（只需一次，耗时长）

```powershell
& $py -u scripts\prepare_totalseg_nnunet.py extract
```

### 3) 先做小规模冒烟（可不解压，直接读 zip）

```powershell
& $py -u scripts\prepare_totalseg_nnunet.py convert --from-zip --parts spleen --limit 3 --overwrite
```

### 4) 全量转换（建议先 spleen，再 organs）

```powershell
# 解压完成后：
& $py -u scripts\prepare_totalseg_nnunet.py convert --parts spleen --overwrite
& $py -u scripts\prepare_totalseg_nnunet.py convert --parts organs
# 如需官方全部 5 个 part：
# & $py -u scripts\prepare_totalseg_nnunet.py convert --parts all
```

### 5) 预处理 + 训练（以后自训）

```powershell
nnUNetv2_plan_and_preprocess -d 606 -pl ExperimentPlanner -c 3d_fullres -np 2
nnUNetv2_train 606 3d_fullres 0 -tr nnUNetTrainerNoMirroring
```

organs 同理，把 `606` 换成 `601`。

训练完成后，把 `nnUNet_results` 下的 checkpoint 接到平台 `ai/spleen_nnunet.py` / `SPLEEN_MODEL_DIR` 即可。

## 磁盘与时间预期

| 步骤 | 大约占用 / 耗时 |
| --- | --- |
| zip | 22GB（已有） |
| 解压 | 额外约 40–80GB+，数十分钟到数小时 |
| 转 spleen | 相对快（每例只合并 1 个 mask） |
| 转 organs | 慢（每例合并 24 个 mask） |
| `plan_and_preprocess` | 很大，视配置而定 |
| 训练 | 数天级（官方说明） |

## 与平台的关系

```text
Totalsegmentator zip
  -> extract / convert
  -> nnUNet_raw/Dataset606_TotalSeg_Spleen
  -> preprocess + train
  -> checkpoint_best.pth
  -> 平台 POST /api/ai/predict (label=spleen)
```

当前平台已在用你本地的 `Dataset506_Spleen` 权重。TotalSeg 转换是为**以后自训/扩展多器官**做准备，不是立刻替换现有预测。

## 脚本位置

- `scripts/prepare_totalseg_nnunet.py`
