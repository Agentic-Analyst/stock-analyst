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


@pytest.fixture(autouse=True)
def _offline_reference_data(monkeypatch, tmp_path):
    """
    No test touches FRED, the ECB, Japan's MOF, Yahoo or NYU. The reference-data
    modules fall through to their dated snapshots, which is the path a run takes
    when the feeds are down — so the suite exercises it every time. A test that
    wants a feed replaces netcache.http_get itself. The disk cache is a fresh
    directory per test, so nothing leaks between them.
    """
    monkeypatch.setenv("VYNN_CACHE_DIR", str(tmp_path / "cache"))
    try:
        from src.agents.fm import netcache, sovereign_rates, country_risk
    except Exception:
        yield
        return

    def _no_network(url, timeout=None):
        raise ConnectionError(f"network disabled in tests: {url}")

    monkeypatch.setattr(netcache, "http_get", _no_network)

    # yfinance is replaced by a module whose every call fails, so the real
    # ^TNX code path runs (and returns None) rather than being stubbed away.
    import sys
    import types

    class _NoTicker:
        def __init__(self, *a, **k):
            pass

        def history(self, *a, **k):
            raise RuntimeError("network disabled in tests")

        def __getattr__(self, name):
            raise RuntimeError("network disabled in tests")

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _NoTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    country_risk._reset_memo()
    sovereign_rates._reset_memo()
    yield
    country_risk._reset_memo()
    sovereign_rates._reset_memo()
