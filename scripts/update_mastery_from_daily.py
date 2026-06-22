from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTER_DIR = ROOT / "data" / "master"
GRAMMAR_CSV = MASTER_DIR / "grammar_master.csv"
VOCAB_CSV = MASTER_DIR / "vocabulary_master.csv"
EVENTS_CSV = MASTER_DIR / "review_events.csv"
EVENT_FIELDS = ["date", "item_type", "item_key", "result", "source_ref", "event_key"]
VALID_RESULTS = {"correct", "wrong", "uncertain"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update TOPIK master-table mastery fields from structured review results.")
    parser.add_argument("--input", required=True, help="CSV with date,item_type,item_key,result,source_ref columns.")
    parser.add_argument("--dry-run", action="store_true", help="Preview updates without writing master tables or event log.")
    return parser.parse_args()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def append_source(existing: str, source: str) -> str:
    if not source:
        return existing
    parts = [part.strip() for part in existing.split(";") if part.strip()]
    if source not in parts:
        parts.append(source)
    return ";".join(parts)


def normalize_type(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"grammar", "g"}:
        return "grammar"
    if lowered in {"vocab", "vocabulary", "word", "phrase"}:
        return "vocab"
    return lowered


def event_key(record: dict[str, str]) -> str:
    return "|".join(
        [
            record.get("date", "").strip(),
            normalize_type(record.get("item_type", "")),
            record.get("item_key", "").strip(),
            record.get("source_ref", "").strip(),
        ]
    )


def find_item(rows: list[dict[str, str]], field: str, key: str) -> dict[str, str] | None:
    key = key.strip()
    for row in rows:
        if row.get(field, "").strip() == key:
            return row
    for row in rows:
        value = row.get(field, "").strip()
        if key and (key in value or value in key):
            return row
    return None


def apply_result(row: dict[str, str], record: dict[str, str]) -> None:
    result = record["result"].strip()
    date = record["date"].strip()
    row["last_review_date"] = date
    row["last_seen_date"] = max(row.get("last_seen_date", ""), date)
    row["source_refs"] = append_source(row.get("source_refs", ""), record.get("source_ref", "").strip())

    if result == "correct":
        row["correct_count"] = str(to_int(row.get("correct_count", "0")) + 1)
    elif result == "wrong":
        row["wrong_count"] = str(to_int(row.get("wrong_count", "0")) + 1)
    elif result == "uncertain":
        row["uncertain_count"] = str(to_int(row.get("uncertain_count", "0")) + 1)

    correct = to_int(row.get("correct_count", "0"))
    wrong = to_int(row.get("wrong_count", "0"))
    uncertain = to_int(row.get("uncertain_count", "0"))

    if wrong:
        row["ask_priority"] = "high"
        row["status"] = "active"
    elif uncertain:
        if row.get("ask_priority") in {"low", "suspended"}:
            row["ask_priority"] = "medium"
        row["status"] = "active"
    elif correct >= 8:
        row["mastery_level"] = "4"
        row["ask_priority"] = "suspended"
        row["status"] = "mastered"
    elif correct >= 5:
        row["mastery_level"] = max(row.get("mastery_level", "1"), "3")
        row["ask_priority"] = "low"
        row["status"] = "low_frequency"
    elif correct >= 3:
        row["mastery_level"] = max(row.get("mastery_level", "1"), "2")
        if row.get("ask_priority") != "high":
            row["ask_priority"] = "medium"
        row["status"] = "active"


def main() -> int:
    args = parse_args()
    grammar_fields, grammar_rows = read_csv(GRAMMAR_CSV)
    vocab_fields, vocab_rows = read_csv(VOCAB_CSV)
    _, existing_events = read_csv(EVENTS_CSV)
    input_fields, records = read_csv(Path(args.input))

    required = {"date", "item_type", "item_key", "result", "source_ref"}
    missing = required - set(input_fields)
    if missing:
        print(f"Input CSV missing required columns: {', '.join(sorted(missing))}")
        return 2

    seen_events = {row.get("event_key") or event_key(row) for row in existing_events}
    new_events: list[dict[str, str]] = []
    updated = skipped_duplicate = missing_items = invalid = 0

    for record in records:
        result = record.get("result", "").strip()
        if result not in VALID_RESULTS:
            print(f"Invalid result for {record.get('item_key', '')}: {result}")
            invalid += 1
            continue
        key = event_key(record)
        if key in seen_events:
            skipped_duplicate += 1
            continue

        item_type = normalize_type(record.get("item_type", ""))
        if item_type == "grammar":
            row = find_item(grammar_rows, "pattern", record.get("item_key", ""))
        elif item_type == "vocab":
            row = find_item(vocab_rows, "ko", record.get("item_key", ""))
        else:
            print(f"Unknown item_type for {record.get('item_key', '')}: {record.get('item_type', '')}")
            invalid += 1
            continue

        if row is None:
            print(f"Item not found: {item_type} {record.get('item_key', '')}")
            missing_items += 1
            continue

        apply_result(row, record)
        event_record = {field: record.get(field, "").strip() for field in EVENT_FIELDS}
        event_record["item_type"] = item_type
        event_record["event_key"] = key
        new_events.append(event_record)
        seen_events.add(key)
        updated += 1

    print("Mastery update summary")
    print(f"- input_rows: {len(records)}")
    print(f"- updated_items: {updated}")
    print(f"- skipped_duplicate_events: {skipped_duplicate}")
    print(f"- missing_items: {missing_items}")
    print(f"- invalid_rows: {invalid}")
    print(f"- dry_run: {args.dry_run}")

    if invalid:
        return 2
    if not args.dry_run:
        write_csv(GRAMMAR_CSV, grammar_fields, grammar_rows)
        write_csv(VOCAB_CSV, vocab_fields, vocab_rows)
        write_csv(EVENTS_CSV, EVENT_FIELDS, existing_events + new_events)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
