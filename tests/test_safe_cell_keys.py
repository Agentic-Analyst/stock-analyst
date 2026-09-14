from pathlib import Path


def test_artifact_cell_keys_are_never_executed_as_python():
    root = Path(__file__).resolve().parents[1]
    report = (root / "src/report_agent.py").read_text()
    model = (root / "src/agents/supervisor/task_agents/model_generation_agent.py").read_text()
    assert "row, col = eval(key)" not in report
    assert "row, col = eval(cell_key)" not in model
    assert "ast.literal_eval(key)" in report
    # New artifact readers may add more safe parsing sites. The security
    # invariant is that every executable-looking cell key is parsed as a
    # literal and never evaluated as Python, not that the file has exactly two
    # consumers forever.
    assert model.count("ast.literal_eval(cell_key)") >= 2


def test_each_pipeline_evaluates_a_model_exactly_once():
    root = Path(__file__).resolve().parents[1]
    direct = (root / "main.py").read_text()
    agent = (root / "src/agents/supervisor/task_agents/model_generation_agent.py").read_text()
    builder = (root / "src/agents/fm/financial_model_builder.py").read_text()

    assert "builder.evaluate_and_save_json(json_output_path)" not in direct
    assert "builder.evaluate_and_save_json(json_output_path)" not in agent
    assert builder.count("builder.evaluate_and_save_json(json_output_path)") == 1


def test_model_agent_publication_controls_fail_closed():
    root = Path(__file__).resolve().parents[1]
    agent = (root / "src/agents/supervisor/task_agents/model_generation_agent.py").read_text()

    assert "publication safety check failed closed" in agent
    assert "method-suitability check failed closed" in agent
    assert "Bank valuation override skipped" not in agent
    assert "state.current_stage = PipelineStage.FAILED" in agent
