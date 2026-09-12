"""BabelDOC subprocess bridge that emits machine-readable progress events.

The request, including the short-lived API key, is read from stdin so secrets do
not appear in the process command line. stdout is reserved for prefixed JSON
events; regular BabelDOC logging continues on stderr.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys


EVENT_PREFIX = "IPAPER_EVENT\t"


def _emit(event: dict) -> None:
    safe = {
        key: value for key, value in event.items()
        if key in {
            "type", "stage", "stage_progress", "stage_current", "stage_total",
            "overall_progress", "part_index", "total_parts",
        }
    }
    print(EVENT_PREFIX + json.dumps(safe, ensure_ascii=True), flush=True)


def _progress_handler(_config, show_log: bool = False):
    del show_log

    def handle(event: dict) -> None:
        if event.get("type") in {"progress_start", "progress_update", "progress_end"}:
            _emit(event)

    return contextlib.nullcontext(), handle


def main() -> int:
    request = json.loads(sys.stdin.readline())
    model = str(request["model"])
    base_url = str(request["base_url"])
    api_key = str(request["api_key"])
    os.environ.setdefault("XDG_CACHE_HOME", os.path.abspath("cache"))

    from babeldoc import main as babeldoc_main
    from babeldoc.format.pdf import high_level

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    for noisy in ("httpx", "httpcore", "openai", "peewee", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    babeldoc_main.create_progress_handler = _progress_handler
    sys.argv = [
        "babeldoc",
        "--openai",
        "--openai-model", model,
        "--openai-base-url", base_url,
        "--openai-api-key", api_key,
        "--files", "input.pdf",
        "--output", ".",
        "--working-dir", "resume",
        "--max-pages-per-part", "20",
        "--report-interval", "0.5",
        "--watermark-output-mode", "no_watermark",
    ]
    high_level.init()
    asyncio.run(babeldoc_main.main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
