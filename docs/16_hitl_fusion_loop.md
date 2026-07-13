# Person B — 人机闭环与 Fusion 再训

「Fusion」在本平台 = **人工确认后的精修 mask 版本**（`v3_fusion`），不是独立多模型 voxel 融合服务。

## 闭环图

```text
AI 初标 (v2_ai)
    → DeepEdit / 图割点击修正 (v3_preview)
    → 确认 promote (v3_fusion 或 final)
    → 收割脚本
         ├─ prepare_deepedit_from_fusion.py  → DeepEdit few-shot 再训
         └─ prepare_organs_nnunet_from_fusion.py → Dataset520–523 HITL nnUNet
    → 新权重再用于自动标注
```

## 在线（平台）

1. 启动 DeepEdit：`scripts\start_deepedit.ps1`（`:8010`）
2. 后端 `:8000`；legacy 前端或 React 标注台
3. AI 预测（脾 `Model0002` / 器官 `Model0010–0013` / `totalseg_*`）→ `v2_ai`
4. 正点 / 负点 → **DeepEdit 神经网络** → `v3_preview`
5. **确认 v3_fusion**（`POST /api/mask/{id}/promote`）

React 标注台已提供 DeepEdit 正点/负点、refine、promote 按钮（与 legacy 对齐）。

## 离线再训（Person B）

### 一键编排

```powershell
# 无真实 fusion 时，可先用 v2_ai 冒烟种子（仅测管线）
D:\anaconda\python.exe scripts\run_hitl_retrain.py --seed-from-v2 --prepare-deepedit --prepare-nnunet

# 有真实 v3_fusion 后
D:\anaconda\python.exe scripts\run_hitl_retrain.py --prepare-deepedit --prepare-nnunet

# DeepEdit few-shot 续训（较慢）
D:\anaconda\python.exe scripts\run_hitl_retrain.py --prepare-deepedit --train-deepedit --epochs 10
```

### 分步

| 步骤 | 脚本 |
|------|------|
| （可选）种子 | `scripts/seed_v3_fusion_from_v2.py` |
| → DeepEdit 数据 | `scripts/prepare_deepedit_from_fusion.py` |
| → DeepEdit 训练 | `scripts/train_deepedit.py --manifest ... --resume` |
| → nnUNet HITL 集 | `scripts/prepare_organs_nnunet_from_fusion.py` |
| 计划/训练 | `nnUNetv2_plan_and_preprocess -d 520 521 522 523` 后自行 train |

HITL nnUNet 使用 **Dataset520–523**，不覆盖 Plan A 的 510–513。

## 诚实边界

- `seed_v3_fusion_from_v2` **不是**真人工修正，只用于脚本冒烟。
- 报告应区分：Plan A 伪标自训 vs HITL 精修再训 vs MSD 脾金标。
- 权重勿提交 Git；DeepEdit 热加载依赖 checkpoint mtime（或重启服务）。

## 相关文档

- 联调清单：`docs/13_person_b_joint_debug_checklist.md`
- 器官初标：`docs/15_organ_ai_predict.md`
- Plan A：`docs/14_planA_organs_nnunet.md`
- API：`docs/04_api_design.md`（DeepEdit / promote）
