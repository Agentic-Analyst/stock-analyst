# Valuation boundary and terminal-growth floor experiment

This directory preserves the launch-canary evidence produced on 2026-09-13
against worker commit `ae1e7575fa4fc630c2faaec84c49f09de78cfb71`.
The original files were recovered from the Claude Code scratch directory before
that temporary directory was removed.

## Universe

`AAPL MSFT GOOGL AMZN META NVDA JPM BAC KO PG JNJ XOM CVX WMT HD UNH T VZ PFE CSCO`

Each run used the real deterministic workbook builder and artifact audit through
`src.valuation_model_canary`. It did not invoke an LLM or write a narrative
report.

## Preserved runs

| File | Intended variant | Withheld |
| --- | --- | ---: |
| `raw/baseline.out` | PR #15 behavior | 14 / 20 |
| `raw/threshold_30pct.out` | restore the mega-cap gap threshold to 30% | 12 / 20 |
| `raw/threshold_30pct_and_wide_band.out` | also allow the `wide` dispersion band | 12 / 20 |
| `raw/all_three_boundary_changes.out` | also relax the corroboration-magnitude rule | 12 / 20 |
| `raw/main_floor.out` | baseline publication rules with main's terminal-growth floor | 14 / 20 |

The floor variant changed one expression in
`src/agents/fm/tabs/tab_valuation_perpetual_growth_dcf.py`:

```diff
-gs_expr = 'MIN(MAX(Model_Inputs!$F$4,-0.2),0.2)'
+gs_expr = 'MIN(MAX(Model_Inputs!$F$4,Assumptions!$B$30),0.2)'
```

The first three boundary labels are reconstructed from the scratch output paths
and the contemporaneous audit report. They are retained as negative evidence,
not as approval to change a publication policy.

## Result

Restoring main's floor did not change the withheld count. Fourteen of the 18
model-valued names were unchanged to displayed cents. KO changed +0.37%, T
+0.09%, VZ +0.13%, and PFE +1.17%; PFE was the only move above 0.5%. No company
moved from withheld to published. The mechanism is normally inert because FY5
revenue growth for the cited mature companies was well above -20%; it changes
value only when FY5 growth falls below the 2.5% terminal-growth assumption.

This rules out that floor as the material source of the low valuations. It does
not establish which upstream forecast or discount-rate input is responsible.

## Reproducibility limitation

The original baseline and floor runs each fetched live data separately. Their
inputs are therefore close but not byte-identical. Both exact input sets are
preserved as compressed JSON snapshots:

- `raw/baseline-inputs.tar.gz`
- `raw/main-floor-inputs.tar.gz`

The raw output streams include the compact JSON result after the workbook
evaluator's progress lines. No credentials are present. A controlled replay
must use one frozen input set for both formulas; do not present the original
live-versus-live comparison as a perfectly isolated causal experiment.

## Reconstructed invocation

```bash
PYTHONPATH=src python -m src.valuation_model_canary \
  AAPL MSFT GOOGL AMZN META NVDA JPM BAC KO PG JNJ XOM CVX WMT HD UNH T VZ PFE CSCO \
  --output-root /tmp/vynn-valuation-floor-run
```

The frozen-input replay added after this evidence-preservation commit is the
canonical way to repeat the comparison.
