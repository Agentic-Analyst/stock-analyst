"""The release-gate summary must fail on drift and on any unexplained outcome."""
import importlib.util
import json
import os
import re
import sys

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "valuation_canary_summary.py")
_SPEC = importlib.util.spec_from_file_location("valuation_canary_summary", _PATH)
summary = importlib.util.module_from_spec(_SPEC)
sys.modules["valuation_canary_summary"] = summary
_SPEC.loader.exec_module(summary)


def _row(ticker, *, withheld=False, status="passed", reason=None):
    return {
        "ticker": ticker, "status": status,
        "point_estimate_withheld": withheld, "withheld_reason": reason,
    }


def test_status_labels_follow_the_canary_row():
    assert summary._status(_row("NVDA")) == "PUBLISHED"
    assert summary._status(_row("TSLA", withheld=True)) == "WITHHELD"
    assert summary._status(_row("SPY", status="passed_specialized_refusal")) == "refused"
    assert summary._status(_row("X", status="failed")) == "FAILED"


def test_publish_rate_excludes_failed_and_refused_rows():
    rows = [
        _row("NVDA"), _row("TSLA", withheld=True),
        _row("SPY", status="passed_specialized_refusal"), _row("X", status="failed"),
    ]
    out = summary.summarize(rows, "candidate")
    assert out["equities"] == 2
    assert out["published"] == 1
    assert out["publish_rate"] == 0.5
    assert out["failed"] == ["X"]


def test_unexplained_changes_name_every_drift_and_every_unlisted_name():
    rows = [
        _row("NVDA"),
        _row("META", withheld=True, reason="The valuation methods span more than 1.8x. Rest."),
        _row("ZZZ"),
    ]
    expectations = {
        "NVDA": {"status": "PUBLISHED"},
        "META": {"status": "PUBLISHED", "why": "DCF within 15% of market"},
    }
    problems = summary.unexplained_changes(rows, expectations)
    assert problems == [
        "UNEXPLAINED: META expected PUBLISHED but is WITHHELD "
        "(The valuation methods span more than 1.8x)",
        "UNLISTED: ZZZ is PUBLISHED but has no expectation",
    ]
    assert summary.unexplained_changes(rows[:1], expectations) == []


def test_cli_exit_codes(tmp_path, capsys):
    rows = [_row("NVDA"), _row("TSLA", withheld=True, reason="Far below market. More.")]
    candidate = tmp_path / "cand.json"
    candidate.write_text("chatter\n" + json.dumps(rows), encoding="utf-8")
    expect = tmp_path / "expect.json"
    expect.write_text(json.dumps({
        "_comment": "ignored", "NVDA": {"status": "PUBLISHED"}, "TSLA": "WITHHELD",
    }), encoding="utf-8")

    assert summary.main([str(candidate), "--expect", str(expect)]) == 0
    assert "every name matches" in capsys.readouterr().out

    expect.write_text(json.dumps({"NVDA": "WITHHELD", "TSLA": "WITHHELD"}), encoding="utf-8")
    assert summary.main([str(candidate), "--expect", str(expect)]) == 3
    assert "UNEXPLAINED: NVDA expected WITHHELD but is PUBLISHED" in capsys.readouterr().out

    assert summary.main([str(candidate), "--min-publish-rate", "0.9"]) == 1

    rows.append(_row("BAD", status="failed"))
    candidate.write_text(json.dumps(rows), encoding="utf-8")
    assert summary.main([str(candidate)]) == 2


def test_real_expectation_file_covers_the_nightly_basket():
    scripts = os.path.join(os.path.dirname(__file__), "..", "scripts")
    expectations = summary._expectations(
        summary.Path(os.path.join(scripts, "valuation_canary_expectations.json"))
    )
    # Read the basket from the nightly script so the two cannot drift apart.
    nightly = open(os.path.join(scripts, "nightly_valuation_canary.sh"), encoding="utf-8").read()
    basket = re.search(r'BASKET=\$\{BASKET:-"([^"]+)"\}', nightly).group(1).split()
    assert "BKNG" in basket
    assert sorted(expectations) == sorted(basket)
    statuses = set()
    for entry in expectations.values():
        status = entry["status"]
        statuses.update(status if isinstance(status, list) else [status])
    assert statuses <= {"PUBLISHED", "WITHHELD"}
    assert all(entry.get("why") for entry in expectations.values())


def test_a_list_accepts_either_outcome_but_never_a_failure():
    expectations = {"BKNG": {"status": ["PUBLISHED", "WITHHELD"], "why": "boundary"}}
    assert summary.unexplained_changes([_row("BKNG")], expectations) == []
    assert summary.unexplained_changes([_row("BKNG", withheld=True)], expectations) == []
    failed = {"ticker": "BKNG", "status": "failed",
              "error": "Workbook accounting/valuation identity integrity failed with 1 error(s)"}
    assert summary.unexplained_changes([failed], expectations) == [
        "UNEXPLAINED: BKNG expected PUBLISHED or WITHHELD but is FAILED "
        "(Workbook accounting/valuation identity integrity failed with 1 error(s))"
    ]


def test_context_only_comps_are_starred_in_the_table():
    voting = {"peer_value": 164.47, "peer_value_included": True}
    context = {"peer_value": 164.47, "peer_value_included": False}
    legacy = {"peer_value": 164.47}
    assert summary._comps(voting).endswith("164.47 ")
    assert summary._comps(context).endswith("164.47*")
    assert summary._comps(legacy).endswith("164.47 ")
    assert summary._comps({"peer_value": 0, "peer_value_included": False}).strip() == "-"
