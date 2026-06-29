# Example Data 分析记录

## 1. 数据概况

本次上传的样例数据位于：

```text
example_data/
```

当前包含两类医学影像数据：

- DICOM 病例目录：`LUNG1-001`、`LUNG1-002`、`LUNG1-003`
- NRRD 压缩包：`patient1.zip`，内部包含 `p1.nrrd` 和 `p1-label.nrrd`

## 2. DICOM 数据结构

样例 DICOM 数据按病例、Study、Series 分层：

```text
example_data/
  LUNG1-001/
    09-18-2008-StudyID-NA-69331/
      0.000000-NA-82046/
      3.000000-NA-78236/
      300.000000-Segmentation-9.554/
  LUNG1-002/
    01-01-2014-StudyID-NA-85095/
      1.000000-NA-61228/
      4.000000-NA-45931/
      300.000000-Segmentation-5.421/
  LUNG1-003/
    01-01-2014-StudyID-NA-34270/
      1.000000-NA-28595/
      4.000000-NA-22712/
      300.000000-Segmentation-2.316/
```

发现一个需要注意的问题：

```text
example_data/LUNG1-001/.../0.000000-NA-82046/LUNG1-002/...
```

`LUNG1-001` 的 CT 序列目录下嵌套了一份 `LUNG1-002` 数据，疑似解压或拷贝时放错目录。正式导入时应以 DICOM `PatientID` 和顶层病例目录双重校验，避免把 `LUNG1-002` 错归到 `LUNG1-001`。

## 3. DICOM 序列摘要

| 路径 | 文件数 | PatientID | Modality | 说明 | 尺寸 | Pixel Spacing | Slice Thickness |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| `LUNG1-001/.../0.000000-NA-82046` | 134 | `LUNG1-001` | CT | CT 影像序列 | 512 x 512 | 0.9765625 x 0.9765625 | 3 |
| `LUNG1-001/.../3.000000-NA-78236` | 1 | `LUNG1-001` | RTSTRUCT | 结构化轮廓标注 | - | - | - |
| `LUNG1-001/.../300.000000-Segmentation-9.554` | 1 | - | SEG | DICOM segmentation mask | - | - | - |
| `LUNG1-002/.../1.000000-NA-61228` | 111 | `LUNG1-002` | CT | CT 影像序列 | 512 x 512 | 0.9770 x 0.9770 | 3.00000 |
| `LUNG1-002/.../4.000000-NA-45931` | 1 | `LUNG1-002` | RTSTRUCT | 结构化轮廓标注 | - | - | - |
| `LUNG1-002/.../300.000000-Segmentation-5.421` | 1 | - | SEG | DICOM segmentation mask | - | - | - |
| `LUNG1-003/.../1.000000-NA-28595` | 107 | `LUNG1-003` | CT | CT 影像序列 | 512 x 512 | 0.9770 x 0.9770 | 3.00000 |
| `LUNG1-003/.../4.000000-NA-22712` | 1 | `LUNG1-003` | RTSTRUCT | 结构化轮廓标注 | - | - | - |
| `LUNG1-003/.../300.000000-Segmentation-2.316` | 1 | - | SEG | DICOM segmentation mask | - | - | - |

说明：

- `CT` 序列应导入为 `images`。
- `RTSTRUCT` 和 `SEG` 可作为已有标注或已有 mask 导入，后续进入 `annotations`、`masks`、`versions`。
- `PatientID` 可以映射到 `cases.patient_id`。
- 平台内部仍使用统一 ID，例如 `Case0001`、`Image0001`，不要直接把外部 `LUNG1-001` 当作主键。

## 4. NRRD 数据摘要

`patient1.zip` 内部文件：

```text
patient1/
  p1.nrrd
  p1-label.nrrd
```

`p1.nrrd` 关键头信息：

```text
type: int
dimension: 3
space: left-posterior-superior
sizes: 512 512 134
space directions:
  (0.97656249999999978,0,0)
  (0,0.97656249999999978,0)
  (0,0,2.9999999999999991)
encoding: gzip
```

`p1-label.nrrd` 关键头信息：

```text
type: short
dimension: 3
sizes: 512 512 134
Segment0_ID: 1
Segment0_LabelValue: 1
Segment0_Name: Neoplasm, Primary
Segmentation_ContainedRepresentationNames: Binary labelmap|Closed surface
```

结论：

- `p1.nrrd` 是 3D 图像，应导入 `images`。
- `p1-label.nrrd` 是已有标签 mask，应导入 `masks`。
- 两者尺寸一致，均为 `512 x 512 x 134`，空间方向和 spacing 可用于一致性校验。
- `Neoplasm, Primary` 应在平台中映射为统一 label，例如 `tumor` 或 `lung_nodule`，不要直接使用带空格和逗号的原始名称作为内部标签。

## 5. 对数据库设计的影响

样例数据说明 Day1 最小八表可以覆盖当前需求：

| 数据现象 | 对应表 |
| --- | --- |
| 一个 PatientID 对应一个病例。 | `cases` |
| 一个病例下有 CT 序列、NRRD 体数据。 | `images` |
| RTSTRUCT、SEG、NRRD label 都是标注或 mask 来源。 | `annotations`、`masks` |
| AI 模型预测后生成 mask。 | `models`、`masks` |
| 人工修正、AI 结果、最终审核需要版本追踪。 | `versions` |
| train/val/test 划分要固定保存。 | `datasets` |

Day1 先保留八张表。更细的 DICOM 字段，例如 `spacing`、`origin`、`direction`、`study_uid`、`series_uid`，可以先写入文件级 metadata，后续需要时再扩展表字段。

