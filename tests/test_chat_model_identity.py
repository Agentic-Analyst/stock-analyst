from pathlib import Path


def test_chat_override_updates_the_artifact_model_identity():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text()
    init = source.index("init_llm(chat_model)")
    identity = source.index('os.environ["ANALYSIS_LLM_MODEL"] = chat_model', init)
    construction = source.index("GeneralistAgent(", init)
    assert init < identity < construction


def test_default_chat_model_is_a_valid_cli_model_choice():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text()
    # --llm now offers every registered model (including Claude on Bedrock).
    assert "choices=list_models()" in source
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from llms.config import LLMProvider
    assert "gpt-6-luna" in LLMProvider.MODELS
    assert 'os.getenv("CHAT_MODEL", "gpt-6-luna")' in source
    assert 'default="gpt-6-luna"' in source
