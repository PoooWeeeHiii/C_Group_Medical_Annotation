#!/usr/bin/env python3
"""Generate class / state / program-flow figures for ZH and EN reports."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIG_ZH = ROOT / "figures"
FIG_EN = ROOT / "figures" / "en"
FIG_ZH.mkdir(parents=True, exist_ok=True)
FIG_EN.mkdir(parents=True, exist_ok=True)

for _fname in ("Songti SC", "Hiragino Sans GB", "Heiti SC", "PingFang SC", "Arial Unicode MS"):
    try:
        path = font_manager.findfont(_fname, fallback_to_default=False)
        if path and "DejaVu" not in path:
            ZH_FONT = _fname
            break
    except Exception:
        continue
else:
    ZH_FONT = "DejaVu Sans"


def save(fig, path: Path) -> None:
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", path.name)


def box(ax, x, y, w, h, fc, text, fs=8.5):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.03,rounding_size=0.06",
            facecolor=fc,
            edgecolor="#333",
            linewidth=1.1,
        )
    )
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs)


def arrow(ax, x1, y1, x2, y2):
    ax.annotate(
        "",
        xy=(x2, y2),
        xytext=(x1, y1),
        arrowprops=dict(arrowstyle="->", color="#333", lw=1.2),
    )


def gen_class(lang: str):
    en = lang == "en"
    plt.rcParams["font.family"] = "DejaVu Sans" if en else ZH_FONT
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(11, 6.2))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 6.4)
    ax.axis("off")
    ax.set_title(
        "Fig. 11  Core Classes / Objects (My Backend)" if en else "图11  核心类与对象设计（本人后端）",
        fontsize=13,
        pad=10,
    )
    items = [
        (0.4, 4.6, 3.0, 1.4, "#E8F1FA", "APIRouter / Schemas\nAuth · Case · Mask\nSurgery · Export" if en else "API 路由 / Schemas\nAuth · Case · Mask\nSurgery · Export"),
        (4.0, 4.6, 3.0, 1.4, "#EAF6EA", "Services\nmask_service\nsurgery_service\nai_service" if en else "业务服务层\nmask_service\nsurgery_service\nai_service"),
        (7.6, 4.6, 3.0, 1.4, "#FFF6E5", "Persistence\nSQLite conn\nschema helpers\nfile paths" if en else "持久化\nSQLite 连接\nschema 兼容\n文件路径"),
        (0.4, 2.4, 3.0, 1.4, "#F5EAF6", "Frontend objects\napp.js state\nvolume_viewer\nhand_gesture" if en else "前端对象\napp.js 状态\nvolume_viewer\nhand_gesture"),
        (4.0, 2.4, 3.0, 1.4, "#FFEFE5", "Domain records\nCase / Image / Mask\nVersion / Task\nSurgeryResult" if en else "领域记录\nCase / Image / Mask\nVersion / Task\nSurgeryResult"),
        (7.6, 2.4, 3.0, 1.4, "#F0F0F0", "External\nTotalSeg / nnU-Net\nVTK.js / MediaPipe" if en else "外部依赖\nTotalSeg / nnU-Net\nVTK.js / MediaPipe"),
    ]
    for args in items:
        box(ax, *args, fs=8)
    # relations
    arrow(ax, 3.4, 5.3, 4.0, 5.3)
    arrow(ax, 7.0, 5.3, 7.6, 5.3)
    arrow(ax, 5.5, 4.6, 5.5, 3.8)
    arrow(ax, 1.9, 4.6, 1.9, 3.8)
    arrow(ax, 9.1, 4.6, 9.1, 3.8)
    note = (
        "Dependency direction: UI/API → Services → Persistence; domain DTOs shared via Pydantic models"
        if en
        else "依赖方向：前端/API → 服务层 → 持久化；领域对象通过 Pydantic 模型在层间传递"
    )
    ax.text(5.5, 0.7, note, ha="center", fontsize=9, color="#333")
    save(fig, (FIG_EN if en else FIG_ZH) / "fig11_class.png")


def gen_state(lang: str):
    en = lang == "en"
    plt.rcParams["font.family"] = "DejaVu Sans" if en else ZH_FONT
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(11, 5.8))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 5.8)
    ax.axis("off")
    ax.set_title(
        "Fig. 12  State Machines: Review + Surgery Modes" if en else "图12  状态图：审核工作流与模拟手术模式",
        fontsize=13,
        pad=10,
    )
    # review row
    ax.text(0.3, 5.3, "Review workflow" if en else "审核工作流", fontsize=10, fontweight="bold")
    rev = [
        (0.4, 4.2, "annotating" if en else "标注中"),
        (3.0, 4.2, "submitted" if en else "已提交"),
        (5.6, 4.2, "approved" if en else "已通过"),
        (8.2, 4.2, "rejected" if en else "已驳回"),
    ]
    for x, y, t in rev:
        box(ax, x, y, 2.0, 0.8, "#E8F0FF", t, fs=9)
    arrow(ax, 2.4, 4.6, 3.0, 4.6)
    arrow(ax, 5.0, 4.6, 5.6, 4.6)
    ax.annotate(
        "",
        xy=(4.0, 4.2),
        xytext=(9.2, 4.2),
        arrowprops=dict(arrowstyle="->", color="#666", connectionstyle="arc3,rad=0.35", lw=1.1),
    )
    ax.text(6.6, 3.7, "reject → re-edit" if en else "驳回后可再编辑", ha="center", fontsize=8, color="#555")

    ax.text(0.3, 3.1, "Surgery mode FSM" if en else "模拟手术模式状态机", fontsize=10, fontweight="bold")
    surg = [
        (0.4, 1.8, "idle / browse" if en else "浏览/空闲"),
        (3.0, 1.8, "select organ" if en else "选中器官"),
        (5.6, 1.8, "ROI confirmed" if en else "ROI 已确认"),
        (8.2, 1.8, "cutting / saved" if en else "切割/已保存"),
    ]
    for x, y, t in surg:
        box(ax, x, y, 2.0, 0.9, "#FFF3D6", t, fs=8.5)
    arrow(ax, 2.4, 2.25, 3.0, 2.25)
    arrow(ax, 5.0, 2.25, 5.6, 2.25)
    arrow(ax, 7.6, 2.25, 8.2, 2.25)
    ax.text(
        5.5,
        0.7,
        "Gates: valid label → confirm cuboid → allow cut → POST surgery_results"
        if en
        else "门槛：有效 label → 确认长方体 → 允许切割 → POST 入库",
        ha="center",
        fontsize=9,
    )
    save(fig, (FIG_EN if en else FIG_ZH) / "fig12_state.png")


def gen_prog_flow(lang: str):
    en = lang == "en"
    plt.rcParams["font.family"] = "DejaVu Sans" if en else ZH_FONT
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(8.5, 9.2))
    ax.set_xlim(0, 8.5)
    ax.set_ylim(0, 9.2)
    ax.axis("off")
    ax.set_title(
        "Fig. 13  Program Flow: Save Surgery ROI" if en else "图13  程序流程图：保存模拟手术 ROI",
        fontsize=12,
        pad=8,
    )
    steps = [
        (2.5, 8.2, 3.5, 0.55, "#E8F1FA", "Start: user clicks Save" if en else "开始：用户点击保存"),
        (2.5, 7.3, 3.5, 0.55, "#FFF6E5", "getSurgerySnapshot()" if en else "前端 getSurgerySnapshot()"),
        (2.5, 6.4, 3.5, 0.55, "#FFE5E5", "ROI confirmed?" if en else "ROI 是否已确认？"),
        (2.5, 5.3, 3.5, 0.55, "#F5EAF6", "POST /api/surgery_results" if en else "POST /api/surgery_results"),
        (2.5, 4.4, 3.5, 0.55, "#EAF6EA", "Validate case/image/label" if en else "校验 case/image/label"),
        (2.5, 3.5, 3.5, 0.55, "#EAF6EA", "Resolve organ fields" if en else "解析 organ 字段"),
        (2.5, 2.6, 3.5, 0.55, "#EAF6EA", "INSERT surgery_results" if en else "INSERT surgery_results"),
        (2.5, 1.7, 3.5, 0.55, "#E8F1FA", "Return success + toast" if en else "返回成功并提示"),
        (2.5, 0.7, 3.5, 0.55, "#F0F0F0", "End" if en else "结束"),
    ]
    for args in steps:
        box(ax, *args, fs=9)
    for y1, y2 in [(8.2, 7.85), (7.3, 6.95), (6.4, 5.85), (5.3, 4.95), (4.4, 4.05), (3.5, 3.15), (2.6, 2.25), (1.7, 1.25)]:
        arrow(ax, 4.25, y1, 4.25, y2)
    # no branch
    box(ax, 6.2, 6.2, 2.0, 0.7, "#FFEFE5", "Abort / warn" if en else "中止并提示", fs=8)
    ax.annotate("", xy=(6.2, 6.55), xytext=(6.0, 6.65), arrowprops=dict(arrowstyle="->", color="#333", lw=1.1))
    ax.text(6.5, 7.0, "No" if en else "否", fontsize=8)
    ax.text(4.5, 6.05, "Yes" if en else "是", fontsize=8)
    save(fig, (FIG_EN if en else FIG_ZH) / "fig13_program_flow.png")


def gen_collab(lang: str):
    en = lang == "en"
    plt.rcParams["font.family"] = "DejaVu Sans" if en else ZH_FONT
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    ax.set_xlim(0, 10.5)
    ax.set_ylim(0, 5.2)
    ax.axis("off")
    ax.set_title(
        "Fig. 14  Collaboration: AI Predict Write-back" if en else "图14  协作图：AI 预测写回（简化）",
        fontsize=13,
        pad=10,
    )
    objs = [
        (0.5, 3.5, "Annotator UI" if en else "标注员 UI"),
        (3.0, 3.5, "ai_service" if en else "ai_service"),
        (5.5, 3.5, "AI backend" if en else "AI 后端"),
        (8.0, 3.5, "mask/version" if en else "mask/version"),
    ]
    for x, y, t in objs:
        box(ax, x, y, 2.0, 0.9, "#E8F0FF", t, fs=9)
    msgs = [
        (1.5, 3.5, 4.0, 3.5, "1 predict()" if en else "1 请求预测"),
        (4.0, 3.3, 6.5, 3.3, "2 run model" if en else "2 执行模型"),
        (6.5, 3.1, 4.0, 3.1, "3 mask/error" if en else "3 掩膜/错误"),
        (4.0, 2.9, 9.0, 2.9, "4 store AI version" if en else "4 写入 AI 版本"),
        (9.0, 2.7, 1.5, 2.7, "5 refresh UI" if en else "5 刷新界面"),
    ]
    # draw horizontal message lines below objects
    y = 2.3
    for i, (a, b, t) in enumerate(
        [
            (1.5, 4.0, "1. POST /api/ai/predict" if en else "1. POST /api/ai/predict"),
            (4.0, 6.5, "2. invoke TotalSeg/nnU-Net/..." if en else "2. 调用 TotalSeg/nnU-Net/..."),
            (6.5, 4.0, "3. mask tensor or honest error" if en else "3. 返回掩膜或明确错误"),
            (4.0, 9.0, "4. write mask + version tag=ai" if en else "4. 写 mask + version(tag=ai)"),
            (9.0, 1.5, "5. UI reload / toast" if en else "5. 界面刷新 / 提示"),
        ]
    ):
        yy = 2.2 - i * 0.35
        ax.annotate("", xy=(b, yy), xytext=(a, yy), arrowprops=dict(arrowstyle="->", color="#234", lw=1.1))
        ax.text((a + b) / 2, yy + 0.08, t, ha="center", fontsize=7.5)
    for x in [1.5, 4.0, 6.5, 9.0]:
        ax.plot([x, x], [0.4, 3.5], color="#aaa", lw=1, ls="--")
    save(fig, (FIG_EN if en else FIG_ZH) / "fig14_collab.png")


def main():
    for lang in ("zh", "en"):
        gen_class(lang)
        gen_state(lang)
        gen_prog_flow(lang)
        gen_collab(lang)
    print("extra figures done")


if __name__ == "__main__":
    main()
