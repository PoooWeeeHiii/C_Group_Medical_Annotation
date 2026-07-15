# 19. 模拟手术机器臂路径：坐标约定与 `robot_plan` Schema

> **声明**：本能力为教学/研究演示。导出的路径**不能**直接用于临床导航或真机手术控制。占位字段需在真实 OR 标定与安全审核后替换。

## 坐标链

```
UVW[0,1]  →  IJK  →  Patient_LPS(mm)  →  Patient_RAS(mm)  →  RobotBase(mm)
```

| 帧 | 含义 | 单位 |
|----|------|------|
| UVW | 前端体渲染归一化坐标，与 mesh 顶点一致 | 无量纲 `[0,1]` |
| IJK | 体素连续索引（`ijk = uvw * (N-1)`） | index |
| Patient_LPS | DICOM / SimpleITK 常用患者系 Left-Posterior-Superior | **mm**（主坐标系） |
| Patient_RAS | 部分导航系统常用 Right-Anterior-Superior | mm（并行存储） |
| RobotBase | 机器臂基座系 | mm（默认 = LPS，模拟刚体） |

### LPS → RAS

```
RAS = [-LPS_x, -LPS_y, LPS_z]
```

即对角阵 `diag(-1, -1, 1)`。`robot_plan.coordinate_frames.lps_to_ras` 中有相同说明。

### IJK → LPS

使用影像 `spacing` / `origin` / `direction`（SimpleITK 约定）：

```
LPS = origin + direction_3x3 @ (ijk ⊙ spacing)
```

等价 4×4：`coordinate_frames.affine_ijk_to_lps_4x4`。

### 模拟配准 RobotBase ← LPS

- 默认：`T_robot_from_lps = I`（单位阵）
- 覆盖：环境变量 `ROBOT_T_LPS`（16 个浮点数，行优先 4×4）
- 版本：`ROBOT_CALIBRATION_VERSION`（默认 `sim-calib-v1`）
- 真实术中配准就绪后，用刚体/非刚体结果替换 `registration.T_robot_from_lps_4x4`，并更新 `calibration_version` / `registered_at`

## 保存与导出 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/surgery_results` | 保存 ROI，响应含 `robot_plan` |
| GET | `/api/surgery_results/{result_id}/robot_path` | 下载完整路径 JSON（可 `?rebuild=true`） |

请求可选字段：

- `volume_meta`：前端缓存的 spacing/origin/direction（服务端也会从影像重读）
- `cut_timestamps`：每刀 `started_at` / `ended_at`
- `robot_plan_overrides`：工具型号、速度/力上限、进刀抬升等

## `robot_plan` 顶层结构（schema_version `1.0.0`）

| 字段 | 内容 |
|------|------|
| `coordinate_frames` | spacing/origin/direction、affine、LPS/RAS 约定 |
| `registration` | 模拟刚体 `T_robot_from_lps`、标定版本 |
| `tool_paths[]` | 有序刀口：entry / waypoints / exit、TCP 四元数与旋转矩阵、depth/thickness_mm、运动约束占位 |
| `anatomy_safety` | ROI AABB（LPS+RAS）、器官 mesh 引用、禁入/端口/关节/碰撞**占位** |
| `repro_meta` | 切割顺序、工具型号、mask_id、标定版本、时间戳 |
| `status` | `ok` 或 `incomplete`（缺体积元数据时不抛 500） |

### 路径生成规则（当前实现）

1. 每张刀痕 `polygon`（UVW）→ LPS 折线轨迹；无 polygon 时用平面∩长方体
2. 入口/退刀：首末点沿接近方向外抬 `approach_offset_mm`（默认 10）
3. TCP：Z = 切除侧法向，X 沿多边形第一边，Y = Z×X；姿态同时存四元数 `xyzw` 与 3×3
4. `thickness_mm` 由 `knife_radius` 与最小 spacing 换算；`multi_pass=false`

### 占位字段（`status: "placeholder"`）

需真实硬件/规划器替换：

- `constraints.force_limit_n` / `v_max` / `a_max`
- `anatomy_safety.keep_out` / `ports` / `joint_limits` / `collision`
- 非单位阵的术中配准矩阵

器官表面网格**不内嵌**大二进制，仅引用 `mask_id` 与 `/api/mask/{id}/surface-mesh`。

## UI

模拟手术面板：

1. **保存手术ROI到数据库** — 入库并自动下载 `{result_id}_robot_path.json`
2. **导出机器臂路径 JSON** — 已保存则按 `result_id` 拉取；未保存则先触发保存

## 与 Dataset 导出的区别

| | 手术 `robot_plan` | Dataset `/api/export` |
|--|------------------|------------------------|
| 用途 | 三维切割意图 → 机器臂路径草案 | nnU-Net / 训练标签 |
| 坐标 | LPS/RAS mm + 模拟 RobotBase | 影像/mask 文件布局 |
