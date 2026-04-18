# Cross-Case Attackability

Generated at: `2026-04-17T01:14:53Z`

## Summary

- Top bullish cases by boundary distance: `aapl_s05_clean, aapl_s01_clean, aapl_s02_clean, nvda_s01_clean, nvda_s03_clean`
- Observed static successes: `aapl_s05_clean, aapl_s01_clean`
- Supplementary near-break case: `nvda_s01_clean`
- Interpretation: The lowest bullish boundary distances were concentrated in AAPL scenarios, and the observed static successes occurred on those same near-boundary cases.

## Case Table

| Case | Direction | Difficulty | Boundary | Dir Rank | Attackable | Observed Label | Observed Success | Slices |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| aapl_s05_clean | bullish | easy | 0.57 | 1 | True | observed_static_success | True | aapl_s05_stage1 |
| aapl_s01_clean | bullish | easy | 1.23 | 2 | True | observed_static_success | True | aapl_s01_stage1, pilot_v5 |
| aapl_s02_clean | bullish | easy | 1.25 | 3 | True | not_observed_in_frozen_static_slices | False |  |
| nvda_s01_clean | bullish | moderate | 2.21 | 4 | True | observed_static_no_success | False | nvda_s01_supplementary, pilot_v5 |
| nvda_s03_clean | bullish | easy | 2.5 | 5 | True | not_observed_in_frozen_static_slices | False |  |
| aapl_s03_clean | bullish | easy | 3.01 | 6 | True | not_observed_in_frozen_static_slices | False |  |
| nvda_s05_clean | bullish | moderate | 3.44 | 7 | True | not_observed_in_frozen_static_slices | False |  |
| nvda_s04_clean | bullish | moderate | 3.61 | 8 | True | not_observed_in_frozen_static_slices | False |  |
| nvda_s02_clean | bullish | moderate | 3.81 | 9 | True | not_observed_in_frozen_static_slices | False |  |
| meta_s02_clean | bullish | hard | 6.89 | 10 | False | not_observed_in_frozen_static_slices | False |  |
| aapl_s04_clean | bullish | hard | 6.95 | 11 | False | not_observed_in_frozen_static_slices | False |  |
| meta_s04_clean | bearish | hard | 4.83 | 1 | False | not_observed_in_frozen_static_slices | False |  |
| amzn_s03_clean | bearish | hard | 5.07 | 2 | False | not_observed_in_frozen_static_slices | False |  |
| meta_s03_clean | bearish | hard | 5.17 | 3 | False | not_observed_in_frozen_static_slices | False |  |
| meta_s05_clean | bearish | hard | 5.21 | 4 | False | not_observed_in_frozen_static_slices | False |  |
| meta_s01_clean | bearish | hard | 5.75 | 5 | False | observed_static_no_success | False | pilot_v5 |
| amzn_s04_clean | bearish | hard | 7.09 | 6 | False | not_observed_in_frozen_static_slices | False |  |
| amzn_s02_clean | bearish | hard | 8.79 | 7 | False | not_observed_in_frozen_static_slices | False |  |
| amzn_s01_clean | bearish | hard | 10 | 8 | False | observed_static_no_success | False | pilot_v5 |
| amzn_s05_clean | bearish | hard | 10 | 9 | False | not_observed_in_frozen_static_slices | False |  |
