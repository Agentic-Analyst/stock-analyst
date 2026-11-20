"""The model a worker starts with, which the tools' bulk steps use (19 Nov 2026).

A chat starts on the default (GPT-6 Luna) when its key is set; the chat agent
itself reasons on CHAT_MODEL through get_chat_llm. Only without the default's
key does a chat start on CHAT_MODEL: run locally with only a Bedrock key, every
chat failed at start-up on the default's missing key.
"""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location("worker_main", pathlib.Path(__file__).parents[1] / "main.py")
worker_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker_main)


ARGV = ["--email", "a@example.com", "--timestamp", "t", "--pipeline", "chat", "--user-prompt", "hi"]


def test_a_chat_with_both_keys_starts_on_the_default(monkeypatch):
    # The tools' bulk steps stay on the default: on Sonnet the news step cost ~60x.
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "set-for-the-test")
    monkeypatch.setenv("OPENAI_API_KEY", "set-for-the-test")
    assert worker_main.bootstrap_model("chat", "gpt-6-luna", ARGV,
                                       {"CHAT_MODEL": "claude-sonnet-5-5-bedrock"}) == "gpt-6-luna"


def test_a_chat_with_only_the_chat_model_s_key_starts_on_it(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "set-for-the-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert worker_main.bootstrap_model("chat", "gpt-6-luna", ARGV,
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
