from pathlib import Path

import pytest

from src import path_utils
from src.session_manager import SessionManager


@pytest.mark.parametrize(
    "bad", ["", ".", "..", "../other", "a/b", "a\\b", "x\x00y", "x\ny"]
)
def test_analysis_path_rejects_unsafe_components(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(path_utils, "DATA_ROOT", tmp_path)
    with pytest.raises(ValueError):
        path_utils.get_analysis_path("person@example.com", "AAPL", bad)


def test_analysis_path_keeps_valid_identity_under_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "DATA_ROOT", tmp_path)
    result = path_utils.get_analysis_path(
        "Person+Research@example.com", "BRK.B", "2026-09-12T12:30:00"
    )
    assert result == (
        tmp_path
        / "person+research@example.com"
        / "BRK.B"
        / "2026-09-12T12:30:00"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("email", "../other@example.com"),
        ("ticker", "../../AAPL"),
        ("session_name", "../another-session"),
    ],
)
def test_session_manager_rejects_unsafe_storage_components(
    tmp_path, monkeypatch, field, value
):
    import src.session_manager as session_module

    monkeypatch.setattr(session_module, "DATA_ROOT", tmp_path)
    kwargs = {
        "email": "person@example.com",
        "ticker": "CHAT",
        "session_name": "chat_2026-09-12T12:30:00",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        SessionManager(**kwargs)


def test_failure_session_can_start_without_company_name(tmp_path, monkeypatch):
    import src.session_manager as session_module

    monkeypatch.setattr(session_module, "DATA_ROOT", tmp_path)
    manager = SessionManager("person@example.com", "CHAT", "session-1")
    index = manager.start_conversation("retry my question")
    assert index == 0
    assert manager.session_data["conversation_history"][0]["completion_status"] == "in_progress"
    assert Path(manager.session_file).is_file()


def test_empty_session_summary_contains_ticker_once(tmp_path, monkeypatch):
    import src.session_manager as session_module

    monkeypatch.setattr(session_module, "DATA_ROOT", tmp_path)
    manager = SessionManager("person@example.com", "CHAT", "session-1")
    assert manager.get_conversation_summary().count("**Ticker:** CHAT") == 1


def test_session_summary_renders_withheld_range_without_leaking_internal_value(
    tmp_path, monkeypatch
):
    import src.session_manager as session_module

    monkeypatch.setattr(session_module, "DATA_ROOT", tmp_path)
    manager = SessionManager("person@example.com", "CHAT", "session-1")
    manager.session_data["conversation_history"] = [{
        "timestamp": "2026-09-12T12:00:00",
        "user_query": "value AAPL",
        "completion_status": "completed",
        "routing_decisions": ["build_model"],
        "key_findings": "AAPL is NOT RATED.",
        "analysis_results": {
            "ticker": "AAPL",
            "valuation": {
                "current_price": 332.27,
                "currency": "USD",
                "model_type": "DCF",
                "point_estimate_withheld": True,
                "range_low": 154.04,
                "range_high": 180.33,
                "publication_withheld_reason": "external evidence conflicts",
            },
        },
    }]

    summary = manager.get_conversation_summary()

    assert "NOT RATED / withheld" in summary
    assert "USD 154.04–180.33" in summary
    assert "Publication reason: external evidence conflicts" in summary
    assert "Fair Value:" not in summary


def test_session_summary_formats_fractional_upside_as_percentage(
    tmp_path, monkeypatch
):
    import src.session_manager as session_module

    monkeypatch.setattr(session_module, "DATA_ROOT", tmp_path)
    manager = SessionManager("person@example.com", "CHAT", "session-1")
    manager.session_data["conversation_history"] = [{
        "timestamp": "2026-09-12T12:00:00", "user_query": "value AAPL",
        "completion_status": "completed", "routing_decisions": [],
        "key_findings": "", "analysis_results": {"valuation": {
            "currency": "USD", "upside_downside": -0.157,
        }},
    }]

    assert "Upside/Downside: -15.70%" in manager.get_conversation_summary()


def test_session_summary_does_not_call_equal_endpoints_a_range(
    tmp_path, monkeypatch
):
    import src.session_manager as session_module

    monkeypatch.setattr(session_module, "DATA_ROOT", tmp_path)
    manager = SessionManager("person@example.com", "CHAT", "session-1")
    manager.session_data["conversation_history"] = [{
        "timestamp": "2026-09-12T12:00:00",
        "user_query": "value TSM",
        "completion_status": "completed",
        "routing_decisions": ["build_model"],
        "key_findings": "TSM is NOT RATED.",
        "analysis_results": {"valuation": {
            "currency": "TWD",
            "point_estimate_withheld": True,
            "support_shape": "single_estimate",
            "range_low": 13245.003,
            "range_high": 13245.004,
        }},
    }]

    summary = manager.get_conversation_summary()

    assert "Supported DCF scenario estimate: TWD 13,245.00" in summary
    assert "Supported method range" not in summary
