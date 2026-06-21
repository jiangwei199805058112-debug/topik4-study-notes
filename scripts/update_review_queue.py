from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True
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

REVIEW_RESULT_HEADER = ["ID", "内容", "类型", "原R阶段", "结果", "错因", "新等级", "备注"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update MASTER_REVIEW_QUEUE.md from a daily log.")
    parser.add_argument("date", nargs="?", default=date.today().isoformat(), help="Daily log date in YYYY-MM-DD format.")
    parser.add_argument("--dry-run", action="store_true", help="Preview queue and review plan changes without writing files.")
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


def iter_markdown_tables(lines: list[str]) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip().startswith("|"):
            index += 1
            continue
        if index + 1 >= len(lines) or not is_separator_row(lines[index + 1]):
            index += 1
            continue

        header = split_table_row(line)
        rows: list[list[str]] = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            if not is_separator_row(lines[cursor]):
                rows.append(split_table_row(lines[cursor]))
            cursor += 1
        tables.append((header, rows))
        index = cursor
    return tables


def declared_review_total(text: str) -> int | None:
    totals: list[int] = []
    for line in section_body(text, "8"):
        match = re.search(r"(?:总复习数量|total)\s*[：:]\s*(\d+)", line, flags=re.IGNORECASE)
        if match:
            totals.append(int(match.group(1)))
    if not totals:
        return None
    return max(totals)


def parse_review_results(text: str) -> tuple[list[dict[str, str]], list[str], int]:
    lines = section_body(text, "8")
    errors: list[str] = []
    skipped_tables = 0
    results: list[dict[str, str]] = []
    valid_results = {"correct", "wrong", "uncertain"}

    for header, table_rows in iter_markdown_tables(lines):
        if header != REVIEW_RESULT_HEADER:
            skipped_tables += 1
            continue
        for row in table_rows:
            data = {header[index]: row[index] if index < len(row) else "" for index in range(len(header))}
            result = data.get("结果", "").strip()
            if not data.get("ID", "").strip() and not result:
                continue
            if result not in valid_results:
                errors.append(f"Invalid review result for {data.get('ID', '')}: {result}")
                continue
            results.append(data)

    expected_total = declared_review_total(text)
    if expected_total and expected_total > 0 and not results:
        errors.append(
            f"Daily log declares review total {expected_total}, but no exact review result table was parsed."
        )
    return results, errors, skipped_tables


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
        row["下次复习"] = (target + timedelta(days=1)).isoformat()
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


def snapshot_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {
        row["ID"]: {
            "状态": row.get("状态", ""),
            "下次复习": row.get("下次复习", ""),
        }
        for row in rows
    }


def changed_existing_rows(before: dict[str, dict[str, str]], rows: list[dict[str, str]]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for row in rows:
        row_id = row.get("ID", "")
        old = before.get(row_id)
        if old is None:
            continue
        old_status = old.get("状态", "")
        old_next = old.get("下次复习", "")
        new_status = row.get("状态", "")
        new_next = row.get("下次复习", "")
        if old_status == new_status and old_next == new_next:
            continue
        changes.append(
            {
                "ID": row_id,
                "内容": row.get("内容", ""),
                "old_status": old_status,
                "new_status": new_status,
                "old_next_due_date": old_next,
                "new_next_due_date": new_next,
            }
        )
    return changes


def print_dry_run_changes(changes: list[dict[str, str]]) -> None:
    print("Dry-run existing row changes:")
    if not changes:
        print("- No existing row status/date changes.")
        return
    print("| ID | 内容 | old_status | new_status | old_next_due_date | new_next_due_date |")
    print("|---|---|---|---|---|---|")
    for change in changes:
        print(
            f"| {sanitize_cell(change['ID'])} | {sanitize_cell(change['内容'])} | "
            f"{sanitize_cell(change['old_status'])} | {sanitize_cell(change['new_status'])} | "
            f"{sanitize_cell(change['old_next_due_date'])} | {sanitize_cell(change['new_next_due_date'])} |"
        )


def main() -> int:
    args = parse_args()
    target = parse_date(args.date)
    daily_text = read_daily_text(target)

    rows = read_queue_rows(QUEUE_PATH)
    review_results, errors, skipped_tables = parse_review_results(daily_text)
    print("Parse summary")
    print(f"- parsed_results: {len(review_results)}")
    print(f"- errors: {len(errors)}")
    print(f"- skipped_tables: {skipped_tables}")
    if errors:
        for error in errors:
            print(error)
        return 2

    new_entries = parse_new_entries(daily_text)
    before = snapshot_rows(rows)
    update_messages = update_existing_rows(rows, review_results, target)
    add_messages = add_new_entries(rows, new_entries, target)
    row_changes = changed_existing_rows(before, rows)

    tomorrow = target + timedelta(days=1)
    tomorrow_due = due_rows(rows, tomorrow)

    if args.dry_run:
        print("Dry-run: no files written.")
        print_dry_run_changes(row_changes)
        print(f"Tomorrow due items if applied: {len(tomorrow_due)}")
    else:
        write_queue_rows(rows, QUEUE_PATH)
        tomorrow_plan = write_review_plan(tomorrow, tomorrow_due)

    print("Update summary")
    print(f"- Review results processed: {len(review_results)}")
    print(f"- New entries processed: {len(new_entries)}")
    print(f"- Queue rows total: {len(rows)}")
    if args.dry_run:
        print("- Tomorrow review plan: not written (--dry-run)")
    else:
        print(f"- Tomorrow review plan: {tomorrow_plan}")
    print(f"- Tomorrow due items: {len(tomorrow_due)}")
    for message in update_messages + add_messages:
        print(f"- {sanitize_cell(message)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
