#!/usr/bin/env python3
"""Generate system-test report markdown/json from pytest JUnit XML."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


def parse_junit(path: Path) -> dict:
    if not path.exists():
        return {
            "tests": 0,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "time": 0.0,
            "cases": [],
        }
    root = ET.parse(path).getroot()
    # pytest may wrap as testsuites/testsuite
    suites = root.findall("testsuite")
    if not suites and root.tag == "testsuite":
        suites = [root]
    cases = []
    tests = failures = errors = skipped = 0
    total_time = 0.0
    for suite in suites:
        tests += int(suite.attrib.get("tests", 0))
        failures += int(suite.attrib.get("failures", 0))
        errors += int(suite.attrib.get("errors", 0))
        skipped += int(suite.attrib.get("skipped", 0))
        total_time += float(suite.attrib.get("time", 0) or 0)
        for case in suite.findall("testcase"):
            status = "passed"
            detail = ""
            if case.find("failure") is not None:
                status = "failed"
                detail = (case.find("failure").attrib.get("message") or "") + "\n" + (case.find("failure").text or "")
            elif case.find("error") is not None:
                status = "error"
                detail = (case.find("error").attrib.get("message") or "") + "\n" + (case.find("error").text or "")
            elif case.find("skipped") is not None:
                status = "skipped"
                detail = case.find("skipped").attrib.get("message") or ""
            cases.append(
                {
                    "classname": case.attrib.get("classname", ""),
                    "name": case.attrib.get("name", ""),
                    "time": float(case.attrib.get("time", 0) or 0),
                    "status": status,
                    "detail": detail.strip(),
                }
            )
    return {
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "time": total_time,
        "cases": cases,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", required=True)
    ap.add_argument("--markdown", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--exit-code", type=int, default=0)
    args = ap.parse_args()

    data = parse_junit(Path(args.junit))
    passed = data["tests"] - data["failures"] - data["errors"] - data["skipped"]
    # skipped counted separately
    passed = max(0, data["tests"] - data["failures"] - data["errors"] - data["skipped"])
    rate = (passed / data["tests"] * 100) if data["tests"] else 0.0
    verdict = "PASS" if args.exit_code == 0 and data["failures"] == 0 and data["errors"] == 0 else "FAIL"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "verdict": verdict,
        "exit_code": args.exit_code,
        "summary": {
            "tests": data["tests"],
            "passed": passed,
            "failed": data["failures"],
            "errors": data["errors"],
            "skipped": data["skipped"],
            "duration_sec": round(data["time"], 3),
            "pass_rate_pct": round(rate, 2),
        },
        "cases": data["cases"],
    }
    Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 系统测试报告（System Test Report）",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 被测环境：`{args.base_url}`",
        f"- 结论：**{verdict}**",
        f"- 用例总数：{data['tests']}",
        f"- 通过：{passed}",
        f"- 失败：{data['failures']}",
        f"- 错误：{data['errors']}",
        f"- 跳过：{data['skipped']}",
        f"- 通过率：{rate:.2f}%",
        f"- 耗时：{data['time']:.2f}s",
        "",
        "## 1. 测试依据",
        "",
        "- 计划文档：`docs/17_system_test_plan.md`",
        "- 执行脚本：`scripts/run_system_tests.sh`",
        "- 用例代码：`tests/system/test_system_api.py`",
        "",
        "## 2. 测试类型覆盖",
        "",
        "| 类型 | 覆盖说明 |",
        "| --- | --- |",
        "| 功能测试 | 健康检查、登录、病例/影像、Mask 读写、标签、模型、手术 ROI、上传导出 |",
        "| 权限/安全负向 | 错密登录、无 token、越权 approve/users、路径穿越/注入样例 |",
        "| 边界/异常 | 非法 cuboid、label_id<=0、不存在 case/image、未知 API |",
        "| 工作流集成 | submit→reject→resubmit→approve；promote/rollback；图割/DeepEdit |",
        "| AI/训练 | 模型就绪、可选实装预测、短训任务启停轮询 |",
        "| 性能冒烟 | /api/health、/api/cases 延迟阈值 |",
        "| 界面入口 | `/` 与关键 frontend 静态脚本可访问 |",
        "| 人工 UI | 见 docs/18_manual_ui_checklist.md（手势/VTK/手术） |",
        "",
        "## 3. 用例结果明细",
        "",
        "| 用例 | 状态 | 耗时(s) |",
        "| --- | --- | --- |",
    ]
    for c in data["cases"]:
        name = c["name"]
        lines.append(f"| `{name}` | {c['status']} | {c['time']:.3f} |")

    fails = [c for c in data["cases"] if c["status"] in {"failed", "error"}]
    lines.extend(["", "## 4. 失败与错误详情", ""])
    if not fails:
        lines.append("无。")
    else:
        for c in fails:
            lines.append(f"### `{c['name']}` ({c['status']})")
            lines.append("")
            lines.append("```")
            lines.append(c["detail"][:4000] or "(no detail)")
            lines.append("```")
            lines.append("")

    lines.extend(
        [
            "## 5. 结论与建议",
            "",
            (
                "本轮系统测试通过，关键业务链路（鉴权、病例影像、手术 ROI 含器官信息、静态入口）可用。"
                if verdict == "PASS"
                else "本轮系统测试未完全通过，请先修复失败用例后再回归。"
            ),
            "",
            "后续建议：",
            "1. 为上传/导出/审核状态机增加独立沙箱库，避免污染演示数据；",
            "2. 补充浏览器端手势与三维交互的人工测试记录；",
            "3. 将本脚本接入 CI（先保证 `/api/health` 服务就绪）。",
            "",
        ]
    )
    Path(args.markdown).write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
