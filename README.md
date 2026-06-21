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
  target-weight strategies such as equal weight and momentum rotation

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
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib .venv/bin/rqalpha run \
  -d data/rqalpha_bundle/bundle \
  -f scripts/rqalpha_target_weight_demo.py \
  -s 2020-11-16 \
  -e 2026-03-20 \
  -a stock 1000000 \
  -bm 000300.XSHG \
  -sp 0.001 \
  --stock-t1 \
  --report /tmp/rqalpha_target_weight_equal_weight \
  -o /tmp/rqalpha_target_weight_equal_weight.pkl \
  -l error
```

Momentum ETF strategy:

```bash
QUANTBOY_RQ_STRATEGY=momentum \
QUANTBOY_RQ_MOMENTUM_LOOKBACK=120 \
QUANTBOY_RQ_MOMENTUM_TOP_K=1 \
PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib .venv/bin/rqalpha run \
  -d data/rqalpha_bundle/bundle \
  -f scripts/rqalpha_target_weight_demo.py \
  -s 2020-11-16 \
  -e 2026-03-20 \
  -a stock 1000000 \
  -bm 000300.XSHG \
  -sp 0.001 \
  --stock-t1 \
  --report /tmp/rqalpha_target_weight_momentum \
  -o /tmp/rqalpha_target_weight_momentum.pkl \
  -l error
```

Environment variables supported by `scripts/rqalpha_target_weight_demo.py`:

- `QUANTBOY_RQ_STRATEGY`: `equal_weight` or `momentum`
- `QUANTBOY_RQ_CODES`: comma-separated codes, for example
  `510300,510500,159915`
- `QUANTBOY_RQ_HISTORY_BARS`: RQAlpha history window, default `260`
- `QUANTBOY_RQ_MAX_TOTAL_WEIGHT`: max gross target weight, default `0.99`
- `QUANTBOY_RQ_MOMENTUM_LOOKBACK`: momentum lookback, default `120`
- `QUANTBOY_RQ_MOMENTUM_TOP_K`: number of selected assets, default `1`

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
  scripts/rqalpha_target_weight_demo.py \
  scripts/rqalpha_etf_smoke.py
```

## Notes

RQAlpha's source distribution includes commercial-use restrictions. Review the
license before using it in any commercial product or service.
