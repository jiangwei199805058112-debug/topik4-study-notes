from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
sys.path.insert(0, str(SCRIPT_DIR))

from audit_review_queue import section5_inconsistencies, table_after_heading  # noqa: E402
from generate_review_plan import QUEUE_PATH, due_rows, parse_date, read_queue_rows  # noqa: E402


TYPE_ORDER = ["vocabulary", "phrases", "chunks", "grammar", "contrast", "audit"]
REVIEW_RESULT_HEADER = ["ID", "内容", "类型", "原R阶段", "结果", "错因", "新等级", "备注"]
LEARNING_EVENTS_PATH = ROOT / "data" / "learning_events.jsonl"
REVIEW_EVENTS_PATH = ROOT / "data" / "review_events.jsonl"
SCORE_LOG_PATH = ROOT / "data" / "exam_diagnostics" / "topik_score_log.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified read-only TOPIK daily workflow CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    today = subparsers.add_parser("today", help="Print today's learning and review task report.")
    today.add_argument("--date", default=date.today().isoformat(), help="Target date in YYYY-MM-DD format.")

    check = subparsers.add_parser("check", help="Run start/end-of-day safety checks.")
    check.add_argument("--date", default=date.today().isoformat(), help="Target date in YYYY-MM-DD format.")

    focus = subparsers.add_parser("focus", help="Print a short daily focus note.")
    focus.add_argument("--date", default=date.today().isoformat(), help="Target date in YYYY-MM-DD format.")

    events = subparsers.add_parser("events", help="Print structured learning/review events for a date.")
    events.add_argument("--date", default=date.today().isoformat(), help="Target date in YYYY-MM-DD format.")

    subparsers.add_parser("score", help="Print the current TOPIK score snapshot.")
    return parser.parse_args()


def parse_target(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def repo_status() -> dict[str, Any]:
    branch = run_command(["git", "branch", "--show-current"]).stdout.strip()
    head = run_command(["git", "rev-parse", "HEAD"]).stdout.strip()
    status = run_command(["git", "status", "--porcelain"]).stdout.splitlines()
    return {"branch": branch, "head": head, "clean": not status, "status_lines": status}


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator_row(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(cell.replace(":", "").replace("-", "").strip() == "" for cell in cells)


def iter_markdown_tables(lines: list[str]) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip().startswith("|") or index + 1 >= len(lines):
            index += 1
            continue
        if not is_separator_row(lines[index + 1]):
            index += 1
            continue
        header = split_table_row(lines[index])
        rows: list[list[str]] = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            if not is_separator_row(lines[cursor]):
                rows.append(split_table_row(lines[cursor]))
            cursor += 1
        tables.append((header, rows))
        index = cursor
    return tables


def read_review_plan_rows(target: date) -> tuple[Path, list[dict[str, str]] | None]:
    path = ROOT / "review" / f"{target.isoformat()}_review_plan.md"
    if not path.exists():
        return path, None

    text = path.read_text(encoding="utf-8")
    for header, table_rows in iter_markdown_tables(text.splitlines()):
        if header != REVIEW_RESULT_HEADER:
            continue
        rows: list[dict[str, str]] = []
        for row in table_rows:
            values = {header[index]: row[index] if index < len(row) else "" for index in range(len(header))}
            if values.get("ID"):
                rows.append(values)
        return path, rows
    return path, []


def count_types(rows: list[dict[str, str]]) -> Counter[str]:
    return Counter(row.get("类型", "") for row in rows)


def print_type_counts(rows: list[dict[str, str]]) -> None:
    counts = count_types(rows)
    for row_type in TYPE_ORDER:
        print(f"- {row_type}: {counts.get(row_type, 0)}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL in {path} line {line_number}: {exc}") from exc
        if isinstance(value, dict):
            events.append(value)
    return events


def int_value(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def daily_log_path(target: date) -> Path:
    return ROOT / "daily" / f"{target.isoformat()}_daily_log.md"


def declared_review_total(text: str) -> int | None:
    totals = [
        int(match.group(1))
        for match in re.finditer(r"(?:总复习数量|total)\s*[：:]\s*(\d+)", text, flags=re.IGNORECASE)
    ]
    return max(totals) if totals else None


def declared_review_counts(text: str) -> dict[str, int | None]:
    result: dict[str, int | None] = {"total": declared_review_total(text)}
    for key in ("correct", "wrong", "uncertain"):
        match = re.search(rf"{key}\s*[：:]\s*(\d+)", text, flags=re.IGNORECASE)
        result[key] = int(match.group(1)) if match else None
    return result


def previous_review_summary(target: date) -> dict[str, int | None]:
    previous = target - timedelta(days=1)
    total: int | None = None
    wrong = 0
    uncertain = 0

    for event in read_jsonl(REVIEW_EVENTS_PATH):
        if event.get("date") != previous.isoformat():
            continue
        event_total = int_value(event.get("total"))
        if event_total:
            total = max(total or 0, event_total)
        wrong += int_value(event.get("wrong"))
        uncertain += int_value(event.get("uncertain"))
        if event.get("result") == "wrong":
            wrong += 1
        if event.get("result") == "uncertain":
            uncertain += 1

    if total is None:
        path = daily_log_path(previous)
        if path.exists():
            counts = declared_review_counts(path.read_text(encoding="utf-8"))
            total = counts["total"]
            wrong = counts["wrong"] or wrong
            uncertain = counts["uncertain"] or uncertain

    return {"date": previous.isoformat(), "total": total, "wrong": wrong, "uncertain": uncertain}


def score_rows() -> list[dict[str, str]]:
    if not SCORE_LOG_PATH.exists():
        return []
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in SCORE_LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = split_table_row(line)
        if cells and cells[0] == "日期":
            header = cells
            continue
        if header and len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
    return rows


def latest_score(subject: str, rows: list[dict[str, str]]) -> dict[str, str] | None:
    for row in reversed(rows):
        if row.get("科目") == subject:
            return row
    return None


def score_number(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"(\d+)\s*/\s*100", value.strip())
    return int(match.group(1)) if match else None


def focus_snapshot(target: date, due_total: int | None = None) -> dict[str, Any]:
    previous = previous_review_summary(target)
    weak_total = (previous["wrong"] or 0) + (previous["uncertain"] or 0)
    scores = score_rows()
    listening_row = latest_score("듣기", scores)
    reading_row = latest_score("읽기", scores)
    writing_row = latest_score("쓰기", scores)
    listening = score_number(listening_row.get("分数") if listening_row else None)
    reading = score_number(reading_row.get("分数") if reading_row else None)
    writing = score_number(writing_row.get("分数") if writing_row else None)

    priorities: list[str] = []
    if reading is None or reading < 55:
        priorities.append("reading")
    if writing is None or writing < 35:
        priorities.append("writing")
    if listening is None or listening < 60:
        priorities.append("listening")
    if not priorities:
        priorities.append("review stability")

    should_add_new = True
    if due_total is not None and due_total > 20:
        should_add_new = False
    if previous["total"] is not None and previous["total"] > 50:
        should_add_new = False
    if weak_total > 5:
        should_add_new = False

    return {
        "previous": previous,
        "weak_total": weak_total,
        "priorities": priorities,
        "reading": f"{reading}/100; sentence structure, context inference, long reading" if reading is not None else "not tested",
        "writing": "not tested / weak; build sentence and paragraph skeletons"
        if writing is None
        else f"{writing}/100; build sentence and paragraph skeletons",
        "listening": f"{listening}/100; keyword location and long dialogue handling"
        if listening is not None
        else "not tested",
        "new_content_allowed": should_add_new,
        "backlog_allowed": should_add_new,
    }


def queue_health(target: date) -> dict[str, Any]:
    rows = read_queue_rows()
    master_due = due_rows(rows, target)
    high_frequency_waiting = [
        row for row in rows if row.get("状态") == "high-frequency" and row.get("下次复习") == "待安排"
    ]
    active_waiting = [row for row in rows if row.get("状态") == "active" and row.get("下次复习") == "待安排"]
    pending = [row for row in rows if row.get("状态") == "pending"]
    section_rows = table_after_heading(QUEUE_PATH.read_text(encoding="utf-8").splitlines(), "## 5. 高频回炉区")
    section_only, main_only, due_mismatch = section5_inconsistencies(rows, section_rows)
    return {
        "rows": rows,
        "master_due": master_due,
        "master_due_counts": count_types(master_due),
        "pending": pending,
        "high_frequency_waiting": high_frequency_waiting,
        "active_waiting": active_waiting,
        "section5_rows": len(section_rows),
        "section5_inconsistent": len(section_only | main_only | due_mismatch),
    }


def print_repo_status(status: dict[str, Any]) -> None:
    print(f"- branch: {status['branch']}")
    print(f"- HEAD: {status['head']}")
    print(f"- working tree: {'clean' if status['clean'] else 'not clean'}")
    if status["status_lines"]:
        for line in status["status_lines"][:10]:
            print(f"- status: {line}")
        if len(status["status_lines"]) > 10:
            print(f"- status: ... {len(status['status_lines']) - 10} more")


def today_command(target: date) -> int:
    status = repo_status()
    plan_path, plan_rows = read_review_plan_rows(target)
    health = queue_health(target)
    due_total = len(plan_rows) if plan_rows is not None else None
    focus = focus_snapshot(target, due_total)

    print(f"# TOPIK Daily Task Report - {target.isoformat()}")
    print("")
    print("## 1. Repository status")
    print_repo_status(status)
    print("")

    print("## 2. Today review due")
    print(f"- review plan: {plan_path.relative_to(ROOT)}")
    if plan_rows is None:
        print("- review plan missing; do not proceed until generated intentionally.")
        print("- due total: unknown")
    else:
        print(f"- due total: {len(plan_rows)}")
        print_type_counts(plan_rows)
        master_ids = {row.get("ID") for row in health["master_due"]}
        plan_ids = {row.get("ID") for row in plan_rows}
        match = plan_ids == master_ids
        print(f"- MASTER due match: {'yes' if match else 'no'}")
        if not match:
            print(f"- MASTER due total now: {len(health['master_due'])}")
    print("")

    print("## 3. Top priority")
    if plan_rows is None:
        print("- R1 / high-frequency items count: unknown")
    else:
        r1_count = sum(1 for row in plan_rows if row.get("原R阶段") == "R1")
        print(f"- R1 / high-frequency items count: {r1_count}")
    previous = focus["previous"]
    weak_total = focus["weak_total"]
    if previous["total"] is None and weak_total == 0:
        print("- wrong/uncertain from previous day: unavailable")
    else:
        print(
            f"- wrong/uncertain from previous day ({previous['date']}): "
            f"{previous['wrong']} wrong / {previous['uncertain']} uncertain / {weak_total} total"
        )
    print(f"- today's priority skills: {', '.join(focus['priorities'])}")
    print("")

    print("## 4. Daily focus")
    print(f"- reading: {focus['reading']}")
    print(f"- writing: {focus['writing']}")
    print(f"- listening: {focus['listening']}")
    print(f"- new content allowed: {'yes' if focus['new_content_allowed'] else 'no'}")
    print(f"- backlog should be touched: {'yes' if focus['backlog_allowed'] else 'no'}")
    print("")

    print("## 5. Recommended execution order")
    print("1. Clear review due")
    print("2. Record first-pass correct/wrong/uncertain")
    print("3. Do immediate wrong/uncertain 回炉")
    print("4. Do TOPIK专项 if energy remains")
    print("5. Do not activate pending/backlog unless explicitly allowed")
    print("")

    print("## 6. Warnings")
    print(f"- pending count: {len(health['pending'])}")
    print(f"- high-frequency / 待安排 count: {len(health['high_frequency_waiting'])}")
    print(f"- active / 待安排 count: {len(health['active_waiting'])}")
    overload = due_total is not None and due_total > 50
    print(f"- today is overload: {'yes' if overload else 'no'}")
    if plan_rows is not None and {row.get("ID") for row in plan_rows} != {row.get("ID") for row in health["master_due"]}:
        print("- review plan and current MASTER due set differ; check before writing back or regenerating plans.")
    return 0


def parse_update_dry_run(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in output.splitlines():
        bullet = re.match(r"^- ([A-Za-z_ ]+):\s*(.*)$", line.strip())
        if bullet:
            key = bullet.group(1).strip().lower().replace(" ", "_")
            parsed[key] = bullet.group(2).strip()
            continue
        tomorrow = re.match(r"^Tomorrow due items if applied:\s*(\d+)", line.strip())
        if tomorrow:
            parsed["tomorrow_due_items_if_applied"] = tomorrow.group(1)
    return parsed


def check_command(target: date) -> int:
    status = repo_status()
    health = queue_health(target)
    plan_path, plan_rows = read_review_plan_rows(target)
    daily_path = daily_log_path(target)
    learning_events = [event for event in read_jsonl(LEARNING_EVENTS_PATH) if event.get("date") == target.isoformat()]
    review_events = [event for event in read_jsonl(REVIEW_EVENTS_PATH) if event.get("date") == target.isoformat()]
    problems: list[str] = []
    warnings: list[str] = []

    if not status["clean"]:
        problems.append("working tree is not clean")

    if plan_rows is not None:
        plan_ids = {row.get("ID") for row in plan_rows}
        master_ids = {row.get("ID") for row in health["master_due"]}
        if plan_ids != master_ids:
            problems.append(
                f"review plan due set differs from current MASTER due set "
                f"(plan={len(plan_ids)}, master={len(master_ids)})"
            )

    if health["pending"]:
        warnings.append(f"pending rows exist: {len(health['pending'])}")
    if health["high_frequency_waiting"]:
        warnings.append(f"high-frequency / 待安排 rows exist: {len(health['high_frequency_waiting'])}")
    if health["active_waiting"]:
        warnings.append(f"active / 待安排 rows exist: {len(health['active_waiting'])}")
    if health["section5_inconsistent"]:
        warnings.append(f"section 5 derived view differs from main table: {health['section5_inconsistent']} IDs")

    update_summary: dict[str, str] = {}
    update_returncode: int | None = None
    update_stderr = ""
    declared_counts: dict[str, int | None] = {"total": None, "correct": None, "wrong": None, "uncertain": None}
    if daily_path.exists():
        daily_text = daily_path.read_text(encoding="utf-8")
        declared_counts = declared_review_counts(daily_text)
        update = run_command([sys.executable, str(SCRIPT_DIR / "update_review_queue.py"), target.isoformat(), "--dry-run"])
        update_returncode = update.returncode
        update_stderr = update.stderr.strip()
        update_summary = parse_update_dry_run(update.stdout)
        parsed_results = int_value(update_summary.get("parsed_results"))
        errors = int_value(update_summary.get("errors"))
        declared_total = declared_counts["total"] or 0
        if parsed_results == 0 and declared_total > 0:
            problems.append("daily log declares review results but dry-run parsed 0 rows")
        if errors:
            problems.append(f"update_review_queue dry-run reported {errors} errors")
        if update_returncode not in {0, None}:
            problems.append(f"update_review_queue dry-run exited {update_returncode}")
    else:
        warnings.append(f"daily log missing: {daily_path.relative_to(ROOT)}")

    print(f"# TOPIK System Check - {target.isoformat()}")
    print("")
    print("## Repository")
    print_repo_status(status)
    print("")

    print("## Learning events")
    print(f"- learning_events_today: {len(learning_events)}")
    event_types = Counter(str(event.get("event_type")) for event in learning_events)
    for event_type, count in sorted(event_types.items()):
        print(f"- {event_type}: {count}")
    print("")

    print("## Review events")
    print(f"- review_events_today: {len(review_events)}")
    review_types = Counter(str(event.get("event_type")) for event in review_events)
    for event_type, count in sorted(review_types.items()):
        print(f"- {event_type}: {count}")
    print("")

    print("## Queue audit")
    print(f"- plan: {plan_path.relative_to(ROOT)}")
    print(f"- plan_rows: {'missing' if plan_rows is None else len(plan_rows)}")
    print(f"- MASTER due rows now: {len(health['master_due'])}")
    for row_type in TYPE_ORDER:
        print(f"- MASTER due {row_type}: {health['master_due_counts'].get(row_type, 0)}")
    print(f"- pending: {len(health['pending'])}")
    print(f"- high-frequency / 待安排: {len(health['high_frequency_waiting'])}")
    print(f"- active / 待安排: {len(health['active_waiting'])}")
    print(f"- section5_inconsistent_id_count: {health['section5_inconsistent']}")
    print("")

    print("## Update-review dry-run")
    if not daily_path.exists():
        print("- skipped: daily log missing")
    else:
        print(f"- daily_log: {daily_path.relative_to(ROOT)}")
        print(f"- declared_total: {declared_counts['total']}")
        print(f"- declared_correct: {declared_counts['correct']}")
        print(f"- declared_wrong: {declared_counts['wrong']}")
        print(f"- declared_uncertain: {declared_counts['uncertain']}")
        print(f"- returncode: {update_returncode}")
        for key in ("parsed_results", "errors", "skipped_tables", "tomorrow_due_items_if_applied"):
            if key in update_summary:
                print(f"- {key}: {update_summary[key]}")
        if update_stderr:
            print(f"- stderr: {update_stderr}")
    print("")

    print("## Problems")
    if problems:
        for item in problems:
            print(f"- {item}")
    else:
        print("- none")
    print("")

    if warnings:
        print("## Warnings")
        for item in warnings:
            print(f"- {item}")
        print("")

    print("## Safe to proceed?")
    if problems:
        print("- NO")
    elif warnings:
        print("- WARN")
    else:
        print("- YES")
    return 0


def focus_command(target: date) -> int:
    _plan_path, plan_rows = read_review_plan_rows(target)
    due_total = len(plan_rows) if plan_rows is not None else len(due_rows(read_queue_rows(), target))
    focus = focus_snapshot(target, due_total)
    print(f"# Daily Focus - {target.isoformat()}")
    print(f"- Review first: yes (due {due_total})")
    print(f"- Skill priority: {', '.join(focus['priorities'])}")
    print(f"- Reading focus: {focus['reading']}")
    print(f"- Writing focus: {focus['writing']}")
    print(f"- Listening focus: {focus['listening']}")
    print(f"- New content allowed: {'yes' if focus['new_content_allowed'] else 'no'}")
    print(f"- Backlog allowed: {'yes' if focus['backlog_allowed'] else 'no'}")
    return 0


def event_counts(events: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    event_type_counts = Counter(str(event.get("event_type")) for event in events)
    skill_counts: Counter[str] = Counter()
    for event in events:
        tags = event.get("skill_tags")
        if isinstance(tags, list):
            skill_counts.update(str(tag) for tag in tags if str(tag).strip())
        elif isinstance(tags, str):
            skill_counts.update(part.strip() for part in re.split(r"[,，/]", tags) if part.strip())
    return {"event_type": event_type_counts, "skill_tags": skill_counts}


def result_totals(events: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"wrong": 0, "uncertain": 0, "audit": 0, "diagnosed": 0}
    for event in events:
        totals["wrong"] += int_value(event.get("wrong"))
        totals["uncertain"] += int_value(event.get("uncertain"))
        result = str(event.get("result") or "")
        if result == "wrong":
            totals["wrong"] += 1
        elif result == "uncertain":
            totals["uncertain"] += 1
        elif result == "audit":
            totals["audit"] += 1
        elif result == "diagnosed":
            totals["diagnosed"] += 1
    return totals


def sample_event_line(event: dict[str, Any]) -> str:
    source = event.get("source") or "unknown source"
    label = event.get("ko") or event.get("zh") or event.get("context") or event.get("notes") or "event"
    return f"{event.get('event_type')} | {event.get('result')} | {source} | {label}"


def events_command(target: date) -> int:
    learning = [event for event in read_jsonl(LEARNING_EVENTS_PATH) if event.get("date") == target.isoformat()]
    review = [event for event in read_jsonl(REVIEW_EVENTS_PATH) if event.get("date") == target.isoformat()]
    all_events = learning + review
    counts = event_counts(all_events)
    totals = result_totals(all_events)

    print(f"# TOPIK Events - {target.isoformat()}")
    print(f"- learning events: {len(learning)}")
    print(f"- review events: {len(review)}")
    print("")
    print("## event_type distribution")
    if counts["event_type"]:
        for key, value in sorted(counts["event_type"].items()):
            print(f"- {key}: {value}")
    else:
        print("- none")
    print("")
    print("## skill_tags distribution")
    if counts["skill_tags"]:
        for key, value in counts["skill_tags"].most_common():
            print(f"- {key}: {value}")
    else:
        print("- none")
    print("")
    print("## result counts")
    print(f"- wrong: {totals['wrong']}")
    print(f"- uncertain: {totals['uncertain']}")
    print(f"- audit: {totals['audit']}")
    print(f"- diagnosed: {totals['diagnosed']}")
    print("")
    print("## samples")
    if all_events:
        for event in all_events[:5]:
            print(f"- {sample_event_line(event)}")
    else:
        print("- none")
    return 0


def score_command() -> int:
    rows = score_rows()
    listening = latest_score("듣기", rows)
    reading = latest_score("읽기", rows)
    writing = latest_score("쓰기", rows)
    print("# TOPIK Score Snapshot")
    print("")
    print("## Current scores")
    if listening:
        print(f"- listening: {listening.get('分数')} ({listening.get('卷号')}, {listening.get('日期')})")
    else:
        print("- listening: not recorded")
    if reading:
        print(f"- reading: {reading.get('分数')} ({reading.get('卷号')}, {reading.get('日期')})")
    else:
        print("- reading: not recorded")
    if writing and score_number(writing.get("分数")) is not None:
        print(f"- writing: {writing.get('分数')} ({writing.get('卷号')}, {writing.get('日期')})")
    elif writing:
        print(f"- writing: not tested / weak ({writing.get('备注')})")
    else:
        print("- writing: not tested / weak")
    print("")
    print("## Target")
    print("- listening 60+")
    print("- reading 55–60")
    print("- writing 35–40")
    print("- total 150+")
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "today":
        return today_command(parse_target(args.date))
    if args.command == "check":
        return check_command(parse_target(args.date))
    if args.command == "focus":
        return focus_command(parse_target(args.date))
    if args.command == "events":
        return events_command(parse_target(args.date))
    if args.command == "score":
        return score_command()
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
