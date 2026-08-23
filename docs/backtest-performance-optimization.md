# RQAlpha Backtest Performance Optimization Notes

## Context

Current research path remains RQAlpha-first. The batch runner launches RQAlpha
for each `(strategy, rebalance)` combination and keeps RQAlpha responsible for
matching, cash, fees, T+1, suspension handling, and result accounting.

The current large run uses:

- Bundle: `data/rqalpha_bundle/bundle_2026-06-22_all_etf_liquid_plus_hs300`
- Universe: `outputs/universes/all_etf_liquid_plus_hs300_2025-01-01_2026-05-29.csv`
- Scope: 300 HS300 constituents plus 321 liquid StockIndex ETFs
- Period: `2025-01-01` to `2026-06-22`
- Workload: 17 strategies x daily/weekly rebalance = 34 RQAlpha runs
- Parallelism: `--jobs 6`
- History: `history_bars=260`, `history_cache_workers=8`

## Current Bottleneck Hypothesis

The bottleneck is mixed. Simple strategies are dominated by framework and data
loading overhead. Optimization strategies add heavy strategy-side computation.

During the current large daily/weekly run, 30 of 34 combinations completed
while the remaining long-tail jobs were exactly:

- `daily/min_variance`
- `daily/max_sharpe`
- `weekly/min_variance`
- `weekly/max_sharpe`

The long-tail run was interrupted after preserving the completed result files.
This is strong evidence that the covariance/linear-solve strategies need a
separate optimization path before they are included in routine full-universe
frequency scans.

### Framework/Data Loading Costs

`scripts/run_strategy_batch.py` starts one independent RQAlpha process for each
strategy/rebalance pair. Each process:

- starts a fresh Python/RQAlpha runtime;
- loads the same bundle metadata;
- subscribes the same 621-code universe;
- preloads close history from HDF5 in `RQAlphaTargetWeightAdapter`;
- runs the RQAlpha event loop over the same date range;
- writes an independent pickle result.

This means the same large universe is read repeatedly. The relevant files are
large enough for repeated reads to matter:

- `stocks.h5`: about 1.3 GB
- `funds.h5`: about 270 MB
- `indexes.h5`: about 1.4 GB

Even though each run reads only selected datasets, the cost is paid once per
RQAlpha process.

### Strategy Computation Costs

Most simple strategies loop over `tradable_codes` and use a close-only history
window. Their complexity is roughly `O(N * lookback)` per rebalance, where
`N ~= 621`.

The heavier strategies are:

- `min_variance`
- `max_sharpe`

Both build a return matrix with `pd.concat`, compute covariance, and solve a
linear system on each rebalance date. With hundreds of symbols, this can become
the dominant cost. The solve is roughly cubic in the number of included assets.

Other moderately heavy strategies include:

- `risk_parity`
- `trend_risk_parity`
- `volatility_target`
- `drawdown_control`

They are less expensive than covariance solves, but still repeatedly build
Pandas objects from per-code history frames.

### Order Submission Costs

`RQAlphaTargetWeightAdapter._apply_target_weights` currently iterates over all
tradable instruments and sends `order_target_percent(order_book_id, 0.0)` for
every code not in the target set.

For TopK strategies that hold only 1 to 3 names, this can mean hundreds of
unnecessary zero-target calls per rebalance. RQAlpha still has to validate and
process those calls. This is likely a meaningful cost for large universes.

## Measurement Before Optimization

Before changing behavior, add timing visibility. Useful metrics:

- total wall time per `(strategy, rebalance)`;
- RQAlpha subprocess startup + completion time;
- adapter close-history preload time;
- rebalance count;
- per-rebalance signal calculation time;
- per-rebalance order application time;
- number of `order_target_percent` calls;
- number of actual orders/trades;
- max RSS memory per process;
- summary metric equality before/after low-risk changes.

The batch runner can write these into a sidecar CSV such as
`performance_summary.csv` next to `summary.csv`.

## Low-Risk Optimization Candidates

### 1. Only Clear Existing Positions

Current behavior clears every tradable non-target code. Instead, clear only
positions that are currently held and no longer in the target set.

Expected impact:

- large speedup for TopK and sparse strategies;
- fewer redundant RQAlpha API calls;
- should preserve portfolio behavior if implemented carefully.

Validation:

- compare trade lists and final summaries on a short period;
- verify no stale holdings remain after target changes;
- test daily and weekly rebalance.

### 2. Tune Thread Oversubscription

Current batch can run 6 RQAlpha processes, and each process may use
`history_cache_workers=8`. NumPy/BLAS may also use its own threads. This can
oversubscribe CPU and disk.

Experiment matrix:

- `jobs=3, history_cache_workers=2`
- `jobs=6, history_cache_workers=1`
- `jobs=6, history_cache_workers=2`
- `jobs=6, history_cache_workers=8`

Also consider setting:

```bash
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

Expected impact:

- lower contention;
- more stable runtime;
- especially useful for covariance-heavy strategies.

### 3. Skip Work for Strategies That Do Not Need History

`equal_weight` already has `requires_history = False`, so it avoids history
building. Keep this pattern for future strategies that only need the current
tradable universe.

### 4. Separate Heavy Strategies From Simple Strategy Sweeps

Run simple strategies together and covariance-heavy strategies separately.

Reason:

- heavy strategies can occupy worker slots for a long time;
- simple strategies give quick feedback and should not wait behind expensive
  optimization runs.

Suggested operational split:

- fast group: equal weight, momentum, MA, dual MA, mean reversion, low vol,
  trend timing, absolute/dual momentum, low-vol trend, sector rotation;
- medium group: risk parity, trend risk parity, volatility target, drawdown
  control;
- heavy group: min variance, max Sharpe.

## Medium-Risk Optimization Candidates

### 5. Shared Close Matrix Cache

Build a universe/date close matrix once per bundle/date range, then let each
RQAlpha subprocess read that compact cache instead of rereading HDF5 datasets.

Possible formats:

- NumPy `.npz` or memory-mapped `.npy`;
- Feather/Parquet;
- HDF5 cache with one dense dataset.

Expected impact:

- reduces repeated HDF5 random dataset reads;
- makes history lookup cheaper and more cache-friendly;
- helps every history-based strategy.

Validation:

- close matrix values must match RQAlpha bundle closes for sampled symbols and
  dates;
- adjusted-close behavior must match current `history_bars(..., adjust_type="pre")`
  if the strategy depends on adjusted prices.

Main caveat:

- current direct HDF5 preload reads raw bundle close, while fallback RQAlpha
  `history_bars` can apply adjustment. Any shared cache must preserve the
  adjustment semantics expected by the strategies.

### 6. Vectorize Strategy Signals

Most current strategies rebuild small Pandas objects per code on each rebalance.
For close-only strategies, compute signals from a matrix:

- rows = dates;
- columns = codes;
- rolling means, returns, volatility, and momentum computed once per strategy;
- target weights generated from vectorized arrays.

Expected impact:

- large speedup for simple and medium strategies;
- less Python loop and Pandas object churn.

Design option:

- keep strategy classes as the public contract;
- add an optional vectorized path for built-in strategies;
- fall back to current `target_weights(date, history, tradable_codes)` for custom
  strategies.

### 7. Precompute Target-Weight Schedules

Generate target weights outside RQAlpha from the bundle close matrix, then run
RQAlpha with a lightweight adapter that reads the schedule by date.

This keeps RQAlpha as the execution engine while moving signal computation out
of the event loop.

Expected impact:

- signal computation happens once per strategy/frequency in a controlled,
  vectorized pipeline;
- RQAlpha run becomes mostly execution and accounting;
- easier to debug and compare target weights across strategies.

Tradeoff:

- more architecture work;
- schedule generation must replicate the exact rebalance-date semantics.

## Heavy Strategy-Specific Optimizations

### 8. Reduce Covariance Problem Size

`min_variance` and `max_sharpe` should not necessarily solve on all 621 assets.
Options:

- preselect top candidates by liquidity, volatility, trend, or momentum;
- apply ETF-only mode for ETF allocation strategies;
- cap covariance universe size, for example 50 to 150 symbols;
- use diagonal covariance or shrinkage as a faster approximation;
- rebalance heavy optimizers weekly/monthly by default.

Expected impact:

- very large speedup;
- often improves numerical stability.

Validation:

- compare risk/return and turnover against full-universe solve;
- ensure the approximation is intentional, documented, and configurable.

### 9. Avoid Rebuilding Return Frames Per Rebalance

For covariance strategies, precompute return matrices once, then slice rolling
windows by date.

Current pattern:

- collect per-code returns into a dict;
- `pd.concat`;
- `frame.cov()`;
- solve.

Faster pattern:

- dense return matrix already aligned by date/code;
- rolling window slice is a NumPy view or compact copy;
- covariance uses NumPy directly;
- selected columns are tracked separately.

## Architecture-Level Options

### Option A: Keep Current RQAlpha-Per-Run Model

Apply low-risk optimizations only:

- timing metrics;
- clear only held positions;
- tune jobs/workers/thread env vars;
- shared close cache if adjustment semantics are handled.

Pros:

- low disruption;
- compatible with existing scripts and result files;
- preserves RQAlpha-first behavior.

Cons:

- still repeats the RQAlpha event loop for every strategy/frequency;
- total runtime scales linearly with run count.

### Option B: Signal Precompute + RQAlpha Execution

Precompute target schedules, then run RQAlpha as the execution/accounting layer.

Pros:

- best balance between speed and RQAlpha-first execution;
- easier to cache and inspect strategy decisions;
- strong path for parameter sweeps.

Cons:

- requires a new schedule format and adapter;
- must carefully test date alignment, listing status, suspension behavior, and
  tradability assumptions.

### Option C: Multi-Strategy In One RQAlpha Process

Attempt to run multiple independent strategies inside one RQAlpha process.

Pros:

- may share data loading and event loop.

Cons:

- RQAlpha portfolio/account state is not naturally multi-portfolio;
- significant complexity to keep independent results;
- less attractive than target-schedule precompute.

This is not the preferred path unless RQAlpha provides a clean multi-account
extension point.

## Recommended Roadmap

1. Add timing metrics and keep the current results as baseline.
2. Optimize order application to clear only existing non-target holdings.
3. Run a jobs/workers/thread experiment to find the best local parallelism.
4. Split fast, medium, and heavy strategy batches operationally.
5. Prototype a shared close matrix cache for close-only strategies.
6. Vectorize built-in signal generation or precompute target-weight schedules.
7. Rework `min_variance` and `max_sharpe` to use candidate caps or faster
   covariance approximations.

## Acceptance Criteria

For low-risk optimizations:

- same final portfolio value and summary metrics within numerical tolerance;
- same or explainably equivalent trade list;
- materially fewer order API calls;
- lower wall time on the same 34-run workload.

For architecture optimizations:

- target weights match the current implementation on sampled dates/codes;
- RQAlpha smoke tests pass on daily and weekly modes;
- full batch summary is reproducible from cached inputs;
- cache invalidation includes bundle path, date range, universe file, adjustment
  mode, and history window.
