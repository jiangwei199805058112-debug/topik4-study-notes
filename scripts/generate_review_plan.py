from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "MASTER_REVIEW_QUEUE.md"
REVIEW_DIR = ROOT / "review"

QUEUE_COLUMNS = [
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

DEFAULTS = {
    "当前等级": "待确认",
    "当前R阶段": "R0",
    "连续正确": "0",
    "错误次数": "0",
    "上次复习": "",
    "下次复习": "待安排",
    "状态": "pending",
}

TYPE_LABELS = {
    "vocabulary": "核心单词",
    "phrases": "固定搭配",
    "chunks": "句型块",
    "grammar": "语法",
    "contrast": "易混对比",
    "audit": "审校修正",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a TOPIK review plan from MASTER_REVIEW_QUEUE.md.")
    parser.add_argument("date", nargs="?", default=date.today().isoformat(), help="Target date in YYYY-MM-DD format.")
    return parser.parse_args()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator_row(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(cell.replace(":", "").replace("-", "").strip() == "" for cell in cells)


def sanitize_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").replace("|", "/").strip()


def find_main_queue_table(lines: list[str]) -> tuple[int, int]:
    in_queue_section = False
    start = -1
    for index, line in enumerate(lines):
        if line.startswith("## 4."):
            in_queue_section = True
            continue
        if in_queue_section and line.startswith("## ") and not line.startswith("## 4."):
            break
        if in_queue_section and line.startswith("| ID |"):
            start = index
            break
    if start == -1:
        raise ValueError("Could not find the main review queue table.")

    end = start + 1
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return start, end


def read_queue_rows(path: Path = QUEUE_PATH) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Queue file not found: {path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = find_main_queue_table(lines)
    header = split_table_row(lines[start])
    rows: list[dict[str, str]] = []

    for line in lines[start + 1 : end]:
        if is_separator_row(line):
            continue
        cells = split_table_row(line)
        raw = {header[index]: cells[index] if index < len(cells) else "" for index in range(len(header))}
        normalized = {column: raw.get(column, DEFAULTS.get(column, "")) for column in QUEUE_COLUMNS}
        for column, default in DEFAULTS.items():
            if not normalized.get(column):
                normalized[column] = default
        rows.append(normalized)
    return rows


def render_queue_table(rows: Iterable[dict[str, str]]) -> list[str]:
    lines = [
        "| " + " | ".join(QUEUE_COLUMNS) + " |",
        "|---|---|---|---|---|---|---|---:|---:|---|---|---|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(sanitize_cell(row.get(column, DEFAULTS.get(column, ""))) for column in QUEUE_COLUMNS) + " |")
    return lines


def write_queue_rows(rows: list[dict[str, str]], path: Path = QUEUE_PATH) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = find_main_queue_table(lines)
    new_lines = lines[:start] + render_queue_table(rows) + lines[end:]
    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def parse_due_date(value: str) -> date | None:
    value = value.strip()
    if not value or value == "待安排":
        return None
    try:
        return parse_date(value)
    except ValueError:
        return None


def due_rows(rows: Iterable[dict[str, str]], target_date: date) -> list[dict[str, str]]:
    due: list[dict[str, str]] = []
    for row in rows:
        status = row.get("状态", "").strip()
        if status in {"archived", "pending"}:
            continue
        next_review = parse_due_date(row.get("下次复习", ""))
        if next_review is None:
            continue
        if next_review <= target_date:
            due.append(row)
    return due


def plan_table(rows: list[dict[str, str]], audit: bool = False) -> list[str]:
    if audit:
        lines = ["| ID | 内容 | 中文/错因 | 当前R阶段 | 下次复习 |", "|---|---|---|---|---|"]
        for row in rows:
            lines.append(
                f"| {sanitize_cell(row.get('ID'))} | {sanitize_cell(row.get('内容'))} | "
                f"{sanitize_cell(row.get('中文/说明'))} | {sanitize_cell(row.get('当前R阶段'))} | "
                f"{sanitize_cell(row.get('下次复习'))} |"
            )
        return lines

    lines = ["| ID | 内容 | 中文 | 当前等级 | 当前R阶段 | 下次复习 |", "|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(
            f"| {sanitize_cell(row.get('ID'))} | {sanitize_cell(row.get('内容'))} | "
            f"{sanitize_cell(row.get('中文/说明'))} | {sanitize_cell(row.get('当前等级'))} | "
            f"{sanitize_cell(row.get('当前R阶段'))} | {sanitize_cell(row.get('下次复习'))} |"
        )
    return lines


def write_review_plan(target: date, rows: list[dict[str, str]]) -> Path:
    REVIEW_DIR.mkdir(exist_ok=True)
    target_text = target.isoformat()
    output_path = REVIEW_DIR / f"{target_text}_review_plan.md"

    regular: dict[str, list[dict[str, str]]] = {key: [] for key in ["vocabulary", "phrases", "chunks", "grammar", "contrast"]}
    audit_or_high_frequency: list[dict[str, str]] = []
    for row in rows:
        row_type = row.get("类型", "").strip()
        if row_type == "audit" or row.get("状态", "").strip() == "high-frequency":
            audit_or_high_frequency.append(row)
        elif row_type in regular:
            regular[row_type].append(row)

    lines = [
        f"# {target_text} Review Plan",
        "",
        "## 0. 使用说明",
        "",
        "先复习本文件中所有到期内容。  ",
        "复习完成后，把结果填写到：",
        "",
        f"daily/{target_text}_daily_log.md",
        "",
        "结果字段只能使用：",
        "",
        "- correct",
        "- wrong",
        "- uncertain",
        "",
        "---",
        "",
        "## 1. 今日必须复习",
        "",
    ]

    if not rows:
        lines += ["今日没有到期复习内容。", ""]

    section_titles = [
        ("vocabulary", "### 1.1 核心单词"),
        ("phrases", "### 1.2 固定搭配"),
        ("chunks", "### 1.3 句型块"),
        ("grammar", "### 1.4 语法"),
        ("contrast", "### 1.5 易混对比"),
    ]
    for key, title in section_titles:
        lines += [title, "", *plan_table(regular[key]), ""]

    lines += ["### 1.6 审校修正 / 高频回炉", "", *plan_table(audit_or_high_frequency, audit=True), ""]
    lines += [
        "---",
        "",
        "## 2. 今日复习结果填写区",
        "",
        f"复习后，请把结果复制或填写到 daily/{target_text}_daily_log.md 的“今日复习结果”。",
        "",
        "| ID | 内容 | 类型 | 原R阶段 | 结果 | 错因 | 新等级 | 备注 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {sanitize_cell(row.get('ID'))} | {sanitize_cell(row.get('内容'))} | "
            f"{sanitize_cell(row.get('类型'))} | {sanitize_cell(row.get('当前R阶段'))} |  |  |  |  |"
        )
    lines += [
        "",
        "---",
        "",
        "## 3. 今日新内容入口",
        "",
        "今天新学内容请记录到：",
        "",
        f"daily/{target_text}_daily_log.md",
    ]

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    args = parse_args()
    target = parse_date(args.date)
    rows = read_queue_rows()
    selected = due_rows(rows, target)
    output_path = write_review_plan(target, selected)
    print(f"Generated review plan: {output_path}")
    print(f"Due items: {len(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
