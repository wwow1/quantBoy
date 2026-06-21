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

Run momentum strategy inside RQAlpha:

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

Verify Python entry points:

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

## Generated Files

Do not commit generated caches, logs, virtual environments, RQAlpha bundles, or
RQAlpha output files.

- `__pycache__/`
- `*.pyc`
- `*.log`
- `.venv/`
- local bundle directories
- RQAlpha reports and pickle outputs
