from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "MASTER_REVIEW_QUEUE.md"

TYPE_ORDER = ["vocabulary", "phrases", "chunks", "grammar", "contrast", "audit"]
MAIN_HEADER = [
    "ID",
    "类型",
    "内容",
    "中文/说明",
    "来源文件",
    "当前等级",
    "当前R阶段",
    "连续正确",
    "错误次数",
    "上次复习",
    "下次复习",
    "状态",
]
HIGH_FREQUENCY_HEADER = ["ID", "类型", "内容", "错因", "来源文件", "回炉原因", "下次复习"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit TOPIK review queue health without modifying files.")
    parser.add_argument("date", nargs="?", default=date.today().isoformat(), help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--samples", type=int, default=20, help="Number of sample IDs to print per issue.")
    return parser.parse_args()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def table_after_heading(lines: list[str], heading: str) -> list[dict[str, str]]:
    heading_index = next((index for index, line in enumerate(lines) if line.strip() == heading), -1)
    if heading_index == -1:
        return []
    for index in range(heading_index + 1, len(lines)):
        if lines[index].startswith("|"):
            header = split_table_row(lines[index])
            rows: list[dict[str, str]] = []
            cursor = index + 2
            while cursor < len(lines) and lines[cursor].startswith("|"):
                cells = split_table_row(lines[cursor])
                if len(cells) == len(header):
                    rows.append(dict(zip(header, cells)))
                cursor += 1
            return rows
    return []


def main_queue_rows(lines: list[str]) -> list[dict[str, str]]:
    in_queue_section = False
    for index, line in enumerate(lines):
        if line.startswith("## 4."):
            in_queue_section = True
            continue
        if in_queue_section and line.startswith("## ") and not line.startswith("## 4."):
            break
        if in_queue_section and line.startswith("| ID |"):
            header = split_table_row(line)
            if header != MAIN_HEADER:
                raise ValueError(f"Unexpected main queue header: {header}")
            rows: list[dict[str, str]] = []
            cursor = index + 2
            while cursor < len(lines) and lines[cursor].startswith("|"):
                cells = split_table_row(lines[cursor])
                if len(cells) == len(header):
                    rows.append(dict(zip(header, cells)))
                cursor += 1
            return rows
    raise ValueError("Could not find main queue table.")


def parse_due_date(value: str) -> date | None:
    value = value.strip()
    if not value or value == "待安排":
        return None
    try:
        return parse_date(value)
    except ValueError:
        return None


def count_types(rows: list[dict[str, str]]) -> Counter[str]:
    return Counter(row.get("类型", "") for row in rows)


def print_type_counts(title: str, rows: list[dict[str, str]]) -> None:
    counts = count_types(rows)
    print(title)
    print(f"- total: {len(rows)}")
    for row_type in TYPE_ORDER:
        print(f"- {row_type}: {counts.get(row_type, 0)}")


def print_samples(title: str, rows: list[dict[str, str]], limit: int) -> None:
    print(title)
    if not rows:
        print("- none")
        return
    for row in rows[:limit]:
        print(
            f"- {row.get('ID', '')} | {row.get('类型', '')} | {row.get('内容', '')} | "
            f"status={row.get('状态', '')} | next_due={row.get('下次复习', '')}"
        )


def future_due_rows(rows: list[dict[str, str]], start: date) -> list[tuple[date, list[dict[str, str]]]]:
    results: list[tuple[date, list[dict[str, str]]]] = []
    for offset in range(1, 8):
        target = start + timedelta(days=offset)
        due = [
            row
            for row in rows
            if row.get("状态", "").strip() not in {"archived", "pending", "suspended"}
            and parse_due_date(row.get("下次复习", "")) == target
        ]
        results.append((target, due))
    return results


def section5_inconsistencies(
    main_rows: list[dict[str, str]], section_rows: list[dict[str, str]]
) -> tuple[set[str], set[str], set[str]]:
    main_by_id = {row["ID"]: row for row in main_rows}
    section_by_id = {row["ID"]: row for row in section_rows}
    main_high_frequency_ids = {row["ID"] for row in main_rows if row.get("状态") == "high-frequency"}

    section_only = set(section_by_id) - main_high_frequency_ids
    main_only = main_high_frequency_ids - set(section_by_id)
    due_mismatch = {
        row_id
        for row_id in set(section_by_id) & main_high_frequency_ids
        if section_by_id[row_id].get("下次复习", "") != main_by_id[row_id].get("下次复习", "")
    }
    return section_only, main_only, due_mismatch


def main() -> int:
    args = parse_args()
    start = parse_date(args.date)
    lines = QUEUE_PATH.read_text(encoding="utf-8").splitlines()
    main_rows = main_queue_rows(lines)
    section5_rows = table_after_heading(lines, "## 5. 高频回炉区")

    high_frequency_waiting = [
        row for row in main_rows if row.get("状态") == "high-frequency" and row.get("下次复习") == "待安排"
    ]
    active_waiting = [row for row in main_rows if row.get("状态") == "active" and row.get("下次复习") == "待安排"]
    pending = [row for row in main_rows if row.get("状态") == "pending"]

    print("# Review Queue Audit")
    print(f"- queue: {QUEUE_PATH}")
    print(f"- start_date: {start.isoformat()}")
    print(f"- total_rows: {len(main_rows)}")
    print("")

    print_type_counts("## high-frequency / 待安排", high_frequency_waiting)
    print_samples("### high-frequency / 待安排 samples", high_frequency_waiting, args.samples)
    print("")

    print_type_counts("## active / 待安排", active_waiting)
    print_samples("### active / 待安排 samples", active_waiting, args.samples)
    print("")

    print_type_counts("## pending", pending)
    print("")

    print("## Future 7 Days Due")
    print("| date | total | vocabulary | phrases | chunks | grammar | contrast | audit |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for target, due in future_due_rows(main_rows, start):
        counts = count_types(due)
        print(
            f"| {target.isoformat()} | {len(due)} | {counts.get('vocabulary', 0)} | "
            f"{counts.get('phrases', 0)} | {counts.get('chunks', 0)} | {counts.get('grammar', 0)} | "
            f"{counts.get('contrast', 0)} | {counts.get('audit', 0)} |"
        )
    print("")

    section_only, main_only, due_mismatch = section5_inconsistencies(main_rows, section5_rows)
    inconsistent_ids = section_only | main_only | due_mismatch
    print("## Section 5 vs Main Table")
    print(f"- section5_rows: {len(section5_rows)}")
    print(f"- inconsistent_id_count: {len(inconsistent_ids)}")
    print(f"- section5_not_current_high_frequency: {len(section_only)}")
    print(f"- main_high_frequency_missing_from_section5: {len(main_only)}")
    print(f"- shared_id_due_mismatch: {len(due_mismatch)}")
    if inconsistent_ids:
        sample = sorted(inconsistent_ids)[: args.samples]
        print("- inconsistent_id_samples: " + ", ".join(sample))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
