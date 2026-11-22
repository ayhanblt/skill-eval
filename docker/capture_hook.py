#!/usr/bin/env python3
"""Claude Code PreToolUse / PostToolUse hook capturing every tool & Skill invocation."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/capture/hook-events.jsonl")
    raw = sys.stdin.read().strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"raw": raw}

    record = {
        "utc": datetime.now(UTC).isoformat(),
        "hook_event_name": payload.get("hook_event_name"),
        "tool_name": payload.get("tool_name"),
        "tool_use_id": payload.get("tool_use_id"),
        "tool_input": payload.get("tool_input"),
        "is_error": payload.get("is_error"),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
