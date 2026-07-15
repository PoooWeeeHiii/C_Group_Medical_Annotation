"""Quality report Markdown generation and optional LLM polish."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import (
    REPORT_POLISH_API_KEY,
    REPORT_POLISH_BASE_URL,
    REPORT_POLISH_MODEL,
    REPORT_POLISH_TIMEOUT_SECONDS,
)
from backend.app.services.mask_service import get_mask_metrics


def polish_status() -> dict[str, Any]:
    configured = bool(REPORT_POLISH_API_KEY)
    return {
        "success": True,
        "configured": configured,
        "model": REPORT_POLISH_MODEL if configured else None,
        "base_url": REPORT_POLISH_BASE_URL if configured else None,
        "message": (
            "AI polish ready"
            if configured
            else "Set REPORT_POLISH_API_KEY in .env to enable AI report polish"
        ),
    }


def _fmt_num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_slice_range(range_value: Any) -> str:
    if range_value is None:
        return "-"
    if isinstance(range_value, dict):
        start = range_value.get("start")
        end = range_value.get("end")
        count = range_value.get("count")
        if start is None and end is None:
            return "-"
        base = f"{start} – {end}"
        return f"{base}（{count} 层）" if count is not None else base
    if isinstance(range_value, (list, tuple)) and len(range_value) >= 2:
        return f"{range_value[0]} – {range_value[1]}"
    return str(range_value)


def _quality_verdict(overlap: dict[str, Any] | None, geometric: dict[str, Any] | None) -> str:
    if overlap and overlap.get("dice") is not None:
        dice = float(overlap["dice"])
        if dice >= 0.9:
            return "与参考标注高度一致，整体质量优秀。"
        if dice >= 0.8:
            return "与参考标注一致性良好，局部边界可继续精修。"
        if dice >= 0.6:
            return "重叠中等，建议重点核对错误切片与边界区域。"
        return "与参考标注差异较大，建议复核连通域与主要错误层后再定稿。"
    if geometric:
        cc = int(geometric.get("connected_component_count") or 0)
        ratio = geometric.get("largest_component_ratio")
        if cc <= 1 and ratio is not None and float(ratio) >= 0.95:
            return "几何结构较干净（单连通、主体占比高），可进入后续审核。"
        if cc > 3:
            return "存在多个连通域，建议清理噪声碎片后再提交审核。"
        return "已完成几何质量检查；补充 GT 后可给出重叠指标结论。"
    return "指标不足，暂无法给出质量结论。"


def build_quality_report_markdown(
    metrics: dict[str, Any],
    *,
    case_id: str | None = None,
) -> tuple[str, str]:
    """Return (title, markdown) from a metrics payload."""
    mask_id = str(metrics.get("mask_id") or "")
    ref_mask_id = metrics.get("ref_mask_id")
    version = metrics.get("version") or "-"
    label = metrics.get("label") or "-"
    geometric = metrics.get("geometric") or {}
    overlap = metrics.get("overlap")
    error_slices = list(metrics.get("error_slices") or [])
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    title = f"质量报告 · {case_id or '未知病例'} · {mask_id or version}"
    lines: list[str] = [
        f"# {title}",
        "",
        f"- 生成时间：{now}",
        f"- 病例：`{case_id or '-'}`",
        f"- 评价 Mask：`{mask_id}`（version=`{version}`，label=`{label}`）",
        f"- 参考 GT：`{ref_mask_id or '无'}`",
        "",
        "## 结论摘要",
        "",
        _quality_verdict(overlap if isinstance(overlap, dict) else None, geometric if isinstance(geometric, dict) else None),
        "",
        "## 几何质量",
        "",
        f"| 指标 | 数值 |",
        f"| --- | --- |",
        f"| 体素数 | {geometric.get('voxel_count', '-')} |",
        f"| 体积 (ml) | {_fmt_num(geometric.get('volume_ml'), 3)} |",
        f"| 连通域数 | {geometric.get('connected_component_count', '-')} |",
        f"| 最大连通域占比 | {_fmt_num(geometric.get('largest_component_ratio'), 3)} |",
        f"| 切片范围 | {_fmt_slice_range(geometric.get('slice_range'))} |",
        "",
    ]

    if isinstance(overlap, dict):
        lines.extend(
            [
                "## 重叠指标（相对 GT）",
                "",
                "| 指标 | 数值 |",
                "| --- | --- |",
                f"| Dice | {_fmt_num(overlap.get('dice'))} |",
                f"| IoU | {_fmt_num(overlap.get('iou'))} |",
                f"| Precision | {_fmt_num(overlap.get('precision'))} |",
                f"| Recall | {_fmt_num(overlap.get('recall'))} |",
                f"| HD95 (mm) | {_fmt_num(overlap.get('hd95_mm'), 3)} |",
                f"| 体积差 (ml) | {_fmt_num(overlap.get('volume_diff_ml'), 3)} |",
                "",
            ]
        )
    else:
        lines.extend(["## 重叠指标（相对 GT）", "", "未提供参考 GT，仅输出几何质量。", ""])

    if error_slices:
        lines.extend(
            [
                "## 错误切片（Top）",
                "",
                "| 平面 | 切片 | 错误体素 | Pred | Ref |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in error_slices:
            axis = item.get("axis") or "-"
            slice_index = item.get("slice_index")
            display_slice = (int(slice_index) + 1) if slice_index is not None else "-"
            lines.append(
                "| {axis} | {slice_} | {err} | {pred} | {ref} |".format(
                    axis=axis,
                    slice_=display_slice,
                    err=item.get("error_voxels", "-"),
                    pred=item.get("pred_voxels", "-"),
                    ref=item.get("ref_voxels", "-"),
                )
            )
        lines.append("")
    elif ref_mask_id:
        lines.extend(["## 错误切片（Top）", "", "未检出显著错误切片。", ""])

    lines.extend(
        [
            "## 建议",
            "",
            "- 若连通域偏多，优先清理碎片与假阳性。",
            "- 若 Dice/IoU 偏低，优先复核错误切片列表中的层面。",
            "- 边界不稳定时可结合 DeepEdit / 图割做交互精修后复测。",
            "",
            "---",
            "",
            "*本报告由标注平台根据 Mask 质量指标自动生成。*",
            "",
        ]
    )
    return title, "\n".join(lines)


def generate_quality_report(
    mask_id: str,
    *,
    ref_mask_id: str | None = None,
    case_id: str | None = None,
    include_error_slices: bool = True,
) -> dict[str, Any]:
    metrics = get_mask_metrics(mask_id, ref_mask_id=ref_mask_id)
    if not include_error_slices:
        metrics = {**metrics, "error_slices": []}
    title, markdown = build_quality_report_markdown(metrics, case_id=case_id)
    return {
        "success": True,
        "mask_id": mask_id,
        "ref_mask_id": ref_mask_id,
        "case_id": case_id,
        "title": title,
        "markdown": markdown,
        "metrics": metrics,
        "message": "quality report generated",
    }


_TONE_HINTS = {
    "clinical": "语气专业、客观，适合临床与影像科审阅，避免夸张形容词。",
    "concise": "尽量简短，保留关键数字与结论，删去重复表述。",
    "detailed": "在不编造数据的前提下补充解读与改进建议，结构清晰。",
}


def polish_report(
    draft_markdown: str,
    *,
    tone: str = "clinical",
    case_id: str | None = None,
    mask_id: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    draft = (draft_markdown or "").strip()
    if not draft:
        return {
            "success": False,
            "polished": False,
            "markdown": "",
            "model": None,
            "message": "draft_markdown is empty",
        }

    if not REPORT_POLISH_API_KEY:
        return {
            "success": True,
            "polished": False,
            "markdown": draft,
            "model": None,
            "message": "AI polish not configured; returned original draft. Set REPORT_POLISH_API_KEY.",
        }

    tone_key = tone if tone in _TONE_HINTS else "clinical"
    system_prompt = (
        "你是医学影像标注平台的质量报告编辑助手。"
        "在不改变任何数值、病例 ID、Mask ID 的前提下润色中文 Markdown 报告。"
        "禁止编造指标；可调整段落结构与表述。"
        f"{_TONE_HINTS[tone_key]}"
        "只输出润色后的完整 Markdown，不要解释过程。"
    )
    user_parts = [f"请润色以下质量报告（tone={tone_key}）：\n\n{draft}"]
    if case_id or mask_id:
        user_parts.insert(0, f"上下文：case_id={case_id or '-'}，mask_id={mask_id or '-'}")
    if metrics:
        # Compact metrics for grounding; keep small.
        compact = {
            "mask_id": metrics.get("mask_id"),
            "ref_mask_id": metrics.get("ref_mask_id"),
            "geometric": metrics.get("geometric"),
            "overlap": metrics.get("overlap"),
        }
        user_parts.append("参考指标 JSON（不得改写数值）：\n" + json.dumps(compact, ensure_ascii=False, default=str))

    base = REPORT_POLISH_BASE_URL.rstrip("/")
    # Accept shorthand Gemini host and rewrite to OpenAI-compatible base.
    if "generativelanguage.googleapis.com" in base and "/openai" not in base:
        if base.endswith("/v1beta"):
            base = base + "/openai"
        else:
            base = "https://generativelanguage.googleapis.com/v1beta/openai"
    endpoint = base + "/chat/completions"
    body = {
        "model": REPORT_POLISH_MODEL,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {REPORT_POLISH_API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REPORT_POLISH_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return {
            "success": False,
            "polished": False,
            "markdown": draft,
            "model": REPORT_POLISH_MODEL,
            "message": f"AI polish HTTP {exc.code}: {detail}",
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "success": False,
            "polished": False,
            "markdown": draft,
            "model": REPORT_POLISH_MODEL,
            "message": f"AI polish failed: {exc}",
        }

    try:
        content = payload["choices"][0]["message"]["content"]
        polished_text = str(content).strip()
    except (KeyError, IndexError, TypeError):
        return {
            "success": False,
            "polished": False,
            "markdown": draft,
            "model": REPORT_POLISH_MODEL,
            "message": "AI polish returned unexpected payload",
        }

    if polished_text.startswith("```"):
        # Strip accidental fenced block wrapper.
        parts = polished_text.split("\n")
        if parts and parts[0].startswith("```"):
            parts = parts[1:]
        if parts and parts[-1].strip() == "```":
            parts = parts[:-1]
        polished_text = "\n".join(parts).strip()

    return {
        "success": True,
        "polished": True,
        "markdown": polished_text or draft,
        "model": REPORT_POLISH_MODEL,
        "message": "AI polish completed",
    }
