#!/usr/bin/env python3
"""Smoke-check DeepSeek roles: executor (fast) and planner (reasoning + JSON)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.adapter import ModelAdapter  # noqa: E402

SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "integer"}},
}


def main() -> int:
    adapter = ModelAdapter.from_config(ROOT / "config.yaml", ROOT / ".env")
    try:
        executor = adapter.complete(
            "executor",
            [{"role": "user", "content": 'Сколько будет 17*23? Ответь JSON {"answer": <число>}'}],
            schema=SCHEMA,
            max_tokens=200,
        )
        print(
            json.dumps(
                {
                    "role": "executor",
                    "model": executor.model,
                    "answer": executor.data,
                    "latency_s": executor.latency_s,
                    "tokens": executor.usage,
                },
                ensure_ascii=False,
            )
        )
        planner = adapter.complete(
            "planner",
            [
                {
                    "role": "user",
                    "content": "Составь план из двух шагов: открыть Блокнот и напечатать текст. "
                    'Верни JSON {"steps": ["...", "..."]}',
                }
            ],
            schema={
                "type": "object",
                "required": ["steps"],
                "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
            },
            max_tokens=600,
        )
        print(
            json.dumps(
                {
                    "role": "planner",
                    "model": planner.model,
                    "steps": planner.data,
                    "latency_s": planner.latency_s,
                    "reasoning_chars": planner.reasoning_chars,
                    "tokens": planner.usage,
                },
                ensure_ascii=False,
            )
        )
        ok = (
            executor.data == {"answer": 391}
            and isinstance(planner.data, dict)
            and len(planner.data.get("steps", [])) >= 2
        )
    finally:
        adapter.close()
    print("MODELS: PASS" if ok else "MODELS: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
