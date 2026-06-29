# Label Platform

C 组医学影像标注与数据管理平台。

## 当前 Day1 标准

第一份开发契约见：

- [docs/01_data_flow_file_naming_standard.md](docs/01_data_flow_file_naming_standard.md)
- [docs/02_example_data_analysis.md](docs/02_example_data_analysis.md)
- [docs/03_database_er_design.md](docs/03_database_er_design.md)
- [docs/04_api_design.md](docs/04_api_design.md)
- [docs/05_platform_prototype.md](docs/05_platform_prototype.md)
- [docs/06_github_workflow.md](docs/06_github_workflow.md)

这些文档已经明确：

- 整个系统的数据流。
- 项目顶层目录结构。
- `dataset/` 数据目录规范。
- Case、Image、Annotation、Mask、Dataset、Model 的统一命名。
- `v1_manual`、`v2_ai`、`v3_fusion`、`final` 版本规则。
- 数据集发布与导出规则。
- example_data 样例数据分析。
- 八张核心表的 ER 图。
- Vue 和 AI 后续调用的 API 契约。
- 第一版平台三栏式 UI 原型。
- GitHub 分支和协作规范。

## 项目结构

```text
label_platform/
  backend/
  frontend/
  ai/
  dataset/
    raw/
    images/
    labels/
    splits/
  database/
  docs/
    reference/
  models/
  requirements.txt
  .gitignore
```

## Day1 原则

不要在数据标准、API 契约、数据库 ER 设计、Dataset 结构没有统一前，直接开始大量写前端、后端或 U-Net 训练代码。

## GitHub 注意事项

大 CT、DICOM、NIfTI、NRRD、Mask、`.pth` 模型权重和 PDF 资料不要提交到 GitHub。仓库只保存代码、小样例说明、配置和文档。

原始需求和规划文档已归档在 `docs/reference/`。
