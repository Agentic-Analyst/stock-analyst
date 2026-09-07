"""
Per-test isolation for run-scoped report context.

set_report_currency() pins a contextvar that format_number() now reads. A test
that pins EUR and does not reset it leaks a euro sign into every later test in
the session — which is exactly what happened the first time format_number was
made currency-aware.
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_report_context():
    try:
        from src.report_agent import set_report_currency, set_report_brief, set_report_language
        set_report_currency(None); set_report_brief(None); set_report_language(None)
    except Exception:
        pass
    yield
    try:
        from src.report_agent import set_report_currency, set_report_brief, set_report_language
        set_report_currency(None); set_report_brief(None); set_report_language(None)
    except Exception:
        pass
