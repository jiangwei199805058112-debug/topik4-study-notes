from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
LEARNING_EVENTS_PATH = ROOT / "data" / "learning_events.jsonl"
REVIEW_EVENTS_PATH = ROOT / "data" / "review_events.jsonl"

SECTION_DEFAULTS = {
    "learned_items": {"event_type": "grammar_learned", "result": "learned", "direction": "mixed"},
    "review_results": {"event_type": "review_result", "result": "skipped", "direction": "mixed"},
    "exam_results": {"event_type": "exam_diagnosis", "result": "diagnosed", "direction": "mixed"},
    "audit_notes": {"event_type": "audit_note", "result": "audit", "direction": "mixed"},
}
REVIEW_EVENT_TYPES = {"review_result", "generated_question_result"}
DEDUPE_FIELDS = ("date", "event_type", "exam", "section", "question_no", "ko", "direction")
ALLOWED_RESULTS = {"correct", "wrong", "uncertain", "learned", "diagnosed", "audit", "skipped"}
ALLOWED_DIRECTIONS = {"ko_to_zh", "zh_to_ko", "listening", "reading", "writing", "mixed"}
BASE_FIELDS = [
    "date",
    "event_type",
    "source",
    "item_id",
    "ko",
    "zh",
    "context",
    "exam",
    "section",
    "question_no",
    "direction",
    "result",
    "skill_tags",
    "notes",
]
ALIASES = {
    "日期": "date",
    "类型": "event_type",
    "event type": "event_type",
    "来源": "source",
    "id": "item_id",
    "ID": "item_id",
    "韩语": "ko",
    "Korean": "ko",
    "中文": "zh",
    "Chinese": "zh",
    "语境": "context",
    "例句": "context",
    "卷号": "exam",
    "科目": "section",
    "题号": "question_no",
    "方向": "direction",
    "结果": "result",
    "标签": "skill_tags",
    "备注": "notes",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest a GPT TOPIK session summary into event JSONL files.")
    parser.add_argument("--input", required=True, help="Markdown session summary file.")
    parser.add_argument("--date", required=True, help="Event date in YYYY-MM-DD format.")
    parser.add_argument("--dry-run", action="store_true", help="Preview parsed events without writing files.")
    parser.add_argument("--allow-empty", action="store_true", help="Exit successfully even if no events are parsed.")
    return parser.parse_args()


def parse_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid --date value: {value}") from exc


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


def split_sections(text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+([A-Za-z_]+)\s*$", text, flags=re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        if name not in SECTION_DEFAULTS:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[name] = text[start:end].strip()
    return sections


def normalize_key(key: str) -> str:
    key = key.strip()
    return ALIASES.get(key, ALIASES.get(key.lower(), key))


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator_row(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(cell.replace(":", "").replace("-", "").strip() == "" for cell in cells)


def parse_json_blocks(section_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", section_text, flags=re.DOTALL | re.IGNORECASE):
        raw = match.group(1).strip()
        if not raw:
            continue
        value = json.loads(raw)
        if isinstance(value, list):
            events.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            events.append(value)

    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        value = json.loads(stripped)
        if isinstance(value, dict):
            events.append(value)
    return events


def parse_markdown_tables(section_text: str) -> list[dict[str, Any]]:
    lines = section_text.splitlines()
    events: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip().startswith("|") or index + 1 >= len(lines) or not is_separator_row(lines[index + 1]):
            index += 1
            continue
        header = [normalize_key(cell) for cell in split_table_row(lines[index])]
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            if not is_separator_row(lines[cursor]):
                cells = split_table_row(lines[cursor])
                events.append({header[pos]: cells[pos] if pos < len(cells) else "" for pos in range(len(header))})
            cursor += 1
        index = cursor
    return events


def parse_bullet_records(section_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        item = stripped[2:].strip()
        separator = "：" if "：" in item else ":"
        if separator not in item:
            continue
        key, value = item.split(separator, 1)
        key = normalize_key(key)
        if key == "event_type" and current:
            events.append(current)
            current = {}
        current[key] = value.strip()
    if current:
        events.append(current)
    return events


def section_events(section_name: str, section_text: str, target_date: str, default_source: str) -> list[dict[str, Any]]:
    parsed = []
    parsed.extend(parse_json_blocks(section_text))
    parsed.extend(parse_markdown_tables(section_text))
    parsed.extend(parse_bullet_records(section_text))

    normalized: list[dict[str, Any]] = []
    defaults = SECTION_DEFAULTS[section_name]
    for event in parsed:
        clean = {normalize_key(str(key)): value for key, value in event.items()}
        clean.setdefault("date", target_date)
        clean.setdefault("event_type", defaults["event_type"])
        clean.setdefault("source", default_source)
        clean.setdefault("result", defaults["result"])
        clean.setdefault("direction", defaults["direction"])
        normalized.append(normalize_event(clean))
    return normalized


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    clean = dict(event)
    for field in BASE_FIELDS:
        clean.setdefault(field, None)
    clean["date"] = parse_date(str(clean["date"]))
    clean["question_no"] = normalize_question_no(clean.get("question_no"))
    clean["skill_tags"] = normalize_skill_tags(clean.get("skill_tags"))
    clean["result"] = str(clean.get("result") or "").strip()
    clean["direction"] = str(clean.get("direction") or "").strip()
    if clean["result"] not in ALLOWED_RESULTS:
        raise ValueError(f"Unsupported result value: {clean['result']}")
    if clean["direction"] not in ALLOWED_DIRECTIONS:
        raise ValueError(f"Unsupported direction value: {clean['direction']}")
    ordered = {field: clean.get(field) for field in BASE_FIELDS}
    for key, value in clean.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def normalize_question_no(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return int(text) if text.isdigit() else None


def normalize_skill_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[,，/]", text) if part.strip()]


def event_key(event: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(event.get(field) for field in DEDUPE_FIELDS)


def target_path(event: dict[str, Any]) -> Path:
    if event.get("event_type") in REVIEW_EVENT_TYPES:
        return REVIEW_EVENTS_PATH
    return LEARNING_EVENTS_PATH


def append_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> int:
    args = parse_args()
    target_date = parse_date(args.date)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    sections = split_sections(input_path.read_text(encoding="utf-8"))
    events: list[dict[str, Any]] = []
    default_source = str(input_path)
    for section_name, section_text in sections.items():
        events.extend(section_events(section_name, section_text, target_date, default_source))

    if not events and not args.allow_empty:
        print("Parsed 0 events. Use --allow-empty to permit this.", file=sys.stderr)
        return 2

    existing_keys = {
        target_path(event): {event_key(item) for item in read_jsonl(target_path(event))}
        for event in events
    }
    pending: dict[Path, list[dict[str, Any]]] = {LEARNING_EVENTS_PATH: [], REVIEW_EVENTS_PATH: []}
    skipped = 0
    seen_new: set[tuple[Any, ...]] = set()
    for event in events:
        path = target_path(event)
        key = event_key(event)
        if key in existing_keys.setdefault(path, set()) or key in seen_new:
            skipped += 1
            continue
        seen_new.add(key)
        pending[path].append(event)

    if not args.dry_run:
        for path, path_events in pending.items():
            append_jsonl(path, path_events)

    print("Ingest summary")
    print(f"- parsed_events: {len(events)}")
    print(f"- learning_events_to_add: {len(pending[LEARNING_EVENTS_PATH])}")
    print(f"- review_events_to_add: {len(pending[REVIEW_EVENTS_PATH])}")
    print(f"- skipped_duplicates: {skipped}")
    print(f"- dry_run: {args.dry_run}")
    sample = next((event for path_events in pending.values() for event in path_events), None)
    if sample:
        print("- sample: " + json.dumps(sample, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
