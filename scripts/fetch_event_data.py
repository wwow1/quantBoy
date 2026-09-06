#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-factor data collector: Tushare -> SQLite (data/event_factors.db).

Two modes, both resumable via a per-unit completion ledger (_meta):
  full        backfill [--start, --end] (default 2026-01-01 .. today),
              skipping units already collected so a crashed run resumes.
  incremental rolling refresh of the trailing --lookback-days window
              (ledger ignored); meant for the daily cron.
Rate limits: shared 50 calls/min for all APIs; report_rc is capped by
Tushare at 10 calls/rolling hour AND 10 calls/rolling day (failed calls
count too), so it gets its own 7min-spaced limiter and 30-day chunks
(6 cover 2026-01..09): a full backfill stays under both caps in ~40min,
leaving headroom for the daily cron's tail refresh.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import tushare as ts

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT / "data" / "event_factors.db"

# table -> primary key columns (used for INSERT OR REPLACE upserts)
PKS: Dict[str, Tuple[str, ...]] = {
    "forecast": ("ts_code", "end_date", "ann_date"),
    "express": ("ts_code", "end_date", "ann_date"),
    "repurchase": ("ts_code", "ann_date", "end_date", "proc"),
    "share_float": ("ts_code", "float_date", "ann_date", "holder_name"),
    "pledge_stat": ("ts_code", "end_date"),
    "stk_holdernumber": ("ts_code", "end_date"),
    "top_list": ("trade_date", "ts_code"),
    "block_trade": ("ts_code", "trade_date", "buyer", "seller"),
    "report_rc": ("ts_code", "report_date", "org_name", "report_title"),
    "margin_market": ("trade_date", "exchange_id"),
}


class RateLimiter:
    def __init__(self, calls_per_minute: float) -> None:
        self.min_interval = 60.0 / calls_per_minute
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        gap = self._last + self.min_interval - now
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()


# --------------------------------------------------------------------------- #
# Schema / upsert
# --------------------------------------------------------------------------- #
def _sql_type(dtype) -> str:
    if np.issubdtype(dtype, np.integer):
        return "INTEGER"
    if np.issubdtype(dtype, np.floating):
        return "REAL"
    return "TEXT"


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return str(value)
    return value


def ensure_table(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    cols = ", ".join(f'"{c}" {_sql_type(df[c].dtype)}' for c in df.columns)
    pk = ", ".join(f'"{c}"' for c in PKS[table])
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols}, PRIMARY KEY ({pk}))')


def upsert(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    df = df.drop_duplicates(subset=list(PKS[table]), keep="last")
    for pk_col in PKS[table]:
        df[pk_col] = df[pk_col].fillna("")
    ensure_table(conn, table, df)
    cols = list(df.columns)
    quoted = ", ".join('"' + c + '"' for c in cols)
    sql = f'INSERT OR REPLACE INTO "{table}" ({quoted}) VALUES ({", ".join("?" * len(cols))})'
    rows = [[_clean(v) for v in row] for row in df.itertuples(index=False, name=None)]
    conn.executemany(sql, rows)
    return len(rows)


# --------------------------------------------------------------------------- #
# Unit plan
# --------------------------------------------------------------------------- #
def trading_days(pro, start: str, end: str) -> List[str]:
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open="1")
    return sorted(cal["cal_date"].tolist())


def _chunks(days: List[str], size: int) -> List[Tuple[str, str]]:
    return [(days[i], days[min(i + size - 1, len(days) - 1)]) for i in range(0, len(days), size)]


def build_units(pro, start: str, end: str) -> Dict[str, List[Tuple[str, Tuple[str, object]]]]:
    """table -> list of (unit_key, (kind, value)) fetch specs."""
    days = trading_days(pro, start, end)
    if not days:
        return {}
    return {
        "forecast": [(f"ann:{d}", ("ann_date", d)) for d in days],
        "express": [(f"ann:{d}", ("ann_date", d)) for d in days],
        "stk_holdernumber": [(f"ann:{d}", ("ann_date", d)) for d in days],
        "top_list": [(f"td:{d}", ("trade_date", d)) for d in days],
        "block_trade": [(f"td:{d}", ("trade_date", d)) for d in days],
        "margin_market": [(f"td:{d}", ("trade_date", d)) for d in days],
        "repurchase": [(f"{a}..{b}", ("range", (a, b))) for a, b in _chunks(days, 21)],
        "share_float": [(f"{a}..{b}", ("range", (a, b))) for a, b in _chunks(days, 10)],
        "report_rc": [(f"{a}..{b}", ("range", (a, b))) for a, b in _chunks(days, 30)],
    }


FETCHERS: Dict[str, Callable] = {
    "forecast": lambda pro, kind, v: pro.forecast(ann_date=v) if kind == "ann_date" else None,
    "express": lambda pro, kind, v: pro.express(ann_date=v) if kind == "ann_date" else None,
    "stk_holdernumber": lambda pro, kind, v: pro.stk_holdernumber(ann_date=v) if kind == "ann_date" else None,
    "top_list": lambda pro, kind, v: pro.top_list(trade_date=v),
    "block_trade": lambda pro, kind, v: pro.block_trade(trade_date=v),
    "margin_market": lambda pro, kind, v: pro.margin(trade_date=v),
    "repurchase": lambda pro, kind, v: pro.repurchase(start_date=v[0], end_date=v[1]),
    "share_float": lambda pro, kind, v: pro.share_float(start_date=v[0], end_date=v[1]),
    "report_rc": lambda pro, kind, v: pro.report_rc(start_date=v[0], end_date=v[1]),
}


# --------------------------------------------------------------------------- #
# Sync
def sync(pro, db: Path, start: str, end: str, rate: float, tables: Optional[List[str]] = None,
         ignore_ledger: bool = False, tail_chunks: bool = False) -> int:
    conn = sqlite3.connect(db)
    done: Dict[str, set] = {}
    if not ignore_ledger:
        for tbl, unit, _rows in conn.execute("SELECT tbl, unit, rows FROM _meta"):
            done.setdefault(tbl, set()).add(unit)

    limiter = RateLimiter(rate)
    slow = RateLimiter(60.0 / 420.0)  # report_rc: 7min spacing, under 10/hour cap
    units = build_units(pro, start, end)
    if tail_chunks:
        units["report_rc"] = units["report_rc"][-1:]
    total_rows = 0
    for table, plan in units.items():
        if tables and table not in tables:
            continue
        pending = [(u, spec) for u, spec in plan if u not in done.get(table, set())]
        if not pending:
            continue
        print(f"[{table}] {len(pending)} units to fetch", flush=True)
        for unit, (kind, value) in pending:
            (slow if table == "report_rc" else limiter).wait()
            try:
                df = FETCHERS[table](pro, kind, value)
            except Exception as exc:
                msg = " ".join(str(exc).split())[:90]
                print(f"  WARN {table} {unit}: {msg}", flush=True)
                if table == "report_rc" and "频率超限" in str(exc):
                    print("  report_rc quota exhausted; aborting table "
                          "(failed calls count against quota)", flush=True)
                    break
                continue
            rows = upsert(conn, table, df)
            conn.execute("INSERT OR REPLACE INTO _meta (tbl, unit, rows) VALUES (?, ?, ?)", (table, unit, rows))
            conn.commit()
            total_rows += rows
            if rows:
                print(f"  {table} {unit}: +{rows}", flush=True)
    conn.commit()
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != '_meta'"):
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"table {t}: {n} rows", flush=True)
    conn.close()
    return total_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["full", "incremental"], default="incremental")
    parser.add_argument("--start", default="20260101")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--lookback-days", type=int, default=7,
                        help="incremental mode: trailing calendar days to reconcile")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--rate", type=float, default=50.0, help="shared calls per minute")
    parser.add_argument("--tables", default="", help="comma-separated subset")
    args = parser.parse_args()

    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        try:
            token = Path("/root/.tushare_token").read_text().strip()
        except Exception:
            pass
    if not token:
        print("ERROR: TUSHARE_TOKEN missing", file=sys.stderr)
        return 1
    pro = ts.pro_api(token)

    start = args.start
    if args.mode == "incremental":
        start = (datetime.now() - timedelta(days=args.lookback_days)).strftime("%Y%m%d")
    tables = [t.strip() for t in args.tables.split(",") if t.strip()] or None
    rows = sync(pro, Path(args.db), start, args.end, args.rate, tables,
                ignore_ledger=args.mode == "incremental",
                tail_chunks=args.mode == "incremental")
    print(f"done: {rows} rows written", flush=True)

if __name__ == "__main__":
    raise SystemExit(main())
