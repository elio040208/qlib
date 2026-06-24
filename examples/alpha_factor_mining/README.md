# Traditional Alpha Factor Mining

This example turns Qlib into a lightweight, explainable formulaic alpha research loop.
It is model-free by default: each factor is a readable Qlib expression, and selection is
based on single-factor IC, Rank IC, long-short return, coverage, and score stability.

## Run

Make sure Qlib daily data exists at `~/.qlib/qlib_data/cn_data`, then run:

```bash
PYTHONPATH=. UV_LINK_MODE=copy uv run python examples/alpha_factor_mining/evaluate_factors.py
```

Outputs are written to `/tmp/qlib_alpha_factor_mining` by default:

- `factor_metrics.csv`: train, validation, and test metrics for every factor.
- `factor_daily_metrics.csv`: daily IC, Rank IC, and long-short return.
- `report.md`: selected factors and the evaluation method.

The default split targets recent data available in the local community CN dataset:
train from 2021 through 2023, validation in 2024, and test from 2025 through 2026-03-30.

Use another output directory with:

```bash
PYTHONPATH=. UV_LINK_MODE=copy uv run python examples/alpha_factor_mining/evaluate_factors.py \
  --output-dir /tmp/my_alpha_report
```

## Workflow Plan

1. Start with an interpretable factor pool.
   The default `factor_pool.yaml` covers kbar shape, momentum, trend, reversal, volatility,
   price-volume, and volume factors.

2. Evaluate single-factor effectiveness.
   Direction is learned only from the train period by default. Validation metrics drive
   factor selection; test metrics are kept for out-of-sample inspection.

3. Keep factors that are stable, not merely lucky.
   Focus on Rank IC mean, Rank ICIR, long-short return, coverage, and autocorrelation.
   A useful factor should be explainable and should not depend on one isolated period.

4. Expand the factor pool by hypothesis.
   Add new entries to `factor_pool.yaml`; no Python changes are required for ordinary
   expression factors.

5. Move selected factors into a strategy or model.
   For a fully transparent portfolio, rank stocks by one selected factor or by a weighted
   factor composite. For a semi-transparent baseline, feed selected factors into Qlib's
   `LinearModel`, `LGBModel`, or the configurable LightGBM workflow.

## Add A Factor

Append one item under `factors`:

```yaml
- name: "MY_FACTOR"
  category: "my_theme"
  expression: "Mean($close, 10) / $close"
  hypothesis: "Readable explanation of why the signal may predict returns."
```

If the economic direction is known in advance, set it explicitly:

```yaml
direction: 1
```

Use `direction: -1` when lower raw values should imply higher expected returns.
Without this field, the script learns direction from train-period IC.

## Notes

- The default label is `Ref($close, -2) / Ref($close, -1) - 1`, matching Qlib's Alpha158
  convention for a next tradable return.
- The default market is `csi300`; change `universe.market` in `factor_pool.yaml` for other
  instrument pools available in the local Qlib data.
- Formula operators are implemented by Qlib's expression engine in `qlib/data/ops.py`.
