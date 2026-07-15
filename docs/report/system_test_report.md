# 系统测试报告（System Test Report）

- 生成时间：2026-07-14T13:21:52
- 被测环境：`http://127.0.0.1:8000`
- 结论：**PASS**
- 人工 UI 检查表：15/15 全部通过（2026-07-14）
- 用例总数：56
- 通过：54
- 失败：0
- 错误：0
- 跳过：2
- 通过率：96.43%
- 耗时：6.31s

## 1. 测试依据

- 计划文档：`docs/17_system_test_plan.md`
- 执行脚本：`scripts/run_system_tests.sh`
- 用例代码：`tests/system/test_system_api.py`

## 2. 测试类型覆盖

| 类型 | 覆盖说明 |
| --- | --- |
| 功能测试 | 健康检查、登录、病例/影像、Mask 读写、标签、模型、手术 ROI、上传导出 |
| 权限/安全负向 | 错密登录、无 token、越权 approve/users、路径穿越/注入样例 |
| 边界/异常 | 非法 cuboid、label_id<=0、不存在 case/image、未知 API |
| 工作流集成 | submit→reject→resubmit→approve；promote/rollback；图割/DeepEdit |
| AI/训练 | 模型就绪、可选实装预测、短训任务启停轮询 |
| 性能冒烟 | /api/health、/api/cases 延迟阈值 |
| 界面入口 | `/` 与关键 frontend 静态脚本可访问 |
| 人工 UI | 见 docs/18_manual_ui_checklist.md（手势/VTK/手术） |

## 3. 用例结果明细

| 用例 | 状态 | 耗时(s) |
| --- | --- | --- |
| `test_ST_AI_03_models_totalseg_ready_flag` | passed | 0.159 |
| `test_ST_AI_04_predict_with_registered_model` | skipped | 0.165 |
| `test_ST_TRAIN_01_list_jobs` | passed | 0.001 |
| `test_ST_TRAIN_02_start_short_job_if_dataset_available` | skipped | 2.998 |
| `test_ST_PERF_01_health_latency` | passed | 0.007 |
| `test_ST_PERF_02_cases_latency` | passed | 0.025 |
| `test_ST_SEC_01_path_traversal_case_id` | passed | 0.001 |
| `test_ST_SEC_02_sql_injection_like_case_id` | passed | 0.003 |
| `test_ST_SEC_03_unauth_write_mask` | passed | 0.019 |
| `test_ST_HEALTH_01_api_health` | passed | 0.001 |
| `test_ST_FE_01_frontend_index` | passed | 0.003 |
| `test_ST_FE_02_frontend_static_js` | passed | 0.004 |
| `test_ST_AUTH_01_login_roles[annotator-annotator123-annotator]` | passed | 0.013 |
| `test_ST_AUTH_01_login_roles[reviewer-reviewer123-reviewer]` | passed | 0.014 |
| `test_ST_AUTH_01_login_roles[admin-admin123-admin]` | passed | 0.015 |
| `test_ST_AUTH_02_login_wrong_password` | passed | 0.016 |
| `test_ST_AUTH_03_me_requires_token` | passed | 0.001 |
| `test_ST_AUTH_04_me_with_token` | passed | 0.004 |
| `test_ST_AUTH_05_annotator_cannot_list_users` | passed | 0.003 |
| `test_ST_AUTH_06_admin_can_list_users` | passed | 0.019 |
| `test_ST_AUTH_07_annotator_cannot_approve` | passed | 0.004 |
| `test_ST_CASE_01_list_cases` | passed | 0.027 |
| `test_ST_CASE_02_case_detail` | passed | 0.008 |
| `test_ST_CASE_03_case_not_found` | passed | 0.005 |
| `test_ST_IMG_01_image_detail` | passed | 0.004 |
| `test_ST_IMG_02_volume_meta` | passed | 0.004 |
| `test_ST_IMG_03_axial_slice_png` | passed | 0.022 |
| `test_ST_IMG_04_mpr_slice_png` | passed | 0.010 |
| `test_ST_IMG_05_projection_png` | passed | 0.020 |
| `test_ST_MASK_01_list_masks` | passed | 0.142 |
| `test_ST_MASK_02_mask_detail_if_present` | passed | 0.067 |
| `test_ST_MASK_03_surface_mesh_per_label_if_present` | passed | 0.070 |
| `test_ST_LABEL_01_list_labels` | passed | 0.009 |
| `test_ST_MODEL_01_list_models` | passed | 0.070 |
| `test_ST_AI_01_health` | passed | 0.029 |
| `test_ST_AI_02_predict_honest_behavior` | passed | 0.301 |
| `test_ST_SURG_01_save_roi_with_organ` | passed | 0.011 |
| `test_ST_SURG_02_list_by_case` | passed | 0.005 |
| `test_ST_SURG_03_get_by_id` | passed | 0.003 |
| `test_ST_SURG_04_reject_bad_cuboid` | passed | 0.008 |
| `test_ST_SURG_05_reject_non_positive_label` | passed | 0.012 |
| `test_ST_TASK_01_list_tasks` | passed | 0.021 |
| `test_ST_WF_01_review_queue_reviewer` | passed | 0.033 |
| `test_ST_WF_02_versions_list` | passed | 0.006 |
| `test_ST_NEG_01_unknown_api` | passed | 0.001 |
| `test_ST_NEG_02_image_not_found` | passed | 0.004 |
| `test_ST_UP_01_nifti_upload_creates_case` | passed | 0.297 |
| `test_ST_UP_02_uploaded_volume_readable` | passed | 0.013 |
| `test_ST_UP_03_multi_file_upload_field` | passed | 0.012 |
| `test_ST_EX_01_export_materialize` | passed | 0.142 |
| `test_ST_MASK_W_01_save_mask_json` | passed | 0.037 |
| `test_ST_MASK_W_02_update_mask` | passed | 0.028 |
| `test_ST_MASK_W_03_export_nifti_and_propagate` | passed | 0.192 |
| `test_ST_MASK_W_04_deepedit_honest_fallback` | passed | 0.740 |
| `test_ST_MASK_W_05_promote_and_rollback` | passed | 0.090 |
| `test_ST_WF_FULL_01_submit_reject_resubmit_approve` | passed | 0.324 |

## 4. 失败与错误详情

无。
## 5. 结论与建议

本轮系统测试通过，关键业务链路（鉴权、病例影像、手术 ROI 含器官信息、静态入口）可用。

后续建议：
1. 为上传/导出/审核状态机增加独立沙箱库，避免污染演示数据；
2. 补充浏览器端手势与三维交互的人工测试记录；
3. 将本脚本接入 CI（先保证 `/api/health` 服务就绪）。


## 6. 本轮补充说明

- 默认 `SYSTEM_TEST_RUN_HEAVY=0`：跳过长耗时 TotalSeg 实装预测与短训启动（可用 `SYSTEM_TEST_RUN_HEAVY=1` 开启）。
- 浏览器手势 / VTK / 手术三步：请按 `docs/18_manual_ui_checklist.md` 人工勾选。
- 前端语法门禁：`node --check` 对 `app.js` / `volume_viewer.js` / `hand_gesture.js` 通过。

