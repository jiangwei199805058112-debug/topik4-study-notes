from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRAMMAR_CSV = ROOT / "data" / "master" / "grammar_master.csv"
VOCAB_CSV = ROOT / "data" / "master" / "vocabulary_master.csv"


GRAMMAR_TEXT_PATTERNS = {
    "V-으면/-면": [r"[가-힣]+으면", r"[가-힣]+면"],
    "V-기 시작하다": [r"기 시작하"],
    "-는 걸 보니": [r"는 걸 보니"],
    "-(으)ㄴ 모양이다": [r"모양이다"],
    "V-자": [r"[가-힣]+자(?:\s|$)"],
    "V-ㄹ 만큼": [r"[가-힣]+[을릴] 만큼", r"만큼"],
    "V-ㄹ 정도로": [r"정도로"],
    "V-기 나름이다": [r"기 나름"],
    "V-기에 달려 있다": [r"기에 달려"],
    "V-지 마세요": [r"지 마세요"],
    "V-ㄹ 때": [r"[가-힣]+[을릴] 때"],
    "N을/를 대상으로": [r"대상으로"],
    "-든지": [r"든지"],
    "-거나": [r"거나"],
    "-곤 하다": [r"곤 하"],
    "-는 편이다": [r"는 편"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query learned TOPIK grammar and vocabulary master tables.")
    parser.add_argument("--grammar", help="Exact or partial grammar pattern query.")
    parser.add_argument("--vocab", help="Exact or partial vocabulary/collocation query.")
    parser.add_argument("--text", help="Scan a Korean text for learned grammar and vocabulary items.")
    return parser.parse_args(normalize_option_values(sys.argv[1:]))


def normalize_option_values(argv: list[str]) -> list[str]:
    normalized: list[str] = []
    index = 0
    value_options = {"--grammar", "--vocab", "--text"}
    while index < len(argv):
        token = argv[index]
        if token in value_options and index + 1 < len(argv):
            normalized.append(f"{token}={argv[index + 1]}")
            index += 2
            continue
        normalized.append(token)
        index += 1
    return normalized


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace("V-", "").replace("N", "")


def row_summary(kind: str, row: dict[str, str]) -> list[str]:
    if kind == "grammar":
        title = row.get("pattern", "")
        meaning = row.get("canonical_meaning_zh", "")
        example = row.get("example_ko", "")
    else:
        title = row.get("ko", "")
        meaning = row.get("meaning_zh", "")
        example = row.get("example_ko", "")
    relation = []
    if row.get("confusable_with"):
        relation.append(f"易混: {row['confusable_with']}")
    if row.get("same_meaning_as"):
        relation.append(f"同义: {row['same_meaning_as']}")
    return [
        f"- type: {kind}",
        f"  item: {title}",
        "  learned: yes",
        f"  meaning_zh: {meaning}",
        f"  mastery_level: {row.get('mastery_level', '')}",
        f"  ask_priority: {row.get('ask_priority', '')}",
        f"  status: {row.get('status', '')}",
        f"  source_refs: {row.get('source_refs', '')}",
        f"  relations: {'；'.join(relation) if relation else ''}",
        f"  example: {example}",
    ]


def find_rows(rows: list[dict[str, str]], field: str, query: str) -> list[dict[str, str]]:
    query_norm = normalize(query)
    matches = []
    for row in rows:
        value = row.get(field, "")
        value_norm = normalize(value)
        if query_norm == value_norm or query_norm in value_norm or value_norm in query_norm:
            matches.append(row)
    return matches


def vocab_variants(value: str) -> list[str]:
    variants = [value]
    if value.endswith("하다") and len(value) > 3:
        variants.append(value[:-2])
    elif value.endswith("해지다") and len(value) > 4:
        variants.append(value[:-3] + "해졌")
        variants.append(value[:-1])
    elif value.endswith(("되다", "지다")) and len(value) > 3:
        variants.append(value[:-1])
    elif value.endswith("다") and len(value) > 3:
        variants.append(value[:-1])
    return [item for item in variants if item]


def text_matches(grammar_rows: list[dict[str, str]], vocab_rows: list[dict[str, str]], text: str) -> list[tuple[str, dict[str, str]]]:
    matches: list[tuple[str, dict[str, str]]] = []
    seen: set[tuple[str, str]] = set()
    for row in grammar_rows:
        pattern = row.get("pattern", "")
        for expr in GRAMMAR_TEXT_PATTERNS.get(pattern, [re.escape(pattern)]):
            if re.search(expr, text):
                key = ("grammar", pattern)
                if key not in seen:
                    seen.add(key)
                    matches.append(("grammar", row))
                break
    for row in vocab_rows:
        key_value = row.get("ko", "")
        for variant in vocab_variants(key_value):
            if variant and variant in text:
                key = ("vocab", key_value)
                if key not in seen:
                    seen.add(key)
                    matches.append(("vocab", row))
                break
    return matches


def print_not_found(kind: str, query: str) -> None:
    print(f"- type: {kind}")
    print(f"  item: {query}")
    print("  learned: no")


def main() -> int:
    args = parse_args()
    grammar_rows = read_rows(GRAMMAR_CSV)
    vocab_rows = read_rows(VOCAB_CSV)
    emitted = False

    if args.grammar:
        print(f"Query grammar: {args.grammar}")
        matches = find_rows(grammar_rows, "pattern", args.grammar)
        if not matches:
            print_not_found("grammar", args.grammar)
        for row in matches:
            print("\n".join(row_summary("grammar", row)))
        emitted = True

    if args.vocab:
        print(f"Query vocab: {args.vocab}")
        matches = find_rows(vocab_rows, "ko", args.vocab)
        if not matches:
            print_not_found("vocab", args.vocab)
        for row in matches:
            print("\n".join(row_summary("vocab", row)))
        emitted = True

    if args.text:
        print(f"Scan text: {args.text}")
        matches = text_matches(grammar_rows, vocab_rows, args.text)
        if not matches:
            print("- learned_matches: 0")
        else:
            print(f"- learned_matches: {len(matches)}")
            for kind, row in matches:
                print("\n".join(row_summary(kind, row)))
        emitted = True

    if not emitted:
        print("No query provided. Use --grammar, --vocab, or --text.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
