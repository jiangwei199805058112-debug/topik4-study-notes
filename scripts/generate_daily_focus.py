from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
REVIEW_EVENTS_PATH = ROOT / "data" / "review_events.jsonl"
SCORE_LOG_PATH = ROOT / "data" / "exam_diagnostics" / "topik_score_log.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a read-only TOPIK daily focus note from event data.")
    parser.add_argument("--date", required=True, help="Focus date in YYYY-MM-DD format.")
    return parser.parse_args()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(value)
    return events


def score_value(text: str | None) -> int | None:
    if not text:
        return None
    match = re.match(r"(\d+)\s*/\s*100", text.strip())
    return int(match.group(1)) if match else None


def score_rows() -> list[dict[str, str]]:
    if not SCORE_LOG_PATH.exists():
        return []
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in SCORE_LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] == "日期":
            header = cells
            continue
        if header and len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
    return rows


def subject_score(subject: str, rows: list[dict[str, str]]) -> int | None:
    for row in reversed(rows):
        if row.get("科目") == subject:
            return score_value(row.get("分数"))
    return None


def previous_due_from_daily(day: date) -> int | None:
    path = ROOT / "daily" / f"{day.isoformat()}_daily_log.md"
    if not path.exists():
        return None
    match = re.search(r"总复习数量[：:]\s*(\d+)", path.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else None


def previous_summary(day: date, events: list[dict[str, Any]]) -> tuple[int | None, int]:
    due_total: int | None = None
    weak_total = 0
    for event in events:
        if event.get("date") != day.isoformat():
            continue
        if isinstance(event.get("total"), int):
            due_total = max(due_total or 0, int(event["total"]))
        elif isinstance(event.get("total"), str) and str(event.get("total")).isdigit():
            due_total = max(due_total or 0, int(str(event["total"])))
        for key in ("wrong", "uncertain"):
            value = event.get(key)
            if isinstance(value, int):
                weak_total += value
            elif isinstance(value, str) and value.isdigit():
                weak_total += int(value)
        if event.get("result") in {"wrong", "uncertain"}:
            weak_total += 1
    if due_total is None:
        due_total = previous_due_from_daily(day)
    return due_total, weak_total


def main() -> int:
    args = parse_args()
    target = parse_date(args.date)
    previous_day = target - timedelta(days=1)
    reviews = read_jsonl(REVIEW_EVENTS_PATH)
    scores = score_rows()

    reading = subject_score("읽기", scores)
    listening = subject_score("듣기", scores)
    writing = subject_score("쓰기", scores)
    previous_due, weak_total = previous_summary(previous_day, reviews)

    priorities: list[str] = []
    if reading is not None and reading < 55:
        priorities.append("阅读：当前低于 55，优先补中后段句子结构、上下文判断和长文主旨。")
    if writing is None or writing < 35:
        priorities.append("写作：未测或低于 35，需要从句子和段落骨架开始。")
    if listening is not None and listening < 60:
        priorities.append("听力：低于 60，继续保持关键词和长对话处理。")
    if not priorities:
        priorities.append("维持复习稳定性，优先处理昨日 wrong/uncertain。")

    should_add_new = not ((previous_due is not None and previous_due > 50) or weak_total > 10)
    print(f"# Daily Focus {target.isoformat()}")
    print("")
    print("## 今日优先技能")
    for item in priorities:
        print(f"- {item}")
    print("")
    print("## 今日是否适合新增")
    if should_add_new:
        print("- 可以少量新增；先确认昨日 weak 项已经复查。")
    else:
        print("- 不建议新增；先处理昨日 due 压力或 wrong/uncertain。")
    print(f"- previous_due: {previous_due if previous_due is not None else 'unknown'}")
    print(f"- previous_wrong_uncertain: {weak_total}")
    print("")
    print("## 今日 GPT 精讲建议")
    print("- 只精讲阅读 2-4、13-18、19-31 中暴露出的结构和连接问题。")
    print("- 每个语法点至少保留一个 TOPIK 语境例句和一个近似表达对比。")
    print("")
    print("## 阅读/听力/写作建议")
    print("- 阅读：从 44 -> 55–60，先做中段短文和句子排序，不急着全量精扒 39–50。")
    print("- 听力：56/100，继续保留后段长题的关键词定位训练。")
    print("- 写作：当前未测，先建立 53 题句子连接和 54 题段落结构。")
    print("")
    print("## 当前目标分数差距")
    if reading is not None:
        print(f"- 읽기: {reading}/100，距 55 还差 {max(0, 55 - reading)} 分。")
    if listening is not None:
        print(f"- 듣기: {listening}/100，距 60 还差 {max(0, 60 - listening)} 分。")
    print("- 쓰기: 待测；先按 <35 风险处理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
