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

## Implemented

- Installed and smoke-tested RQAlpha `6.1.5`.
- Downloaded official bundle to `data/rqalpha_bundle/bundle`.
- Added `strategy/quantboy/rqalpha_adapter.py`.
- Added `scripts/rqalpha_target_weight_demo.py`.
- Added formal strategies under `strategy/strategies/`.
- Removed the old self-built Python backtest engines and old demo backtest
  scripts from the main codebase.

## Current RQAlpha Commands

Equal weight:

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

Momentum:

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

## Caveats

- RQAlpha's source distribution includes commercial-use restrictions. Review
  the license before commercial use.
- The official bundle is not necessarily updated every trading day.
- `rqalpha update-bundle` exists, but the tested path requires RQDatac
  credentials.
- Future non-official bundle updates need an explicit data ingestion interface;
  see [bundle-update-todo.md](bundle-update-todo.md).
