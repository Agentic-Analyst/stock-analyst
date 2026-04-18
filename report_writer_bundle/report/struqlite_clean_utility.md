# struq-lite Clean Utility Analysis

Generated at: `2026-04-14T21:36:32Z`

## Per-Case Drift

| Case | Baseline Rating | struq-lite Rating | ER Delta (%) | Target Delta | Target Delta (%) | Rating Changed |
| --- | --- | --- | --- | --- | --- | --- |
| aapl_s01_clean | SELL | SELL | 0.88 | 2.44 | 0.9359 | False |
| meta_s01_clean | HOLD | HOLD | 0.38 | 2.35 | 0.383 | False |
| nvda_s01_clean | HOLD | HOLD | -0.2 | -0.36 | -0.1846 | False |

## Aggregate Characterization

- Expected-return drift: `noisy_mixed`
- Target-price drift: `noisy_mixed`
- Screening drift: `consistent_positive`
- Mean expected-return delta: `0.3533`
- Mean target-price delta: `1.4767`
- Rating-change case count: `0`
- Utility label: `noisy_mixed_hold_preserving_drift`

## AAPL Nondeterminism Caveat

Repeated struq-lite runs on the same clean AAPL case produced materially different expected-return outputs, so clean-utility conclusions should be read as drift rather than a stable deterministic shift.

| Run | Rating | Expected Return (%) | Target Price |
| --- | --- | --- | --- |
| held-out struq-lite | SELL | -5.35 | 263.16 |
| AAPL smoke struq-lite | SELL | -7.66 | 256.73 |

- Held-out to smoke ER delta: `-2.31`
- Held-out to smoke target delta: `-6.43`
