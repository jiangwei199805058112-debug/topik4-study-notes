from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from generate_review_plan import (  # noqa: E402
    DEFAULTS,
    QUEUE_PATH,
    ROOT,
    due_rows,
    parse_date,
    read_queue_rows,
    sanitize_cell,
    write_queue_rows,
    write_review_plan,
)


DAILY_DIR = ROOT / "daily"

R_INTERVALS = {
    "R0": 0,
    "R1": 0,
    "R2": 1,
    "R3": 3,
    "R4": 7,
    "R5": 14,
    "R6": 30,
    "R7": 60,
}

NEXT_R = {
    "R0": "R1",
    "R1": "R2",
    "R2": "R3",
    "R3": "R4",
    "R4": "R5",
    "R5": "R6",
    "R6": "R7",
    "R7": "archived",
}

ROLLBACK_R = {
    "R3": "R1",
    "R5": "R3",
    "R7": "R2",
}

PREFIX_BY_TYPE = {
    "vocabulary": "VOC",
    "phrases": "PHR",
    "chunks": "CHK",
    "grammar": "GRM",
    "contrast": "CON",
    "audit": "AUD",
}

NEW_CONTENT_SECTIONS = {
    "1": {"type": "vocabulary", "content": "韩语", "chinese": "中文", "flag": "是否进入复习队列"},
    "2": {"type": "phrases", "content": "表达", "chinese": "中文", "flag": "是否进入复习队列"},
    "3": {"type": "chunks", "content": "表达", "chinese": "中文", "flag": "是否进入复习队列"},
    "4": {"type": "grammar", "content": "语法", "chinese": "中文", "flag": "是否进入复习队列"},
    "5": {"type": "contrast", "content": "A", "content_b": "B", "chinese": "区别", "flag": "是否进入复习队列"},
    "6": {"type": "audit", "content": "原答案 / 原理解", "chinese": "正确答案 / 正确理解", "flag": "是否进入高频回炉"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update MASTER_REVIEW_QUEUE.md from a daily log.")
    parser.add_argument("date", nargs="?", default=date.today().isoformat(), help="Daily log date in YYYY-MM-DD format.")
    return parser.parse_args()


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator_row(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(cell.replace(":", "").replace("-", "").strip() == "" for cell in cells)


def read_daily_text(target: date) -> str:
    path = DAILY_DIR / f"{target.isoformat()}_daily_log.md"
    if not path.exists():
        raise FileNotFoundError(f"Daily log not found: {path}")
    return path.read_text(encoding="utf-8")


def section_body(text: str, section_number: str) -> list[str]:
    lines = text.splitlines()
    start = -1
    for index, line in enumerate(lines):
        if line.startswith(f"## {section_number}."):
            start = index + 1
            break
    if start == -1:
        return []
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return lines[start:end]


def parse_bullet_records(lines: list[str], first_keys: set[str]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        item = stripped[2:].strip()
        if "：" in item:
            key, value = item.split("：", 1)
        elif ":" in item:
            key, value = item.split(":", 1)
        else:
            continue
        key = key.strip()
        value = value.strip()
        if key in first_keys and current and any(current.values()):
            records.append(current)
            current = {}
        current[key] = value

    if current and any(current.values()):
        records.append(current)
    return records


def parse_review_results(text: str) -> tuple[list[dict[str, str]], list[str]]:
    lines = section_body(text, "8")
    errors: list[str] = []
    table: list[list[str]] = []

    for line in lines:
        if line.strip().startswith("|"):
            if is_separator_row(line):
                continue
            table.append(split_table_row(line))

    if not table:
        return [], errors

    header = table[0]
    results: list[dict[str, str]] = []
    valid_results = {"correct", "wrong", "uncertain"}
    for row in table[1:]:
        data = {header[index]: row[index] if index < len(row) else "" for index in range(len(header))}
        result = data.get("结果", "").strip()
        if not data.get("ID", "").strip() and not result:
            continue
        if result not in valid_results:
            errors.append(f"Invalid review result for {data.get('ID', '')}: {result}")
            continue
        results.append(data)
    return results, errors


def normalize_flag(value: str) -> str:
    value = value.strip().lower()
    if value in {"yes", "y", "true", "1", "是"}:
        return "yes"
    if value in {"no", "n", "false", "0", "否"}:
        return "no"
    if value in {"pending", "待确认", "待確認"}:
        return "pending"
    return "blank"


def parse_new_entries(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for section_number, config in NEW_CONTENT_SECTIONS.items():
        first_keys = {config["content"]}
        records = parse_bullet_records(section_body(text, section_number), first_keys)
        for record in records:
            content = record.get(config["content"], "").strip()
            if config.get("content_b"):
                second = record.get(config["content_b"], "").strip()
                if content and second:
                    content = f"{content} vs {second}"
            chinese = record.get(config["chinese"], "").strip() or "待确认"
            if not content:
                continue
            flag = normalize_flag(record.get(config["flag"], ""))
            if flag == "no":
                continue
            entries.append(
                {
                    "type": config["type"],
                    "content": content,
                    "chinese": chinese,
                    "source": record.get("来源", "").strip(),
                    "level": record.get("初始等级", "").strip() or "待确认",
                    "flag": flag,
                    "high_frequency": config["type"] == "audit" and flag == "yes",
                }
            )
    return entries


def to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def next_id(rows: list[dict[str, str]], row_type: str) -> str:
    prefix = PREFIX_BY_TYPE[row_type]
    highest = 0
    for row in rows:
        row_id = row.get("ID", "")
        if not row_id.startswith(prefix + "-"):
            continue
        try:
            highest = max(highest, int(row_id.split("-", 1)[1]))
        except ValueError:
            continue
    return f"{prefix}-{highest + 1:04d}"


def row_exists(rows: list[dict[str, str]], row_type: str, content: str) -> bool:
    return any(row.get("类型") == row_type and row.get("内容") == content for row in rows)


def add_new_entries(rows: list[dict[str, str]], entries: list[dict[str, str]], target: date) -> list[str]:
    messages: list[str] = []
    for entry in entries:
        row_type = entry["type"]
        content = entry["content"]
        if row_exists(rows, row_type, content):
            messages.append(f"Skipped duplicate: {row_type} {content}")
            continue

        source = entry["source"] or f"daily/{target.isoformat()}_daily_log.md"
        status = "pending"
        r_stage = "R0"
        next_review = "待安排"
        last_review = target.isoformat()

        if entry["flag"] == "yes":
            status = "active"
            next_review = target.isoformat()
        if entry["high_frequency"]:
            status = "high-frequency"
            r_stage = "R1"
            next_review = (target + timedelta(days=1)).isoformat()

        rows.append(
            {
                "ID": next_id(rows, row_type),
                "类型": row_type,
                "内容": content,
                "中文/说明": entry["chinese"],
                "来源文件": source,
                "当前等级": entry["level"],
                "当前R阶段": r_stage,
                "连续正确": "0",
                "错误次数": "0",
                "上次复习": last_review,
                "下次复习": next_review,
                "状态": status,
            }
        )
        messages.append(f"Added {row_type}: {content} ({status})")
    return messages


def closer_date(first: date, second: date) -> date:
    return first if first <= second else second


def next_date_for_correct(target: date, r_stage: str, consecutive: int) -> str:
    r_date = target + timedelta(days=R_INTERVALS.get(r_stage, 0))
    streak_date: date | None = None
    if consecutive >= 5:
        streak_date = target + timedelta(days=30)
    elif consecutive >= 3:
        streak_date = target + timedelta(days=7)
    elif consecutive >= 2:
        streak_date = target + timedelta(days=3)
    if streak_date is None:
        return r_date.isoformat()
    return closer_date(r_date, streak_date).isoformat()


def apply_review_result(row: dict[str, str], result: dict[str, str], target: date) -> None:
    outcome = result["结果"].strip()
    current_r = row.get("当前R阶段", DEFAULTS["当前R阶段"]) or DEFAULTS["当前R阶段"]
    new_level = result.get("新等级", "").strip()
    if new_level:
        row["当前等级"] = new_level
    row["上次复习"] = target.isoformat()

    if outcome == "correct":
        consecutive = to_int(row.get("连续正确", "0")) + 1
        row["连续正确"] = str(consecutive)
        next_r = NEXT_R.get(current_r, "R1")
        if consecutive >= 8 or next_r == "archived":
            row["当前R阶段"] = "R7"
            row["状态"] = "archived"
            row["下次复习"] = ""
            return
        row["当前R阶段"] = next_r
        row["状态"] = "active"
        row["下次复习"] = next_date_for_correct(target, next_r, consecutive)
        return

    if outcome == "wrong":
        rollback = ROLLBACK_R.get(current_r, "R1")
        row["连续正确"] = "0"
        row["错误次数"] = str(to_int(row.get("错误次数", "0")) + 1)
        row["当前R阶段"] = rollback
        row["状态"] = "high-frequency"
        row["下次复习"] = (target + timedelta(days=R_INTERVALS.get(rollback, 0))).isoformat()
        return

    if outcome == "uncertain":
        row["连续正确"] = "0"
        row["当前R阶段"] = "R1"
        row["状态"] = "high-frequency"
        row["下次复习"] = (target + timedelta(days=1)).isoformat()


def update_existing_rows(rows: list[dict[str, str]], results: list[dict[str, str]], target: date) -> list[str]:
    messages: list[str] = []
    by_id = {row["ID"]: row for row in rows}
    for result in results:
        row_id = result.get("ID", "").strip()
        row = by_id.get(row_id)
        if row is None:
            messages.append(f"Review result ID not found: {row_id}")
            continue
        apply_review_result(row, result, target)
        messages.append(f"Updated {row_id}: {result['结果']}")
    return messages


def main() -> int:
    args = parse_args()
    target = parse_date(args.date)
    daily_text = read_daily_text(target)

    rows = read_queue_rows(QUEUE_PATH)
    review_results, errors = parse_review_results(daily_text)
    if errors:
        for error in errors:
            print(error)
        return 2

    new_entries = parse_new_entries(daily_text)
    update_messages = update_existing_rows(rows, review_results, target)
    add_messages = add_new_entries(rows, new_entries, target)

    write_queue_rows(rows, QUEUE_PATH)

    tomorrow = target + timedelta(days=1)
    tomorrow_due = due_rows(rows, tomorrow)
    tomorrow_plan = write_review_plan(tomorrow, tomorrow_due)

    print("Update summary")
    print(f"- Review results processed: {len(review_results)}")
    print(f"- New entries processed: {len(new_entries)}")
    print(f"- Queue rows total: {len(rows)}")
    print(f"- Tomorrow review plan: {tomorrow_plan}")
    print(f"- Tomorrow due items: {len(tomorrow_due)}")
    for message in update_messages + add_messages:
        print(f"- {sanitize_cell(message)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
