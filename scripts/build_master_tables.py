from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
GRAMMAR_CSV = ROOT / "data" / "master" / "grammar_master.csv"
VOCAB_CSV = ROOT / "data" / "master" / "vocabulary_master.csv"
GRAMMAR_MD = ROOT / "grammar" / "MASTER_GRAMMAR_TABLE.md"
VOCAB_MD = ROOT / "vocabulary" / "MASTER_VOCABULARY_TABLE.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build human-readable TOPIK master tables from CSV data.")
    parser.add_argument("--dry-run", action="store_true", help="Preview generated output without writing files.")
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Master CSV not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def clean_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").replace("|", "/").strip()


def relation_text(row: dict[str, str]) -> str:
    parts = []
    if row.get("confusable_with"):
        parts.append(f"易混: {row['confusable_with']}")
    if row.get("same_meaning_as"):
        parts.append(f"同义: {row['same_meaning_as']}")
    return "；".join(parts)


def ask_text(row: dict[str, str]) -> str:
    priority = row.get("ask_priority", "")
    status = row.get("status", "")
    if priority == "suspended" or status in {"mastered", "archived"}:
        return "暂停高频"
    if priority == "high":
        return "high"
    if status == "low_frequency" or priority == "low":
        return "low_frequency"
    return priority or status or "medium"


def render_table(headers: list[str], rows: Iterable[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|---" * len(headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(clean_cell(value) for value in row) + " |")
    return lines


def render_grammar(rows: list[dict[str, str]]) -> str:
    table_rows = []
    for row in rows:
        example = row.get("example_ko", "")
        if row.get("example_zh"):
            example = f"{example} / {row['example_zh']}"
        table_rows.append(
            [
                row.get("pattern", ""),
                row.get("canonical_meaning_zh", ""),
                row.get("function", ""),
                row.get("form_note", ""),
                example,
                relation_text(row),
                row.get("mastery_level", ""),
                ask_text(row),
                row.get("source_refs", ""),
            ]
        )
    lines = [
        "# TOPIK4 学过语法总表",
        "",
        "> 本文件由 `scripts/build_master_tables.py` 根据 `data/master/grammar_master.csv` 生成，请优先维护 CSV。",
        "",
        f"- 语法项数量：{len(rows)}",
        "",
        *render_table(
            ["语法", "中文核心义", "功能", "接续/形态", "例句", "易混/同义", "掌握等级", "是否继续提问", "来源"],
            table_rows,
        ),
        "",
    ]
    return "\n".join(lines)


def render_vocab(rows: list[dict[str, str]]) -> str:
    table_rows = []
    for row in rows:
        example = row.get("example_ko", "")
        if row.get("example_zh"):
            example = f"{example} / {row['example_zh']}"
        table_rows.append(
            [
                row.get("ko", ""),
                row.get("meaning_zh", ""),
                row.get("pos", ""),
                row.get("component_breakdown", ""),
                row.get("collocation", ""),
                example,
                relation_text(row),
                row.get("mastery_level", ""),
                ask_text(row),
                row.get("source_refs", ""),
            ]
        )
    lines = [
        "# TOPIK4 学过单词/搭配总表",
        "",
        "> 本文件由 `scripts/build_master_tables.py` 根据 `data/master/vocabulary_master.csv` 生成，请优先维护 CSV。",
        "",
        f"- 单词/搭配项数量：{len(rows)}",
        "",
        *render_table(
            ["韩语", "中文", "类型", "拆解", "常见搭配", "例句", "易混/同义", "掌握等级", "是否继续提问", "来源"],
            table_rows,
        ),
        "",
    ]
    return "\n".join(lines)


def maybe_write(path: Path, content: str, dry_run: bool) -> bool:
    content = content.rstrip() + "\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    changed = existing != content
    if changed and not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return changed


def main() -> int:
    args = parse_args()
    grammar_rows = read_rows(GRAMMAR_CSV)
    vocab_rows = read_rows(VOCAB_CSV)

    grammar_changed = maybe_write(GRAMMAR_MD, render_grammar(grammar_rows), args.dry_run)
    vocab_changed = maybe_write(VOCAB_MD, render_vocab(vocab_rows), args.dry_run)

    print("Master table build")
    print(f"- grammar_items: {len(grammar_rows)}")
    print(f"- vocabulary_items: {len(vocab_rows)}")
    print(f"- grammar_output: {GRAMMAR_MD}")
    print(f"- grammar_written: {grammar_changed and not args.dry_run}")
    print(f"- grammar_would_change: {grammar_changed}")
    print(f"- vocabulary_output: {VOCAB_MD}")
    print(f"- vocabulary_written: {vocab_changed and not args.dry_run}")
    print(f"- vocabulary_would_change: {vocab_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
