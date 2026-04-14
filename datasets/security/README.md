# Security Benchmark Dataset

This directory contains the local prompt-injection benchmark used for the VYNN AI
security MVP.

Layout:

- `cases.jsonl`: one manifest row per clean or poisoned case
- `articles/<case_id>/*.md`: frozen article bundles with YAML front matter

The dataset is built from real searched article artifacts already present under
`data/**/searched/*.md`, then paired poisoned variants are generated
deterministically for:

- `tier1`: direct override
- `tier2`: disguised financial-language steering
- `tier3`: stealthy downstream recommendation shift

Rebuild command:

```bash
PYTHONPATH=src conda run -n stock-analyst python -m src.security.build_dataset --force
```

Run the pilot subset:

```bash
PYTHONPATH=src conda run -n stock-analyst python -m src.security.run_benchmark --split pilot --config baseline
```
