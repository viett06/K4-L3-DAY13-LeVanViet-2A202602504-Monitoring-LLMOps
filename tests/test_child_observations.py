from __future__ import annotations

import json
from contextlib import contextmanager

from app import agent as agent_module


class ManagedPrompt:
    version = 3

    def compile(self, **variables: str) -> str:
        return (
            f"Feature={variables['feature']}\n"
            f"Docs={variables['docs']}\n"
            f"Question={variables['message']}"
        )


class Observation:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class RecordingClient:
    def __init__(self) -> None:
        self.prompt = ManagedPrompt()
        self.started: list[dict] = []
        self.observations: list[Observation] = []

    def get_prompt(self, name: str, **kwargs):
        return self.prompt

    def update_current_span(self, **kwargs) -> None:
        return None

    def start_as_current_observation(self, **kwargs):
        observation = Observation()
        self.started.append(kwargs)
        self.observations.append(observation)

        @contextmanager
        def context():
            yield observation

        return context()


def test_run_creates_retriever_and_generation_children(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)

    @contextmanager
    def record_attributes(**kwargs):
        yield

    monkeypatch.setattr(agent_module, "propagate_attributes", record_attributes)

    agent = agent_module.LabAgent()
    result = agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain traces. Email student@vinuni.edu.vn phone 0901234567",
        correlation_id="req-12345678",
    )

    assert [item["as_type"] for item in client.started] == ["retriever", "generation"]
    assert client.started[0]["name"] == "retrieval"
    assert client.started[1]["name"] == "generation"
    assert client.started[1]["model"] == "claude-sonnet-4-5"
    assert client.started[1]["prompt"] is client.prompt
    generation_update = client.observations[1].updates[-1]
    assert generation_update["usage_details"]["input"] > 0
    assert generation_update["usage_details"]["output"] > 0
    assert generation_update["usage_details"]["total"] == (
        generation_update["usage_details"]["input"] + generation_update["usage_details"]["output"]
    )
    assert generation_update["cost_details"]["total"] == result.cost_usd
    assert result.retrieval_ms >= 0
    assert result.generation_ms >= 0

    safe_started = []
    for item in client.started:
        copied = dict(item)
        copied.pop("prompt", None)
        safe_started.append(copied)
    captured = json.dumps(
        {"started": safe_started, "updates": [item.updates for item in client.observations]},
        ensure_ascii=False,
    )
    assert "student@vinuni.edu.vn" not in captured
    assert "0901234567" not in captured
