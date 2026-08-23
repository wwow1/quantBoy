# QuantBoy

QuantBoy is now a small strategy layer around RQAlpha for low-frequency A-share
and ETF research.

Current decision:

- RQAlpha is the only backtest/execution engine on the main path.
- The RQAlpha official bundle is the authoritative market data source for now.
- QuantBoy keeps strategy interfaces, RQAlpha adapters, indicators, and helper
  scripts.
- The old self-built Python backtest engines and example scripts have been
  removed to avoid mixing execution rules.

AI agents and contributors should read [AGENTS.md](AGENTS.md) before changing
the project.

## What Stays Here

```text
strategy/strategies/
  target-weight strategies such as equal weight, momentum rotation, moving
  average trend, mean reversion, low volatility, and risk parity

strategy/quantboy/rqalpha_adapter.py
  adapter that runs target-weight strategies inside RQAlpha

strategy/quantboy/indicator.py
  technical indicator helpers for research code

scripts/rqalpha_target_weight_demo.py
  main runnable RQAlpha entry for QuantBoy strategies

scripts/rqalpha_etf_smoke.py
  minimal RQAlpha smoke test

docs/bundle-update-todo.md
  TODO for future bundle incremental update support
```

The local SQLite database may still exist as a historical data asset, but it is
not the authoritative source for backtests while this decision is active.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r strategy/requirements.txt
```

RQAlpha has already been tested with version `6.1.5`.

## Data

The current canonical bundle path used in local tests is:

```text
data/rqalpha_bundle/bundle
```

Download the official bundle when needed:

```bash
.venv/bin/rqalpha download-bundle -d data/rqalpha_bundle --confirm
```

The official bundle observed in this workspace contains daily bars through
`2026-05-29` for checked stocks, indexes, and common ETFs.

## Run

Equal weight ETF strategy:

```bash
QUANTBOY_RQ_STRATEGY=equal_weight \
QUANTBOY_RQ_REBALANCE=daily \
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib .venv/bin/rqalpha run \
  -d data/rqalpha_bundle/bundle \
  -f scripts/rqalpha_target_weight_demo.py \
  -s 2020-11-16 \
  -e 2026-03-20 \
  -a stock 100000 \
  -bm 000300.XSHG \
  -sp 0.001 \
  --stock-t1 \
  --report /tmp/rqalpha_target_weight_equal_weight \
  -o /tmp/rqalpha_target_weight_equal_weight.pkl \
  -l error
```

Batch-run built-in strategies from the default config:

```bash
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib \
  .venv/bin/python scripts/run_strategy_batch.py
```

The default config is [config/backtest.yaml](/root/quantBoy/config/backtest.yaml).
It defines the date range, initial cash, bundle path, strategies, rebalance
frequencies, concurrency settings, strategy parameters, and the universe runs.
Command line arguments with the same names override the config for temporary
tests.

Build a slim ETF universe from the RQAlpha bundle. This keeps liquid
`StockIndex` ETFs, covering broad-market, industry, and theme ETFs, and
excludes money, bond, QDII, Hong Kong/Hang Seng, newly listed, and small ETFs:

```bash
PYTHONPATH=strategy .venv/bin/python scripts/build_etf_universe.py \
  --preset all_etf_liquid \
  --start 2025-01-01 \
  --end 2026-05-29 \
  --output outputs/universes/all_etf_liquid_2025-01-01_2026-05-29.csv
```

Run against that ETF universe without changing the config:

```bash
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib \
  .venv/bin/python scripts/run_strategy_batch.py \
  --start 2025-01-01 \
  --end 2026-05-29 \
  --codes-file outputs/universes/all_etf_liquid_2025-01-01_2026-05-29.csv \
  --rebalance monthly
```

Universe presets supported by `scripts/build_etf_universe.py`:

- `broad_etf`: the five default broad-market ETFs.
- `all_etf`: StockIndex ETFs, covering broad-market, industry, and theme ETFs.
- `all_etf_liquid`: `all_etf` filtered by size, listing age, and non-HK scope.
- `hs300`: latest static HS300 constituents from the CSI public file.
- `all_etf_plus_hs300`: `all_etf` plus `hs300`.
- `all_etf_liquid_plus_hs300`: `all_etf_liquid` plus `hs300`.

Scan all rebalance frequencies without changing the config:

```bash
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib \
  .venv/bin/python scripts/run_strategy_batch.py \
  --start 2024-01-01 \
  --end 2026-05-29 \
  --codes 510300,510500,159915,510050,588000 \
  --rebalances all
```

This writes each RQAlpha result pkl and a `summary.csv` under:

```text
outputs/backtests/<start>_<end>/
```

Momentum ETF strategy:

```bash
QUANTBOY_RQ_STRATEGY=momentum \
QUANTBOY_RQ_REBALANCE=daily \
QUANTBOY_RQ_MOMENTUM_LOOKBACK=120 \
QUANTBOY_RQ_MOMENTUM_TOP_K=1 \
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib .venv/bin/rqalpha run \
  -d data/rqalpha_bundle/bundle \
  -f scripts/rqalpha_target_weight_demo.py \
  -s 2020-11-16 \
  -e 2026-03-20 \
  -a stock 100000 \
  -bm 000300.XSHG \
  -sp 0.001 \
  --stock-t1 \
  --report /tmp/rqalpha_target_weight_momentum \
  -o /tmp/rqalpha_target_weight_momentum.pkl \
  -l error
```

Environment variables supported by `scripts/rqalpha_target_weight_demo.py`:

- `QUANTBOY_RQ_STRATEGY`: `equal_weight`, `momentum`, `ma_trend`,
  `dual_ma`, `mean_reversion`, `low_volatility`, `risk_parity`,
  `trend_timing`, `absolute_momentum`, `dual_momentum`,
  `volatility_target`, `drawdown_control`, `trend_risk_parity`,
  `min_variance`, `max_sharpe`, `low_volatility_trend`, or
  `sector_rotation`
- `QUANTBOY_RQ_CODES`: comma-separated codes, for example
  `510300,510500,159915`
- `QUANTBOY_RQ_REBALANCE`: `daily`, `weekly`, or `monthly`; default `daily`
- `QUANTBOY_RQ_HISTORY_BARS`: RQAlpha history window, default `260`
- `QUANTBOY_RQ_MAX_TOTAL_WEIGHT`: max gross target weight, default `0.99`
- `QUANTBOY_RQ_MOMENTUM_LOOKBACK`: momentum lookback, default `120`
- `QUANTBOY_RQ_MOMENTUM_TOP_K`: number of selected assets, default `1`
- `QUANTBOY_RQ_MA_WINDOW`: moving average trend window, default `120`
- `QUANTBOY_RQ_SHORT_WINDOW`: dual moving average short window, default `20`
- `QUANTBOY_RQ_LONG_WINDOW`: dual moving average long window, default `120`
- `QUANTBOY_RQ_MEAN_REVERSION_LOOKBACK`: mean reversion lookback, default `20`
- `QUANTBOY_RQ_MEAN_REVERSION_TOP_K`: selected mean reversion assets,
  default `1`
- `QUANTBOY_RQ_TREND_WINDOW`: mean reversion trend filter, default `120`
- `QUANTBOY_RQ_VOLATILITY_LOOKBACK`: volatility window for low volatility and
  risk parity, default `60`
- `QUANTBOY_RQ_LOW_VOLATILITY_TOP_K`: selected low-volatility assets,
  default `3`
- `QUANTBOY_RQ_MIN_RETURN`: minimum trailing return for momentum filters,
  default `0`
- `QUANTBOY_RQ_TARGET_VOLATILITY`: annualized target volatility, default `0.10`
- `QUANTBOY_RQ_MAX_LEVERAGE`: max volatility-target scaling, default `1.0`
- `QUANTBOY_RQ_DRAWDOWN_LOOKBACK`: drawdown-control lookback, default `120`
- `QUANTBOY_RQ_MAX_DRAWDOWN`: drawdown-control stop threshold, default `0.08`
- `QUANTBOY_RQ_COVARIANCE_LOOKBACK`: covariance lookback for optimization
  strategies, default `120`

`scripts/run_strategy_batch.py` also supports `--rebalances daily,weekly,monthly`
or `--rebalances all` to compare rebalance frequencies in one run.

Implemented strategy meanings:

- `equal_weight`: hold all tradable codes equally.
- `momentum`: buy the strongest trailing performers.
- `ma_trend`: hold codes whose latest close is above the moving average.
- `dual_ma`: hold codes whose short moving average is above long moving average.
- `mean_reversion`: buy recent laggards that are still above a long trend line.
- `low_volatility`: buy the lowest trailing volatility codes.
- `risk_parity`: weight all usable codes by inverse trailing volatility.
- `trend_timing`: hold codes above a long moving average.
- `absolute_momentum`: hold codes with positive own trailing returns.
- `dual_momentum`: buy the strongest positive-momentum codes.
- `volatility_target`: scale inverse-volatility weights toward target risk.
- `drawdown_control`: hold equal weights unless basket drawdown is too large.
- `trend_risk_parity`: risk parity after a moving-average trend filter.
- `min_variance`: long-only minimum-variance covariance approximation.
- `max_sharpe`: long-only maximum-Sharpe covariance approximation.
- `low_volatility_trend`: low-volatility selection after trend filtering.
- `sector_rotation`: momentum rotation key for industry/theme ETF universes.

## Add A Strategy

Add a file under `strategy/strategies/` and expose a class with:

```python
def target_weights(self, date, history, tradable_codes):
    return {"510300": 0.5, "510500": 0.5}
```

The strategy should only decide target weights. RQAlpha owns account state,
orders, matching, fees, T+1, suspension, and other execution behavior.

## Verify

```bash
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib \
  .venv/bin/python -m py_compile \
  strategy/quantboy/__init__.py \
  strategy/quantboy/rqalpha_adapter.py \
  strategy/quantboy/indicator.py \
  strategy/strategies/etf_equal_weight.py \
  strategy/strategies/etf_momentum.py \
  strategy/strategies/basic.py \
  scripts/rqalpha_target_weight_demo.py \
  scripts/run_strategy_batch.py \
  scripts/rqalpha_etf_smoke.py
```

## Notes

RQAlpha's source distribution includes commercial-use restrictions. Review the
license before using it in any commercial product or service.
