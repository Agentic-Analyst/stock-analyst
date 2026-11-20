from pathlib import Path


def test_the_artifacts_name_the_model_that_made_them():
    # Since 19 Nov 2026 a chat no longer switches the whole worker to
    # CHAT_MODEL: the tools' bulk steps (news insights, report write-up) run on
    # the worker's model, so the artifacts' manifest names that model.
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text()
    assert "init_llm(chat_model)" not in source
    assert 'os.environ["ANALYSIS_LLM_MODEL"] = chat_model' not in source
    identity = source.index('os.environ["ANALYSIS_LLM_MODEL"] = args.llm')
    init = source.index("init_llm(args.llm)")
    construction = source.index("GeneralistAgent(")
    assert identity < init < construction


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
