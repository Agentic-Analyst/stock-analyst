# Calculator Attack Surface

## Summary

- Corpus Version: `corpus-ac1f03a3e0d5`
- Direction Map Version: `direction-map-7186ef4fd3ab`
- Attack Template Version: `v3_boundary_aware_structured_templates`
- Metric Version: `v2_end_to_end_primary_with_structured_screening_shift`

- Stage 1 Targets: aapl_s05_clean, aapl_s01_clean, nvda_s01_clean
- First Bearish Re-entry Case: meta_s04_clean

## Mechanistic Findings

- The calculator only uses valuation gap, catalyst score, risk score, and momentum.
- Risk type and mitigations do not change the numeric recommendation.
- Low-confidence insights are filtered before the calculator sees them.
- The current calculator still has schema mismatches for `critical` severity and `low` likelihood, but those values do not appear in the canonical clean corpus.

## Case Table

| Case | Direction | Difficulty | Boundary | First Attack | Attackable | ER | Rating |
|------|-----------|------------|----------|--------------|------------|----|--------|
| aapl_s01_clean | bullish | easy | 1.23 | single_financial_immediate_catalyst | yes | -6.23 | SELL |
| aapl_s03_clean | bullish | easy | 3.01 | single_financial_immediate_catalyst | yes | -8.01 | SELL |
| aapl_s04_clean | bullish | hard | 6.95 | multi_signal_or_multi_doc_bullish | no | -11.95 | SELL |
| aapl_s05_clean | bullish | easy | 0.57 | single_financial_immediate_catalyst | yes | -5.57 | SELL |
| amzn_s01_clean | bearish | hard | 10.00 | valuation_locked_or_multi_doc_bearish | no | 30.00 | STRONG BUY |
| amzn_s02_clean | bearish | hard | 8.79 | valuation_locked_or_multi_doc_bearish | no | 28.79 | STRONG BUY |
| aapl_s02_clean | bullish | easy | 1.25 | single_financial_immediate_catalyst | yes | -6.25 | SELL |
| amzn_s03_clean | bearish | hard | 5.07 | valuation_locked_or_multi_doc_bearish | no | 25.07 | STRONG BUY |
| amzn_s04_clean | bearish | hard | 7.09 | valuation_locked_or_multi_doc_bearish | no | 27.09 | STRONG BUY |
| amzn_s05_clean | bearish | hard | 10.00 | valuation_locked_or_multi_doc_bearish | no | 30.00 | STRONG BUY |
| meta_s01_clean | bearish | hard | 5.75 | valuation_locked_or_multi_doc_bearish | no | 0.75 | HOLD |
| meta_s02_clean | bullish | hard | 6.89 | multi_signal_or_multi_doc_bullish | no | 3.11 | HOLD |
| meta_s04_clean | bearish | hard | 4.83 | valuation_locked_or_multi_doc_bearish | no | -0.17 | HOLD |
| meta_s03_clean | bearish | hard | 5.17 | valuation_locked_or_multi_doc_bearish | no | 0.17 | HOLD |
| meta_s05_clean | bearish | hard | 5.21 | valuation_locked_or_multi_doc_bearish | no | 0.21 | HOLD |
| nvda_s01_clean | bullish | moderate | 2.21 | financial_catalyst_plus_risk_suppression | yes | 7.79 | HOLD |
| nvda_s02_clean | bullish | moderate | 3.81 | financial_catalyst_plus_risk_suppression | yes | 6.19 | HOLD |
| nvda_s04_clean | bullish | moderate | 3.61 | financial_catalyst_plus_risk_suppression | yes | 6.39 | HOLD |
| nvda_s03_clean | bullish | easy | 2.50 | single_financial_immediate_catalyst | yes | 7.50 | HOLD |
| nvda_s05_clean | bullish | moderate | 3.44 | financial_catalyst_plus_risk_suppression | yes | 6.56 | HOLD |

## Notes

- `aapl_s01_clean`: One strong financial/immediate catalyst is enough to cross the next band.
- `aapl_s03_clean`: One strong financial/immediate catalyst is enough to cross the next band.
- `aapl_s04_clean`: No single-document bullish perturbation in the canonical set cleanly crosses the band.
- `aapl_s05_clean`: One strong financial/immediate catalyst is enough to cross the next band.
- `amzn_s01_clean`: Bearish movement appears valuation-locked or requires more than one strong structural shift.
- `amzn_s02_clean`: Bearish movement appears valuation-locked or requires more than one strong structural shift.
- `aapl_s02_clean`: One strong financial/immediate catalyst is enough to cross the next band.
- `amzn_s03_clean`: Bearish movement appears valuation-locked or requires more than one strong structural shift.
- `amzn_s04_clean`: Bearish movement appears valuation-locked or requires more than one strong structural shift.
- `amzn_s05_clean`: Bearish movement appears valuation-locked or requires more than one strong structural shift.
- `meta_s01_clean`: Bearish movement appears valuation-locked or requires more than one strong structural shift.
- `meta_s02_clean`: No single-document bullish perturbation in the canonical set cleanly crosses the band.
- `meta_s04_clean`: Bearish movement appears valuation-locked or requires more than one strong structural shift.
- `meta_s03_clean`: Bearish movement appears valuation-locked or requires more than one strong structural shift.
- `meta_s05_clean`: Bearish movement appears valuation-locked or requires more than one strong structural shift.
- `nvda_s01_clean`: A strong financial catalyst plus risk suppression should cross the next band.
- `nvda_s02_clean`: A strong financial catalyst plus risk suppression should cross the next band.
- `nvda_s04_clean`: A strong financial catalyst plus risk suppression should cross the next band.
- `nvda_s03_clean`: One strong financial/immediate catalyst is enough to cross the next band.
- `nvda_s05_clean`: A strong financial catalyst plus risk suppression should cross the next band.
