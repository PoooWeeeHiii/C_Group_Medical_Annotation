# 系统测试计划（System Test Plan）

| 项 | 内容 |
| --- | --- |
| 项目 | C 组医学影像标注与数据管理平台 |
| 版本 | 与当前 `main` / `feature-a` 可运行代码一致 |
| 测试类型 | 系统测试（功能 / 权限 / 边界 / 接口集成） |
| 测试环境 | 本地 `uvicorn` @ `127.0.0.1:8000`，SQLite，legacy frontend |
| 执行方式 | `scripts/run_system_tests.sh`（pytest + 自动生成报告） |

## 1. 测试目标

验证平台在真实运行环境下，端到端关键业务是否满足需求：登录鉴权、病例与影像浏览、切片/体数据、Mask 查询、AI 健康与诚实失败、手术 ROI（含器官信息）入库与查询、审核权限边界、前端静态入口可用。

## 2. 范围

### 2.1 在测范围（In Scope）

- `/api/health`、前端首页
- 认证：`/api/auth/login`、`/api/me`、角色越权
- 病例：`/api/cases`、`/api/case/{id}`
- 影像：slice / volume / projection
- Mask 列表与详情（只读）以及写路径：`save_mask` / update / `export_mask_nifti` / `label_propagate` / promote / rollback / DeepEdit
- 上传 NIfTI、多文件 `files` 字段；`/api/export` materialize
- 审核闭环：submit → reject → resubmit → approve（独立 SYSTEM_TEST 病例）
- AI：health、模型列表、可选 TotalSeg 实装预测（`SYSTEM_TEST_RUN_HEAVY`）
- 训练：任务列表、短 epoch 启动与状态轮询（可选重测试）
- 轻量性能：health/cases 延迟阈值；基础安全负向（路径穿越/注入样例）
- 手术 ROI：保存、按 case/image/result 查询，校验器官字段
- 标签列表、模型列表、任务列表（可读性）
- 静态资源：`/frontend/app.js` 等可访问性
- 浏览器手势/VTK/手术：**人工检查表** `docs/18_manual_ui_checklist.md`

### 2.2 不在测范围（Out of Scope）

- 完整 GPU 长训与精度对标金标准
- 摄像头手势的自动 E2E（依赖人工表）
- 真实病人隐私合规审计、正式渗透测试、多浏览器矩阵自动化
- 大规模压测（本轮仅冒烟延迟阈值）

## 3. 通过准则

- 阻断级（Blocker）用例全部通过
- 重要级（Major）用例通过率 ≥ 95%
- 报告中对失败项给出复现步骤与影响说明

## 4. 用例编号规则

`ST-<模块>-<序号>`，例如 `ST-AUTH-01`。

## 5. 风险与依赖

- 依赖本地后端已启动；未启动时用例直接失败并提示
- 手术保存会向演示库写入测试记录（note 含 `[SYSTEM_TEST]` 标记）
- AI 环境不同会导致 predict 结果“失败/成功”分支不同；用例对“诚实失败”与“成功写回”均接受，但禁止静默伪成功无诊断信息
