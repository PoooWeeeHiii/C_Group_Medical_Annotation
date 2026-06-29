# GitHub 协作规范

## 1. 仓库定位

C 组使用一个统一仓库，不拆成两个独立小程序。

统一仓库负责管理：

- 后端 API
- 前端标注平台
- AI 训练和推理脚本
- Dataset 目录规范
- Mask 和版本规则
- 数据库设计
- 接口文档
- 项目流程图

推荐仓库名：

```text
C_Group_Medical_Annotation
```

## 2. GitHub 仓库结构

```text
C_Group_Medical_Annotation/
  backend/          # Person A: FastAPI、数据库、接口
  frontend/         # Person A: 页面、标注工具、病例管理
  ai/               # Person B: 训练、推理、评价指标
  dataset/          # 只放小样例、manifest、split，不放大数据
    raw/
    images/
    labels/
    splits/
  database/         # 建表 SQL、ER 图
  docs/             # 接口文档、分工、流程图
  models/           # 不放大模型，只放说明或下载链接
  requirements.txt
  .gitignore
  README.md
```

## 3. 不要上传到 GitHub 的内容

以下内容不要直接提交：

- 大 CT 数据
- DICOM 原始序列
- NIfTI / NRRD 大体积影像
- 真实病人数据
- 大 Mask 文件
- `.pth`、`.pt`、`.ckpt`、`.onnx` 模型权重
- 大型 PDF 参考书
- 本地虚拟环境
- 缓存文件

这些内容建议放在：

- 本地数据目录
- 网盘
- 服务器
- MinIO / 对象存储
- 实验室共享存储

GitHub 只放：

- 代码
- 小样例说明
- 配置文件
- 文档
- 目录占位文件
- 数据集划分 manifest

## 4. 分支设计

使用四条核心分支：

```text
main        # 稳定版，只放能运行、能演示的代码
dev         # 每天合并测试版
feature-a   # Person A 开发平台、后端、前端、数据库、接口
feature-b   # Person B 开发 AI、训练、推理、评价指标
```

## 5. 首次上传到 GitHub

先在 GitHub 网页创建一个空仓库，推荐仓库名：

```text
C_Group_Medical_Annotation
```

不要勾选自动生成 README、`.gitignore` 或 License，因为本地仓库已经有这些文件。

创建后，把 GitHub 给出的 SSH 或 HTTPS 地址添加为远程仓库：

```bash
git remote add origin git@github.com:<your_name>/C_Group_Medical_Annotation.git
```

首次推送四个分支：

```bash
git push -u origin main
git push -u origin dev
git push -u origin feature-a
git push -u origin feature-b
```

## 6. 每日开发流程

Person A：

```text
git switch dev
git pull
git switch feature-a
git merge dev
# 开发 backend/frontend/database/docs
git add .
git commit -m "A: update platform module"
git push
```

Person B：

```text
git switch dev
git pull
git switch feature-b
git merge dev
# 开发 ai/dataset/models/docs
git add .
git commit -m "B: update ai module"
git push
```

每天晚上：

```text
feature-a -> dev
feature-b -> dev
dev 测试通过 -> main
```

建议通过 Pull Request 合并，不要直接把未测试代码推到 `main`。

## 7. 合并原则

- `main` 保持稳定，不直接开发。
- `dev` 是当天集成分支。
- `feature-a` 和 `feature-b` 每天从 `dev` 同步。
- API、Dataset、Mask 命名一旦改动，必须同时更新文档。
- 大文件不要强行提交；如误提交，应立即从 Git 历史中清理。
