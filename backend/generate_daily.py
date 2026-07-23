"""Generate and persist one daily lesson for schedulers or manual runs."""

import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data"
LOG_FILE = Path(__file__).resolve().parent / "daily_gen.log"

load_dotenv(ROOT_DIR / ".env")

from assistants.english_assistant import get_today_expression  # noqa: E402


def log(message):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def main():
    log("Starting daily lesson generation")
    result = get_today_expression()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    destination = DATA_DIR / f"day{result['day']}.json"
    temp_path = destination.with_suffix(".json.tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, destination)
    log(
        f"Saved Day {result['day']} with "
        f"{len(result.get('expressions', []))} expressions"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log(f"Generation failed: {error}")
        raise
