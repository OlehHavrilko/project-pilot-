"""Unit tests for the DeepSeek adapter (MockTransport, no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from models.adapter import Budget, BudgetExceeded, ModelAdapter, ModelError, ModelFormatError

SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "integer"}}}
CONFIG = {
    "models": {
        "base_url": "https://api.deepseek.test",
        "executor": {"model": "deepseek-flash", "thinking": "disabled"},
        "planner": {"model": "deepseek-flash", "thinking": "enabled", "reasoning_effort": "high"},
    },
    "limits": {"max_model_calls": 10, "max_tokens": 1000},
}


def make(handler, budget: Budget | None = None) -> ModelAdapter:
    return ModelAdapter(
        CONFIG,
        "sk-test",
        transport=httpx.MockTransport(handler),
        budget=budget,
    )


def completion(content: str, reasoning: str = "") -> dict:
    message = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    return {
        "model": "deepseek-flash",
        "choices": [{"message": message}],
        "usage": {"total_tokens": 10, "completion_tokens": 2, "prompt_tokens": 8},
    }


def test_valid_json_is_parsed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json=completion('{"answer": 391}'))

    with make(handler) as adapter:
        response = adapter.complete("executor", [{"role": "user", "content": "x"}], schema=SCHEMA)
    assert response.data == {"answer": 391}
    assert response.role == "executor"
    assert adapter.budget.tokens == 10


def test_invalid_json_is_retried_once() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, json=completion("not json at all"))
        return httpx.Response(200, json=completion('{"answer": 5}'))

    with make(handler) as adapter:
        response = adapter.complete("executor", [{"role": "user", "content": "x"}], schema=SCHEMA)
    assert calls["count"] == 2
    assert response.data == {"answer": 5}


def test_invalid_json_twice_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion("still not json"))

    with make(handler) as adapter:
        with pytest.raises(ModelFormatError):
            adapter.complete("executor", [{"role": "user", "content": "x"}], schema=SCHEMA)


def test_planner_sends_thinking_and_reasoning_effort() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=completion('{"answer": 1}', reasoning="thinking..."))

    with make(handler) as adapter:
        response = adapter.complete("planner", [{"role": "user", "content": "x"}], schema=SCHEMA)
    assert seen["thinking"] == {"type": "enabled"}
    assert seen["reasoning_effort"] == "high"
    assert response.reasoning_chars == len("thinking...")


def test_missing_api_key_raises() -> None:
    with pytest.raises(ModelError):
        ModelAdapter(CONFIG, "")


def test_budget_is_enforced() -> None:
    budget = Budget(max_calls=1, max_tokens=1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion('{"answer": 1}'))

    with make(handler, budget=budget) as adapter:
        adapter.complete("executor", [{"role": "user", "content": "x"}], schema=SCHEMA)
        with pytest.raises(BudgetExceeded):
            adapter.complete("executor", [{"role": "user", "content": "y"}], schema=SCHEMA)
