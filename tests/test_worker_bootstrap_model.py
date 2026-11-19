"""A chat the server starts names no --llm; it must start on CHAT_MODEL (19 Nov 2026).

Run locally end to end with only a Bedrock key, every chat failed at start-up:
the worker initialised its default OpenAI model before the chat path read
CHAT_MODEL, and that model's key was missing.
"""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location("worker_main", pathlib.Path(__file__).parents[1] / "main.py")
worker_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker_main)


def test_a_server_chat_starts_on_the_chat_model(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "set-for-the-test")
    argv = ["--email", "a@example.com", "--timestamp", "t", "--pipeline", "chat", "--user-prompt", "hi"]
    assert worker_main.bootstrap_model("chat", "gpt-6-luna", argv,
                                       {"CHAT_MODEL": "claude-sonnet-5-5-bedrock"}) == "claude-sonnet-5-5-bedrock"


def test_an_explicit_llm_wins():
    argv = ["--pipeline", "chat", "--llm", "claude-haiku-5-5-bedrock"]
    assert worker_main.bootstrap_model("chat", "claude-haiku-5-5-bedrock", argv,
                                       {"CHAT_MODEL": "claude-sonnet-5-5-bedrock"}) == "claude-haiku-5-5-bedrock"


def test_other_pipelines_and_unknown_models_keep_the_default():
    assert worker_main.bootstrap_model("comprehensive", "gpt-6-luna", [],
                                       {"CHAT_MODEL": "claude-sonnet-5-5-bedrock"}) == "gpt-6-luna"
    assert worker_main.bootstrap_model("chat", "gpt-6-luna", [], {"CHAT_MODEL": "no-such-model"}) == "gpt-6-luna"
    assert worker_main.bootstrap_model("chat", "gpt-6-luna", [], {}) == "gpt-6-luna"


def test_a_chat_model_without_its_key_keeps_the_default(monkeypatch):
    # The review's case: CHAT_MODEL on Bedrock with only an OpenAI key set.
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    assert worker_main.bootstrap_model("chat", "gpt-6-luna", [],
                                       {"CHAT_MODEL": "claude-sonnet-5-5-bedrock"}) == "gpt-6-luna"
