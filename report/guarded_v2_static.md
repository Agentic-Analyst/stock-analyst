# guarded_v2 static slice

Status: `not_run`

- Reason: `verifier_v2_gate_failed`
- Gate source: `report/verifier_v2_evaluation.json`
- Intended slice: same 9-case no-AMZN static slice used for the frozen
  `struq-lite` evaluation

The verifier-v2 replay did not detect the known AAPL success cases and
calibration collapsed to a threshold of `1.0`, so `guarded_v2` was
intentionally not run.
