# Bundle Update TODO

The project will use the RQAlpha bundle as the authoritative data source.
Incremental update support is intentionally deferred, but the future interface
should be designed around the existing bundle layout rather than a separate
SQLite backtest database.

## Goal

Provide one command that updates a local RQAlpha-compatible bundle from the
latest trusted data source, while preserving RQAlpha's expected file formats and
instrument identifiers.

Proposed command shape:

```bash
TUSHARE_TOKEN=... PYTHONPATH=strategy .venv/bin/python scripts/update_rqalpha_bundle.py update \
  --bundle data/rqalpha_bundle/bundle \
  --output-bundle data/rqalpha_bundle/bundle_2026-06-22 \
  --start 2026-06-01 \
  --end 2026-06-22 \
  --universe stock,index,etf
```

Compare converted Tushare rows with existing bundle rows before trusting a new
source:

```bash
TUSHARE_TOKEN=... PYTHONPATH=strategy .venv/bin/python scripts/update_rqalpha_bundle.py compare \
  --bundle data/rqalpha_bundle/bundle \
  --start 2026-05-28 \
  --end 2026-05-29 \
  --codes 000001,510300,159915,000300 \
  --universe stock,index,etf
```

## Open Questions

- Tushare Pro is the first supported upstream source.
- Tushare provides raw daily bars, limit prices, adjustment factors, dividends,
  fund dividends, suspension data, ETF bars, ETF factors, index bars, calendars,
  and instrument metadata for the first updater.
- Should updates modify the official bundle in place or write a new versioned
  bundle directory?
- How should failed partial updates roll back?
- How often should updates run: daily, weekly, or manually?

## Required Bundle Areas

Investigate and document each required file before writing updater code:

- `instruments.pk`
- `trading_dates.npy`
- `stocks.h5`
- `funds.h5`
- `indexes.h5`
- `dividends.h5`
- `ex_cum_factor.h5`
- `suspended_days.h5`
- `st_stock_days.h5`

## Implementation Steps

1. Read RQAlpha's bundle loader code and document exact schema expectations for
   each file.
2. Build read-only inspection utilities that print date ranges, instruments,
   fields, dtypes, and row counts for a bundle.
3. Decide update policy: in-place with backup, or write new bundle version then
   switch a symlink.
4. Implement a data-source abstraction that can fetch daily bars, calendar,
   instruments, dividends/factors, suspension, and ST status.
5. Implement schema validators before and after update.
6. Implement append/update logic per asset class.
7. Add a smoke test that runs `scripts/rqalpha_target_weight_demo.py` against
   the updated bundle.
8. Add a manifest file outside the bundle recording source, update time, date
   range, row counts, and validation result.

## First Tushare Mapping

- `stocks.h5`: `daily` plus `stk_limit`.
- `funds.h5`: `fund_daily` plus `stk_limit`.
- `indexes.h5`: `index_daily`.
- `ex_cum_factor.h5`: `adj_factor` and `fund_adj`, converted by factor ratios
  so the existing RQAlpha factor scale is preserved.
- `dividends.h5`: `dividend` and `fund_div`, converted to RQAlpha's per-10-lot
  cash dividend convention.
- `suspended_days.h5`: `suspend_d`, full-day suspension rows only.
- `st_stock_days.h5`: derived from `namechange` records until direct
  `stock_st` access is available.

## Near-Term Manual Process

Until the updater exists, use the official RQAlpha bundle as-is:

```bash
.venv/bin/rqalpha download-bundle -d data/rqalpha_bundle --confirm
```

If RQDatac credentials become available, test:

```bash
.venv/bin/rqalpha update-bundle -d data/rqalpha_bundle/bundle
```

Do not mix local SQLite bars into backtests unless they are first converted
into an RQAlpha-compatible bundle and validated.
