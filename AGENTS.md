# QuantBoy Project Rules

This is the operating guide for AI agents and contributors working on this
repository.

## Current Decision

QuantBoy is an RQAlpha-first low-frequency quant research project.

- Use RQAlpha as the only backtest/execution engine on the main path.
- Treat the RQAlpha official bundle as the authoritative data source for
  backtests until a later bundle update interface is implemented.
- Keep QuantBoy focused on target-weight strategies, RQAlpha adapter code,
  indicators, helper scripts, and documentation.
- Do not reintroduce a self-built Python backtest engine unless the user
  explicitly changes this decision.

## Strategy Contract

New strategies belong in `strategy/strategies/`.

They should expose:

```python
def target_weights(self, date, history, tradable_codes):
    return {
        "510300": 0.4,
        "510500": 0.3,
        "159915": 0.3,
    }
```

Strategies decide desired exposure only. They should not own order matching,
cash checks, T+1, fees, suspension logic, or fill prices. RQAlpha owns those
execution rules.

## Main Entry Points

- `strategy/quantboy/rqalpha_adapter.py`: target-weight strategy adapter for
  RQAlpha.
- `strategy/strategies/`: formal research strategies.
- `scripts/rqalpha_target_weight_demo.py`: main runnable RQAlpha strategy file.
- `scripts/rqalpha_etf_smoke.py`: minimal RQAlpha smoke test.
- `docs/bundle-update-todo.md`: future bundle update interface TODO.

Do not point users to removed legacy files such as `BacktestEngine`, `Broker`,
`Strategy.buy()`, `TargetWeightBacktestEngine`, or `run_etf_baseline.py`.

## Data Rule

The authoritative backtest data source is the RQAlpha bundle.

The current local test bundle path is:

```text
data/rqalpha_bundle/bundle
```

The workspace also contains local SQLite data assets such as
`data/quantboy.db`. Do not delete them unless explicitly asked, but do not use
them as the canonical backtest source under the current decision.

Future bundle update work should follow `docs/bundle-update-todo.md`.

## Current Research Best

The current best practical strategy for follow-up tracking is:

```text
stateful_accelerating_momentum 10/200/80 top1 daily with take_profit=0.8
```

Use these strategy settings:

```text
QUANTBOY_RQ_STRATEGY=stateful_accelerating_momentum
QUANTBOY_RQ_SHORT_LOOKBACK=10
QUANTBOY_RQ_LONG_LOOKBACK=200
QUANTBOY_RQ_VOLATILITY_LOOKBACK=80
QUANTBOY_RQ_MOMENTUM_TOP_K=1
QUANTBOY_RQ_SHORT_WEIGHT=1.5
QUANTBOY_RQ_TRAILING_DRAWDOWN=0.08
QUANTBOY_RQ_TAKE_PROFIT=0.8
QUANTBOY_RQ_MA_EXIT_WINDOW=20
QUANTBOY_RQ_COOLDOWN_WEEKS=1
QUANTBOY_RQ_ALLOW_SWITCH=1
QUANTBOY_RQ_REBALANCE=daily
```

Research context:

- Training window: 2025-06-01 to 2025-12-31.
- Current verified test window: 2026-01-01 to 2026-06-25.
- Universe: `all_etf_liquid_plus_hs300`.
- Execution: RQAlpha daily bar, stock T+1, `-sp 0.001`, 100,000 initial
  cash, benchmark `000300.XSHG`.
- Filters: pre-start history enabled, 20-day average turnover at least
  200,000,000, avoid limit-up/limit-down trades, and exclude STAR/ChiNext
  buys.
- Current bundle: `data/rqalpha_bundle/bundle_2026-06-25_all_etf_liquid_plus_hs300`.

Observed results:

- Current verified test: Sharpe 5.0359, total return 274.42%, max drawdown
  15.07%, final value 374,415.18.
- Same strategy through 2026-06-24: Sharpe 4.8858, total return 254.82%,
  max drawdown 15.07%.
- Previous practical baseline `risk_adjusted_momentum 220/50/top2 weekly`
  through 2026-06-24: Sharpe 3.5561, total return 128.09%, max drawdown
  21.34%.

Interpretation:

- Treat this as the current practical main strategy candidate.
- It is a stateful target-weight strategy: rank by long momentum plus recent
  acceleration divided by trailing volatility, hold the strongest name, and
  apply trailing-drawdown, take-profit, moving-average exit, and cooldown rules.
- It chooses target weights only. RQAlpha owns fill prices, cash constraints,
  round lots, fees, T+1, suspension, volume limits, and limit-price behavior.
- In the current daily-bar setup, RQAlpha uses current-bar close matching with
  0.1% price-ratio slippage: buys are filled near close * 1.001 and sells near
  close * 0.999, clipped by limit prices.
- Do not confuse this strategy with `scheduled_rotation`. That strategy was an
  exploratory future-return schedule and is not a meaningful investment
  strategy.

## Useful Commands

Install Python dependencies:

```bash
.venv/bin/pip install -r strategy/requirements.txt
```

Download official bundle:

```bash
.venv/bin/rqalpha download-bundle -d data/rqalpha_bundle --confirm
```

Run equal-weight strategy inside RQAlpha:

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

Run momentum strategy inside RQAlpha:

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

Run another built-in strategy by changing `QUANTBOY_RQ_STRATEGY`:

```bash
QUANTBOY_RQ_STRATEGY=dual_ma \
QUANTBOY_RQ_SHORT_WINDOW=20 \
QUANTBOY_RQ_LONG_WINDOW=120 \
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
  --report /tmp/rqalpha_target_weight_dual_ma \
  -o /tmp/rqalpha_target_weight_dual_ma.pkl \
  -l error
```

Built-in strategy keys are `equal_weight`, `momentum`, `ma_trend`, `dual_ma`,
`mean_reversion`, `low_volatility`, `risk_parity`, `trend_timing`,
`absolute_momentum`, `dual_momentum`, `volatility_target`,
`drawdown_control`, `trend_risk_parity`, `min_variance`, `max_sharpe`,
`low_volatility_trend`, and `sector_rotation`.

Batch-run built-in strategies from the default config:

```bash
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib \
  .venv/bin/python scripts/run_strategy_batch.py
```

The default config is `config/backtest.yaml`. It owns the date range, cash,
bundle path, strategies, rebalance frequencies, concurrency settings, strategy
parameters, and configured universe runs. Command line arguments with the same
names override the config for one-off tests.

Build and use an ETF universe from the RQAlpha bundle:

```bash
PYTHONPATH=strategy .venv/bin/python scripts/build_etf_universe.py \
  --preset all_etf_liquid \
  --start 2025-01-01 \
  --end 2026-05-29 \
  --output outputs/universes/all_etf_liquid_2025-01-01_2026-05-29.csv

PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib \
  .venv/bin/python scripts/run_strategy_batch.py \
  --start 2025-01-01 \
  --end 2026-05-29 \
  --codes-file outputs/universes/all_etf_liquid_2025-01-01_2026-05-29.csv \
  --rebalance monthly
```

`all_etf_liquid` defaults to `fund_type=StockIndex`, minimum latest size
500,000,000, at least 120 listed days before the start date, and excludes
Hong Kong/Hang Seng related ETFs.

Incremental Tushare bundle updates should use the same tested universe when
the user asks for the current ETF + HS300 scope:

```bash
TUSHARE_TOKEN=<token> PYTHONPATH=strategy .venv/bin/python \
  scripts/update_rqalpha_bundle.py update \
  --bundle data/rqalpha_bundle/bundle \
  --output-bundle data/rqalpha_bundle/bundle_YYYY-MM-DD \
  --start YYYY-MM-DD \
  --end YYYY-MM-DD \
  --universe stock,etf \
  --codes-file outputs/universes/all_etf_liquid_plus_hs300_2025-01-01_2026-05-29.csv \
  --rate-limit-per-minute 180

TUSHARE_TOKEN=<token> PYTHONPATH=strategy .venv/bin/python \
  scripts/update_rqalpha_bundle.py update \
  --bundle data/rqalpha_bundle/bundle_YYYY-MM-DD \
  --start YYYY-MM-DD \
  --end YYYY-MM-DD \
  --universe index \
  --codes 000001.XSHG,000300.XSHG \
  --rate-limit-per-minute 180
```

`all_etf_liquid_plus_hs300` means liquid `StockIndex` ETFs plus HS300 stock
constituents from the generated universe file. It is not just the `000300.XSHG`
index series. RQAlpha 6.1.5 uses `000001.XSHG` to determine the daily bundle
available data range, so incremental bundles that will be used for RQAlpha
backtests must also update `000001.XSHG`. Keep `000300.XSHG` updated when it is
used as the benchmark.

Scan all rebalance frequencies:

```bash
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib \
  .venv/bin/python scripts/run_strategy_batch.py \
  --start 2024-01-01 \
  --end 2026-05-29 \
  --codes 510300,510500,159915,510050,588000 \
  --rebalances all
```

Verify Python entry points:

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

## Generated Files

Do not commit generated caches, logs, virtual environments, RQAlpha bundles, or
RQAlpha output files.

- `__pycache__/`
- `*.pyc`
- `*.log`
- `.venv/`
- local bundle directories
- RQAlpha reports and pickle outputs
