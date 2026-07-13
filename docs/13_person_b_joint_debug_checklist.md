# Person B：1–2 天联调与能力缺口收口清单

以 **Person A 端口为准：DeepEdit = `8010`**。后端默认 `8000`，前端 legacy `frontend/` 或 React `web/`。

## 已对齐（本机）

| 项 | 状态 |
|----|------|
| `feature-b` 已 merge 最新 `feature-a` | ✅ |
| DeepEdit 服务 `http://127.0.0.1:8010/health` | ✅ `model_loaded=true` |
| 权重 | `models/deepedit/deepedit_unet.pth`（交付包同目录） |
| 多器官自动标注 | TotalSeg + Plan A `Model0010`–`Model0013` |
| 人机闭环脚本 | `run_hitl_retrain` + fusion→DeepEdit/nnUNet；`docs/16` | ✅ |
| React DeepEdit / promote | `AnnotationPage` 正点/负点 + refine + v3_fusion | ✅ |

## Day1（联调日）

1. 确认 `.env` 含：
   ```env
   DEEPEDIT_SERVICE_URL=http://127.0.0.1:8010
   ```
2. 启动 DeepEdit（若未开）：
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\start_deepedit.ps1
   curl.exe -s http://127.0.0.1:8010/health
   ```
3. 启动后端：
   ```powershell
   D:\anaconda\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
4. 打开前端（legacy）：浏览器访问 `http://127.0.0.1:8000/`  
   或 React：`cd web; npm run dev`
5. 平台验收：
   - AI 预测选 `totalseg_organs` 或 `Model0011` 等 → 出 `v2_ai`
   - DeepEdit：欠分割正点 / 过分割负点 → 出 `v3_preview` / `v3_fusion`
6. 烟测：
   ```powershell
   D:\anaconda\python.exe scripts\smoke_deepedit_infer.py
   ```

## Day2（能力缺口）

1. **多器官自动标注**：UI 选 `totalseg_organs` 或 Person B 自训 `Model0010`–`Model0013`。
2. **人机再训练**（有人工修正 mask 后）：
   ```powershell
   D:\anaconda\python.exe scripts\run_hitl_retrain.py --prepare-deepedit --prepare-nnunet
   D:\anaconda\python.exe scripts\run_hitl_retrain.py --prepare-deepedit --train-deepedit --epochs 10
   # 或无真实 fusion 时先冒烟：
   # D:\anaconda\python.exe scripts\run_hitl_retrain.py --seed-from-v2 --prepare-deepedit --prepare-nnunet
   # 重启 DeepEdit 服务加载新权重
   ```
   详见 `docs/16_hitl_fusion_loop.md`。
3. **脾 nnUNet**：本地默认 `3d_fullres`（`SPLEEN_*` 见 `.env`）；演示优先用 TotalSeg，脾专项可用 `Model0002`。
4. **交付**：权重走 `deliverables/deepedit_for_person_a/`（勿把 `.pth` 推 Git）；代码推 `feature-b`。

## Person A 对齐话术

- DeepEdit URL：**固定 8010**（忙则双方同时改 8011）
- 权重：`deepedit_unet.pth` + `config.json` → `models/deepedit/`
- 接口：已在 `ai/deepedit_service.py`，Person B 不改契约

## 指标速记

| 模型 | 指标 |
|------|------|
| DeepEdit（交付 8 例） | best val Dice ≈ **0.526** |
| 脾 nnUNet 3d_fullres | val Dice ≈ **0.707** |
| Exp-A TotalSeg | mean Dice ≈ **0.962**（3 例） |
