from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
LEARNING_EVENTS_PATH = ROOT / "data" / "learning_events.jsonl"
REVIEW_EVENTS_PATH = ROOT / "data" / "review_events.jsonl"
SCORE_LOG_PATH = ROOT / "data" / "exam_diagnostics" / "topik_score_log.md"
WEAK_RESULTS = {"wrong", "uncertain"}


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


def event_date(event: dict[str, Any]) -> date | None:
    try:
        return datetime.strptime(str(event.get("date", "")), "%Y-%m-%d").date()
    except ValueError:
        return None


def recent_window(days: int = 3) -> set[str]:
    today = date.today()
    return {(today - timedelta(days=offset)).isoformat() for offset in range(days)}


def weak_count(event: dict[str, Any]) -> int:
    total = 0
    for key in ("wrong", "uncertain"):
        value = event.get(key)
        if isinstance(value, int):
            total += value
        elif isinstance(value, str) and value.isdigit():
            total += int(value)
    if total:
        return total
    return 1 if event.get("result") in WEAK_RESULTS else 0


def rows_from_score_log() -> list[dict[str, str]]:
    if not SCORE_LOG_PATH.exists():
        return []
    rows: list[dict[str, str]] = []
    for line in SCORE_LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] == "日期":
            header = cells
            continue
        if "header" in locals() and len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
    return rows


def item_history(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        item_id = event.get("item_id")
        if item_id:
            history[str(item_id)].append(event)
    for rows in history.values():
        rows.sort(key=lambda item: str(item.get("date", "")))
    return history


def main() -> int:
    learning_events = read_jsonl(LEARNING_EVENTS_PATH)
    review_events = read_jsonl(REVIEW_EVENTS_PATH)
    all_events = learning_events + review_events
    recent_dates = recent_window()

    recent_learning = [event for event in learning_events if event.get("date") in recent_dates]
    recent_review = [event for event in review_events if event.get("date") in recent_dates]
    recent_all = [event for event in all_events if event.get("date") in recent_dates]

    learning_counts = Counter(str(event.get("date")) for event in recent_learning)
    review_counts = Counter(str(event.get("date")) for event in recent_review)
    weak_total = sum(weak_count(event) for event in recent_all)

    history = item_history(review_events)
    all_correct_3 = [
        item_id
        for item_id, rows in history.items()
        if len(rows) >= 3 and all(row.get("result") == "correct" for row in rows[-3:])
    ]
    consecutive_weak = []
    for item_id, rows in history.items():
        streak = 0
        for row in reversed(rows):
            if row.get("result") in WEAK_RESULTS:
                streak += 1
            else:
                break
        if streak >= 2:
            consecutive_weak.append((item_id, streak))

    output_weak = [
        event
        for event in all_events
        if event.get("direction") == "zh_to_ko" and event.get("result") in WEAK_RESULTS
    ]

    print("# Learning State Audit")
    print(f"- learning_events: {LEARNING_EVENTS_PATH}")
    print(f"- review_events: {REVIEW_EVENTS_PATH}")
    print(f"- recent_window: {', '.join(sorted(recent_dates))}")
    print("")
    print("## Recent 3 Days Event Counts")
    print("| date | learning_events | review_events |")
    print("|---|---:|---:|")
    for day in sorted(recent_dates):
        print(f"| {day} | {learning_counts.get(day, 0)} | {review_counts.get(day, 0)} |")
    print("")
    print("## Recent 3 Days Weak Count")
    print(f"- wrong_or_uncertain: {weak_total}")
    print("")
    print("## Recent 3 Correct Items")
    if all_correct_3:
        for item_id in all_correct_3[:20]:
            print(f"- {item_id}")
    else:
        print("- none inferred")
    print("")
    print("## Consecutive Wrong/Uncertain Items")
    if consecutive_weak:
        for item_id, streak in consecutive_weak[:20]:
            print(f"- {item_id}: {streak}")
    else:
        print("- none inferred")
    print("")
    print("## Output Weak Items")
    if output_weak:
        for event in output_weak[:20]:
            label = event.get("item_id") or event.get("ko") or event.get("zh") or "unknown"
            print(f"- {event.get('date')} | {label} | {event.get('result')}")
    else:
        print("- none")
    print("")
    print("## TOPIK Score Summary")
    rows = rows_from_score_log()
    if rows:
        for row in rows:
            print(
                f"- {row.get('日期')} {row.get('卷号')} {row.get('科目')}: "
                f"{row.get('分数')} ({row.get('备注')})"
            )
    else:
        print("- score log not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
