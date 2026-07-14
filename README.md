# C Group Medical Annotation Platform

C 组医学影像标注与数据管理平台（东北大学软件学院企业项目实训）。

面向 CT 等医学影像的上传、二维多标签标注、三维可视化与手势交互、AI 辅助分割写回、版本审核与 Dataset 导出。本仓库包含平台后端、标注前端、AI 推理/训练脚本与设计文档。

> **说明**：本项目为教学实训工程系统，不是已取证的医疗器械软件；「模拟手术」用于三维交互与 ROI 数据闭环演示，不能替代临床手术规划。

---

## 功能概览

| 模块 | 能力 |
|------|------|
| 认证与权限 | JWT 登录；标注员 / 审核员 / 管理员角色隔离 |
| 病例与影像 | 病例列表、NIfTI/DICOM 等上传、切片浏览 |
| 二维标注 | 画笔 / 橡皮 / 多标签、撤销重做、版本保存 |
| 三维与 MPR | VTK.js / WebGL2 体渲染、轴位/冠状/矢状联动、MIP/MinIP |
| 手势交互 | MediaPipe Hands（摄像头）：旋转、缩放、点选器官 |
| 模拟手术 | 选器官 → 确认长方体 ROI → 切割 → 结果入库（含器官字段） |
| AI 预测 | TotalSegmentator / nnU-Net / 平台 U-Net 等写回 `v2_ai` |
| DeepEdit | 正点/负点精修（独立服务 `:8010`，失败可降级） |
| 审核工作流 | 提交 → 驳回/通过 → `final` 版本 |
| 数据导出 | Dataset materialize、manifest，供训练读取 |
| 系统测试 | HTTP 自动化回归 + 人工 UI 检查表 |

---

## 仓库结构

```text
label_platform/
├── backend/          # FastAPI 后端（API、鉴权、Mask/手术/导出）
├── frontend/         # 主前端（原生 HTML/CSS/JS，功能最全，推荐演示）
├── web/              # 备选前端（React + Vite）
├── ai/               # 推理/训练脚本与 DeepEdit 服务
├── database/         # schema.sql；运行时生成 app.db（不入 Git）
├── dataset/          # 影像/标签/划分/导出目录约定
├── models/           # 本地权重说明（权重文件不入 Git）
├── scripts/          # 初始化、冒烟、系统测试、再训脚本
├── tests/system/     # 系统测试用例
├── docs/             # 设计文档、联调与测试说明
├── requirements.txt
└── .env.example
```

**端口约定**

| 服务 | 端口 |
|------|------|
| 主后端 + Legacy 前端 | `8000` |
| DeepEdit 推理服务（可选） | `8010` |
| React 开发服务器（可选） | `5173` |

---

## 环境要求

- **Python** 3.10+（推荐 3.11）
- **浏览器** Chrome / Edge（三维与摄像头手势）
- **可选**：Node.js 18+（仅当使用 `web/` React 前端）
- **可选**：已安装 TotalSegmentator / nnU-Net 的独立 Python 环境（AI 高精度路径）
- **摄像头**（可选）：手势功能需要

大体积影像、模型权重、真实病人数据**不要**提交到 Git。仓库只保留代码、文档、配置与小样例说明。

---

## 快速开始（最小可运行）

在项目根目录执行：

```bash
# 1. 创建虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 按需编辑 .env（默认即可先跑通平台主路径）

# 4. （可选）初始化 SQLite；后端启动时也会自动 ensure schema
python scripts/init_sqlite.py

# 5. 启动主后端（同时托管 frontend/）
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000/
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/api/health
```

### 演示账号（启动时自动种子写入）

| 用户名 | 密码 | 角色 |
|--------|------|------|
| `annotator` | `annotator123` | 标注员 |
| `reviewer` | `reviewer123` | 审核员 |
| `admin` | `admin123` | 管理员 |

> 仅用于本地联调。正式环境请修改密码，并更换 `.env` 中的 `JWT_SECRET`。

---

## 部署与配置

### 1. 环境变量

从模板复制后按需填写：

```bash
cp .env.example .env
```

常用项：

| 变量 | 含义 |
|------|------|
| `JWT_SECRET` | JWT 密钥（生产必须修改） |
| `JWT_EXPIRE_HOURS` | Token 有效期，默认 24 |
| `DEEPEDIT_SERVICE_URL` | DeepEdit 服务地址，默认 `http://127.0.0.1:8010` |
| `DEEPEDIT_MODEL_PATH` | DeepEdit 权重路径 |
| `USE_REACT_FRONTEND` | 设为 `1` 时优先托管 `web/dist/` |
| `TOTALSEG_PYTHON` | 可 `import totalsegmentator` 的 Python 解释器 |
| `TOTALSEG_DEVICE` / `TOTALSEG_FAST` | TotalSeg 设备与 fast 模式 |
| `SPLEEN_NNUNET_*` / `ORGANS_NNUNET_*` | nnU-Net 本地环境（可选） |

后端启动时会自动加载项目根目录 `.env`。`.env` 已在 `.gitignore` 中，请勿提交。

### 2. 数据库

- Schema：`database/schema.sql`
- 运行库：`database/app.db`（本地生成，不入 Git）
- 启动时自动 `ensure_*_schema`；也可手动：

```bash
python scripts/init_sqlite.py
```

### 3. 数据与病例

仓库**不包含**大体积 CT。本地需要自行准备多层 NIfTI/DICOM，或通过平台「上传」导入。

三维 / 手势 / TotalSeg 建议使用**多层**体数据（推荐深度 ≥ 8，演示常用约百层级 CT）。单层序列无法可靠做 3D，手势入口会拦截。

可用脚本从本机样例导入（路径按你机器调整）：

```bash
# 示例：按 docs / scripts 说明导入本地病例
python scripts/import_local_cases.py --help
```

### 4. 模型权重（可选）

权重放在 `models/` 下且**不要**提交 Git。说明见：

- [`models/README.md`](models/README.md)
- DeepEdit 交付说明：`deliverables/deepedit_for_person_a/`

无 DeepEdit 权重时，服务仍可启动，但 `/infer` 可能失败；平台侧可降级，不阻断基本标注。

---

## 启动方式详解

### A. 推荐：主后端 + Legacy 前端（一份进程）

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000/
```

`frontend/` 由 FastAPI 静态托管，包含三维、手势、模拟手术等完整演示能力。

### B. 可选：DeepEdit 精修服务

另开终端：

```bash
# 先将权重放到 models/deepedit/，并确认 .env 中路径正确
bash scripts/start_deepedit.sh
# 等价：python -m uvicorn ai.deepedit_service:app --host 127.0.0.1 --port 8010
```

检查：

```bash
curl -s http://127.0.0.1:8010/health
```

若 `8010` 被占用，可改用 `8011`，并同步修改 `.env` 中 `DEEPEDIT_SERVICE_URL`。

### C. 可选：React 前端开发模式

```bash
# 终端 1：后端
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000

# 终端 2：Vite
cd web
npm install
npm run dev
# 打开 http://127.0.0.1:5173 （API 已代理到 :8000）
```

生产构建并由后端托管：

```bash
cd web && npm run build
USE_REACT_FRONTEND=1 uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

> 答辩演示 3D / 手势 / 手术时，优先使用 **Legacy `frontend/` @ :8000**。

### D. 可选：TotalSegmentator / nnU-Net

1. 在独立环境安装 TotalSegmentator 或配置 nnU-Net 结果目录  
2. 在 `.env` 填写 `TOTALSEG_PYTHON` 或 `SPLEEN_NNUNET_*` / `ORGANS_NNUNET_*`  
3. 重启主后端，在标注台选择对应模型后点击 AI 预测  

更多联调步骤见：

- [`docs/10_spleen_ai_predict.md`](docs/10_spleen_ai_predict.md)
- [`docs/15_organ_ai_predict.md`](docs/15_organ_ai_predict.md)
- [`docs/13_person_b_joint_debug_checklist.md`](docs/13_person_b_joint_debug_checklist.md)

---

## 使用指南（功能演示路径）

以下以 **Legacy 前端** `http://127.0.0.1:8000/` 为准。操作前建议**强制刷新**浏览器，避免旧 JS 缓存。

### 1. 登录与角色

1. 打开首页，使用 `annotator / annotator123` 登录  
2. 切换账号验证权限：审核接口仅 `reviewer` / `admin` 可写  

### 2. 病例与上传

1. 在病例中心查看已有病例，或上传 NIfTI / DICOM 包  
2. 打开病例进入标注工作台，确认切片可滚动浏览  

### 3. 二维标注与版本

1. 选择标签（器官 label）  
2. 使用画笔 / 橡皮勾画，保存 Mask  
3. 在版本面板查看 `manual` / `ai` / `fusion` 等来源  
4. 可用对比查看版本间 Dice/IoU（粗评，不能替代人工审核）  

### 4. AI 预测

1. 在模型列表选择后端（如 `totalseg_organs` 或已注册的 nnU-Net）  
2. 点击预测；成功则写回 AI mask，失败应给出明确原因（不允许静默伪成功）  
3. 检查：`GET /api/ai/health`  

### 5. DeepEdit 精修（可选）

1. 确保 `:8010` 服务可用  
2. 在影像上放置正/负引导点并运行精修  
3. 预览后 promote 到融合版本（按界面提示操作）  

### 6. 三维、MPR 与手势

1. 打开**多层**病例（单层会被手势预检拦截）  
2. 进入 3D 视图：旋转观察、切换 MPR、必要时 MIP/MinIP  
3. 开启摄像头手势：双手控制旋转/缩放，点选手势聚焦器官  
4. 手势面板位于 3D 与 MPR 之间的 dock，避免遮挡体数据  

### 7. 模拟手术 ROI

1. 在 3D 中选中目标器官  
2. 确认长方体 ROI 大小（未确认前不可切割）  
3. 进入切割；收刀后保留刀痕面  
4. 保存：写入 `surgery_results`（含 `organ_name` / `organ_display_name` / `organ_color` 等）  

### 8. 审核与导出

1. 标注员提交病例  
2. 审核员登录：通过或驳回（驳回后可再编辑）  
3. 导出 Dataset（可 materialize 多类标签与 manifest），供训练管线读取  

### 推荐演示数据

- 优先多层 CT（约百层级）做 3D / 手势 / TotalSeg  
- 单层序列仅适合测「预检拦截」负例  

---

## 系统测试

**前提**：主后端已在 `127.0.0.1:8000` 运行。

```bash
bash scripts/run_system_tests.sh
```

- 报告：`docs/report/system_test_report.md`  
- 默认会跑功能 / 权限 / 工作流 / 手术 ROI 等；长耗时 AI/训练可用环境变量控制：

```bash
SYSTEM_TEST_RUN_HEAVY=0 bash scripts/run_system_tests.sh   # 跳过重测试
SYSTEM_TEST_BASE_URL=http://127.0.0.1:8000 bash scripts/run_system_tests.sh
```

浏览器三维与摄像头手感见人工表：[`docs/18_manual_ui_checklist.md`](docs/18_manual_ui_checklist.md)。

常用冒烟脚本：

```bash
python scripts/smoke_deepedit_infer.py
python scripts/smoke_spleen_predict.py --help
python scripts/smoke_organ_predict.py --help
```

---

## 常见问题

**Q: 打开页面是空白或按钮无反应？**  
强制刷新（Ctrl/Cmd+Shift+R）。确认访问的是 `http://127.0.0.1:8000/` 且后端日志无报错。

**Q: 三维 / 手势提示层数不足？**  
换多层 CT。单层 DICOM 不能支撑可靠 3D 与手势。

**Q: AI 预测失败？**  
先看 `/api/ai/health` 与后端日志。TotalSeg 需正确配置 `TOTALSEG_PYTHON`；无模型时应返回明确错误，而不是假 Mask。

**Q: DeepEdit 连不上？**  
确认 `:8010` 在听，且 `.env` 中 `DEEPEDIT_SERVICE_URL` 一致。

**Q: 端口被占用？**  
更换端口启动，并同步前端代理 / DeepEdit URL：

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

**Q: React 与 Legacy 哪个为准？**  
平台完整演示（3D/手势/手术）以 **Legacy `frontend/`** 为准；`web/` 为 React 备选实现。

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [`docs/01_data_flow_file_naming_standard.md`](docs/01_data_flow_file_naming_standard.md) | 数据流与命名 |
| [`docs/03_database_er_design.md`](docs/03_database_er_design.md) | 数据库 ER |
| [`docs/04_api_design.md`](docs/04_api_design.md) | API 契约与账号 |
| [`docs/05_platform_prototype.md`](docs/05_platform_prototype.md) | UI 原型 |
| [`docs/06_github_workflow.md`](docs/06_github_workflow.md) | Git 协作 |
| [`docs/07_person_b_ai_framework.md`](docs/07_person_b_ai_framework.md) | AI 框架 |
| [`docs/13_person_b_joint_debug_checklist.md`](docs/13_person_b_joint_debug_checklist.md) | 联调清单 |
| [`docs/16_hitl_fusion_loop.md`](docs/16_hitl_fusion_loop.md) | 人机闭环再训 |
| [`docs/17_system_test_plan.md`](docs/17_system_test_plan.md) | 系统测试计划 |
| [`docs/18_manual_ui_checklist.md`](docs/18_manual_ui_checklist.md) | 人工 UI 检查 |
| [`backend/README.md`](backend/README.md) | 后端说明 |
| [`web/README.md`](web/README.md) | React 前端说明 |
| [`models/README.md`](models/README.md) | 权重布局 |

---

## GitHub 提交规范（重要）

**不要提交**：

- `.env`、密钥、账号密码文件  
- `*.pth` / `*.pt` / 大模型目录  
- 大 CT、DICOM、NIfTI、NRRD、Mask、ZIP  
- `database/app.db` 等本地运行库  

**可以提交**：代码、文档、`.env.example`、小 manifest、目录占位 `.gitkeep`。

建议分支：`feature-*` → `dev` → `main`（详见 `docs/06_github_workflow.md`）。

---

## 许可证与声明

本仓库用于东北大学软件学院企业项目实训（C 组）。若无公开样例数据，请遵守对应数据集原始许可。使用本平台产生的标注与模型结果仅供教学与研究演示，不用于临床诊断或手术决策。
