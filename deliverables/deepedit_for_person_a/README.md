# DeepEdit 权重交付包（Person B → Person A）

## 放哪里

把本目录内容复制到平台仓库：

```text
models/deepedit/
  deepedit_unet.pth      ← 本包权重
  config.json            ← 本包配置
```

大文件不要提交 Git，用网盘 / U 盘 / 内网传即可。

## 格式说明

| 项 | 值 |
|----|-----|
| 格式 | `monai_unet_checkpoint`（MONAI 3D UNet） |
| 输入 | 4 通道：`CT归一化 + 正点 + 负点 + 当前mask` |
| 输出 | 2 通道：背景 / 前景（取通道 1，再 threshold） |
| 空间 | 训练裁剪 `64×128×128`；推理由服务按原 CT 跑 |
| 支持 label | `heart` `liver` `spleen` `left_lung` `right_lung` `left_kidney` `right_kidney`（同一套二值权重） |

## 后端 .env（Person A）

```env
DEEPEDIT_SERVICE_URL=http://127.0.0.1:8010
DEEPEDIT_SERVICE_TIMEOUT_SECONDS=120
```

## 服务启动（Person B / 联调机）

```powershell
# 在仓库根目录
powershell -ExecutionPolicy Bypass -File scripts\start_deepedit.ps1

curl http://127.0.0.1:8010/health
```

期望：`model_loaded: true`。

## 训练指标（本包权重）

- 数据：MSD CT + TotalSeg 伪标签，**8 例 × 7 器官**（脾脏用 MSD 金标准覆盖）
- epoch：50；best val Dice：**0.526**（epoch 44）
- 分器官（最佳轮）：liver 0.725 / right_lung 0.626 / left_lung 0.613 / heart 0.513 / left_kidney 0.495 / right_kidney 0.361 / spleen 0.347

## 联调检查清单

1. [ ] `models/deepedit/deepedit_unet.pth` + `config.json` 已就位
2. [ ] DeepEdit 服务已启动，`GET /health` 成功
3. [ ] 后端 `DEEPEDIT_SERVICE_URL` 与端口一致（**8010**）
4. [ ] 前端 DeepEdit：欠分割加点 / 过分割加负点能出 `v3_*` mask

## 联系

权重由 **Person B（Feature B / DeepEdit）** 提供。接口契约已在 `feature-a` 的 `ai/deepedit_service.py`。
