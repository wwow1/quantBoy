# Backtest Framework Decision

## Decision

Use RQAlpha as the only backtest/execution engine for QuantBoy.

QuantBoy no longer maintains its own Python event-driven engine or light
target-weight engine on the main path. The project now provides:

- target-weight strategy classes
- an adapter that maps those strategies into RQAlpha
- indicators and small research helpers
- documentation and runnable RQAlpha scripts

## Data Decision

Use the RQAlpha official bundle as the authoritative data source for now.

Observed local bundle path:

```text
data/rqalpha_bundle/bundle
```

Observed latest checked bar date in that bundle:

```text
2026-05-29
```

Checked assets included common ETFs, `000001`, and `000300`.

Local SQLite data in `data/quantboy.db` is no longer the canonical backtest
source under this decision. It can remain as a historical data asset.

## Strategy Interface

Low-frequency strategies should return target weights:

```python
def target_weights(self, date, history, tradable_codes):
    return {"510300": 0.5, "510500": 0.5}
```

RQAlpha owns:

- account state
- order submission
- matching
- fees and slippage
- T+1 behavior
- suspension and tradability checks
- reports and result output

QuantBoy's adapter controls rebalance frequency before handing orders to
RQAlpha. Supported modes are `daily`, `weekly`, and `monthly`; the default is
`daily`.

## Implemented

- Installed and smoke-tested RQAlpha `6.1.5`.
- Downloaded official bundle to `data/rqalpha_bundle/bundle`.
- Added `strategy/quantboy/rqalpha_adapter.py`.
- Added `scripts/rqalpha_target_weight_demo.py`.
- Added formal strategies under `strategy/strategies/`.
- Added built-in target-weight strategies: equal weight, momentum rotation,
  moving average trend, dual moving average, mean reversion, low volatility,
  and risk parity.
- Removed the old self-built Python backtest engines and old demo backtest
  scripts from the main codebase.

## Current RQAlpha Commands

Equal weight:

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

Momentum:

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

Other built-in strategy keys:

- `ma_trend`: hold assets above their moving average.
- `dual_ma`: hold assets whose short moving average is above long moving
  average.
- `mean_reversion`: buy recent laggards that remain above a long trend line.
- `low_volatility`: buy the lowest trailing volatility assets.
- `risk_parity`: allocate by inverse trailing volatility.
- `trend_timing`: hold assets above a long moving average.
- `absolute_momentum`: hold assets with positive own trailing returns.
- `dual_momentum`: select the strongest positive-momentum assets.
- `volatility_target`: scale inverse-volatility weights toward target risk.
- `drawdown_control`: reduce exposure when basket drawdown is too large.
- `trend_risk_parity`: risk parity after a trend filter.
- `min_variance`: long-only minimum-variance covariance approximation.
- `max_sharpe`: long-only maximum-Sharpe covariance approximation.
- `low_volatility_trend`: low-volatility selection after trend filtering.
- `sector_rotation`: momentum rotation for industry/theme ETF universes.

Batch comparison:

```bash
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib \
  .venv/bin/python scripts/run_strategy_batch.py
```

The batch script reads `config/backtest.yaml` by default. That file owns the
date range, initial cash, bundle path, selected strategies, rebalance
frequencies, concurrency settings, strategy parameters, and one or more
universe runs. Command line arguments with the same names override the config
for temporary tests.

ETF universe from bundle:

```bash
PYTHONPATH=strategy .venv/bin/python scripts/build_etf_universe.py \
  --preset all_etf_liquid \
  --start 2025-01-01 \
  --end 2026-05-29 \
  --output outputs/universes/all_etf_liquid_2025-01-01_2026-05-29.csv
```

The `all_etf_liquid` preset keeps liquid `StockIndex` ETFs by default:
broad-market, industry, and theme ETFs. Money, bond, QDII, Hong Kong/Hang Seng,
newly listed, and small ETFs are excluded unless the filters are overridden.

Frequency scan:

```bash
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib \
  .venv/bin/python scripts/run_strategy_batch.py \
  --start 2024-01-01 \
  --end 2026-05-29 \
  --codes 510300,510500,159915,510050,588000 \
  --rebalances all
```

The batch script saves RQAlpha pkl files and `summary.csv` under
`outputs/backtests/<start>_<end>/`.

## Caveats

- RQAlpha's source distribution includes commercial-use restrictions. Review
  the license before commercial use.
- The official bundle is not necessarily updated every trading day.
- `rqalpha update-bundle` exists, but the tested path requires RQDatac
  credentials.
- Future non-official bundle updates need an explicit data ingestion interface;
  see [bundle-update-todo.md](bundle-update-todo.md).
