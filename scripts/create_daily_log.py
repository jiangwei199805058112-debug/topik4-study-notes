from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "templates" / "daily_log_template.md"
DAILY_DIR = ROOT / "daily"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a TOPIK daily log from the template.")
    parser.add_argument("date", nargs="?", default=date.today().isoformat(), help="Date in YYYY-MM-DD format.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_date = args.date

    if not TEMPLATE_PATH.exists():
        print(f"Template not found: {TEMPLATE_PATH}")
        return 1

    DAILY_DIR.mkdir(exist_ok=True)
    output_path = DAILY_DIR / f"{target_date}_daily_log.md"
    if output_path.exists():
        print(f"Daily log already exists: {output_path}")
        return 0

    content = TEMPLATE_PATH.read_text(encoding="utf-8").replace("YYYY-MM-DD", target_date)
    output_path.write_text(content, encoding="utf-8")
    print(f"Created daily log: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
