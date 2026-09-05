#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Incrementally update a local RQAlpha bundle from Tushare Pro.

The updater keeps RQAlpha as the only backtest data source. It converts Tushare
data into the existing bundle layout, then merges rows by date so the same code
path can append new days or rewrite a small overlap window.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import h5py
import numpy as np
import pandas as pd


SECURITY_DTYPE = np.dtype(
    [
        ("datetime", np.int64),
        ("open", np.float64),
        ("close", np.float64),
        ("high", np.float64),
        ("low", np.float64),
        ("prev_close", np.float64),
        ("limit_up", np.float64),
        ("limit_down", np.float64),
        ("volume", np.float64),
        ("total_turnover", np.float64),
    ]
)

INDEX_DTYPE = np.dtype(
    [
        ("datetime", np.int64),
        ("open", np.float64),
        ("close", np.float64),
        ("high", np.float64),
        ("low", np.float64),
        ("prev_close", np.float64),
        ("volume", np.float64),
        ("total_turnover", np.float64),
    ]
)

EX_FACTOR_DTYPE = np.dtype(
    [
        ("start_date", np.int64),
        ("ex_cum_factor", np.float64),
    ]
)

DIVIDEND_DTYPE = np.dtype(
    [
        ("book_closure_date", np.int64),
        ("announcement_date", np.float64),
        ("dividend_cash_before_tax", np.float64),
        ("ex_dividend_date", np.int64),
        ("payable_date", np.int64),
        ("round_lot", np.float64),
    ]
)

SUPPORTED_UNIVERSES = {"stock", "index", "etf"}
FUND_TYPES = {"ETF", "LOF", "REITs", "PUBLIC_FUND"}
DEFAULT_BUNDLE = "data/rqalpha_bundle/bundle"
DEFAULT_COMPARE_CODES = "000001,510300,159915,000300"

RQ_TO_TS_EXCHANGE = {
    "XSHG": "SH",
    "XSHE": "SZ",
    "XBSE": "BJ",
    "XBEI": "BJ",
}

TS_TO_RQ_EXCHANGE = {
    "SH": "XSHG",
    "SSE": "XSHG",
    "SZ": "XSHE",
    "SZSE": "XSHE",
    "BJ": "XBSE",
    "BSE": "XBSE",
}


@dataclass
class MergeStats:
    file: str
    instruments_seen: int = 0
    instruments_updated: int = 0
    rows_added_or_replaced: int = 0
    rows_after_merge: int = 0
    missing_limit_rows: int = 0
    skipped: int = 0


@dataclass
class UpdateManifest:
    source: str
    bundle: str
    started_at: str
    start: str
    end: str
    universe: List[str]
    dry_run: bool
    output_bundle: Optional[str] = None
    trading_dates: List[str] = field(default_factory=list)
    stats: Dict[str, Mapping[str, object]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update or compare an RQAlpha bundle using Tushare Pro data."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser(
        "update",
        help="Merge incremental Tushare data into a bundle.",
    )
    add_common_args(update)
    update.add_argument(
        "--output-bundle",
        default=None,
        help=(
            "Optional bundle directory to write. When set, the source bundle is "
            "copied before updates are applied."
        ),
    )
    update.add_argument(
        "--overwrite-output",
        action="store_true",
        help="Remove --output-bundle first if it already exists.",
    )
    update.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and convert data, but do not write HDF5/PKL files.",
    )
    update.add_argument(
        "--skip-st",
        action="store_true",
        help="Skip namechange-derived ST day updates.",
    )
    update.add_argument(
        "--manifest",
        default=None,
        help="Optional manifest JSON output path.",
    )
    update.add_argument(
        "--codes",
        default=None,
        help=(
            "Optional comma-separated codes to update. Accepts plain codes, "
            "Tushare codes, or RQAlpha order_book_ids. Omit for all bundle instruments."
        ),
    )
    update.add_argument(
        "--codes-file",
        default=None,
        help=(
            "Optional CSV file of codes to update. Uses order_book_id, code, or "
            "ts_code column when present; otherwise uses the first column."
        ),
    )
    update.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Extra sleep seconds after each Tushare request. Default: 0.",
    )
    update.add_argument(
        "--rate-limit-per-minute",
        type=int,
        default=180,
        help=(
            "Max paced Tushare requests per minute. Default: 180, below the "
            "common 200/minute quota. Use 0 to disable."
        ),
    )

    compare = subparsers.add_parser(
        "compare",
        help="Compare converted Tushare bars with existing bundle rows.",
    )
    add_common_args(compare)
    compare.add_argument(
        "--codes",
        default=None,
        help=(
            "Comma-separated sample codes. Accepts plain codes, Tushare codes, "
            "or RQAlpha order_book_ids. Defaults to "
            f"{DEFAULT_COMPARE_CODES} when --codes-file is not set."
        ),
    )
    compare.add_argument(
        "--codes-file",
        default=None,
        help=(
            "Optional CSV file of sample codes. Uses order_book_id, code, or "
            "ts_code column when present; otherwise uses the first column."
        ),
    )
    compare.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Extra sleep seconds after each Tushare request. Default: 0.",
    )
    compare.add_argument(
        "--rate-limit-per-minute",
        type=int,
        default=180,
        help=(
            "Max paced Tushare requests per minute. Default: 180, below the "
            "common 200/minute quota. Use 0 to disable."
        ),
    )
    compare.add_argument(
        "--tolerance",
        type=float,
        default=1e-6,
        help="Absolute warning tolerance for numeric comparisons.",
    )
    compare.add_argument(
        "--relative-tolerance",
        type=float,
        default=1e-8,
        help="Relative warning tolerance for numeric comparisons.",
    )
    return parser.parse_args()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--bundle",
        default=DEFAULT_BUNDLE,
        help="RQAlpha bundle directory.",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Start date, YYYY-MM-DD or YYYYMMDD.",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="End date, YYYY-MM-DD or YYYYMMDD.",
    )
    parser.add_argument(
        "--universe",
        default="stock,index,etf",
        help="Comma-separated universe keys: stock,index,etf.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Tushare token. Defaults to TUSHARE_TOKEN environment variable.",
    )


def normalize_date(value: str) -> str:
    raw = str(value).strip()
    if "-" in raw:
        return pd.Timestamp(raw).strftime("%Y%m%d")
    if len(raw) == 8 and raw.isdigit():
        return raw
    raise ValueError(f"Invalid date {value!r}; expected YYYY-MM-DD or YYYYMMDD")


def format_date(value: str) -> str:
    value = normalize_date(value)
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def date_to_dt_int(value: str) -> int:
    return int(normalize_date(value)) * 1_000_000


def dt_int_to_date(value: object) -> int:
    raw = int(value)
    return raw // 1_000_000 if raw > 100_000_000 else raw


def value_to_date_int(value: object, fallback: int = 0) -> int:
    if value is None:
        return fallback
    if isinstance(value, float) and np.isnan(value):
        return fallback
    raw = str(value).strip()
    if not raw or raw.lower() in {"none", "nan", "nat"}:
        return fallback
    return int(normalize_date(raw))


def value_to_date_float(value: object, fallback: float = np.nan) -> float:
    parsed = value_to_date_int(value, fallback=0)
    return float(parsed) if parsed else fallback


def parse_universe(raw: str) -> Set[str]:
    values = {item.strip().lower() for item in raw.split(",") if item.strip()}
    unknown = values - SUPPORTED_UNIVERSES
    if unknown:
        raise ValueError(f"Unsupported universe keys: {sorted(unknown)}")
    if not values:
        raise ValueError("--universe cannot be empty")
    return values


def rq_to_ts_code(order_book_id: str) -> str:
    code, exchange = str(order_book_id).split(".", 1)
    try:
        suffix = RQ_TO_TS_EXCHANGE[exchange]
    except KeyError as exc:
        raise ValueError(f"Unsupported RQAlpha exchange {exchange!r}") from exc
    return f"{code}.{suffix}"


def ts_to_rq_order_book_id(ts_code: object) -> str:
    code, suffix = str(ts_code).split(".", 1)
    try:
        exchange = TS_TO_RQ_EXCHANGE[suffix.upper()]
    except KeyError as exc:
        raise ValueError(f"Unsupported Tushare exchange suffix {suffix!r}") from exc
    return f"{code}.{exchange}"


def ensure_tushare(
    token: Optional[str],
    sleep: float,
    rate_limit_per_minute: int,
) -> "TushareSource":
    resolved = token or os.environ.get("TUSHARE_TOKEN")
    if not resolved:
        raise RuntimeError("Tushare token is required. Set TUSHARE_TOKEN or pass --token.")
    try:
        import tushare as ts
    except ImportError as exc:
        raise RuntimeError(
            "tushare is not installed. Run: .venv/bin/pip install -r strategy/requirements.txt"
        ) from exc
    return TushareSource(
        ts.pro_api(resolved),
        sleep=sleep,
        rate_limit_per_minute=rate_limit_per_minute,
    )


class RateLimiter:
    def __init__(self, calls_per_minute: int) -> None:
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute if calls_per_minute > 0 else 0.0
        self.next_allowed = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        if now < self.next_allowed:
            time.sleep(self.next_allowed - now)
            now = time.monotonic()
        self.next_allowed = now + self.min_interval


class TushareSource:
    def __init__(
        self,
        pro,
        sleep: float = 0.0,
        rate_limit_per_minute: int = 180,
    ) -> None:
        self.pro = pro
        self.sleep = sleep
        self.rate_limiter = RateLimiter(rate_limit_per_minute)
        self.request_count = 0

    def call(self, api_name: str, **kwargs) -> pd.DataFrame:
        clean_kwargs = {key: value for key, value in kwargs.items() if value is not None}
        api = getattr(self.pro, api_name)
        self.rate_limiter.wait()
        df = api(**clean_kwargs)
        self.request_count += 1
        if self.sleep > 0:
            time.sleep(self.sleep)
        if df is None:
            return pd.DataFrame()
        return df.copy()


def load_instruments(bundle: Path) -> List[Dict[str, object]]:
    with (bundle / "instruments.pk").open("rb") as file:
        return pickle.load(file)


def load_trading_dates(bundle: Path) -> List[str]:
    path = bundle / "trading_dates.npy"
    values = np.load(path, allow_pickle=False)
    return [str(int(value)) for value in values]


def trading_dates_between(source: TushareSource, start: str, end: str) -> List[str]:
    df = source.call(
        "trade_cal",
        exchange="SSE",
        start_date=start,
        end_date=end,
        is_open="1",
    )
    if df.empty:
        return []
    return sorted(str(value) for value in df["cal_date"].tolist())


def previous_local_trading_date(bundle: Path, start: str) -> Optional[str]:
    dates = load_trading_dates(bundle)
    before = [item for item in dates if item < start]
    return before[-1] if before else None


def normalize_code_arg(code: str, instruments: Sequence[Dict[str, object]]) -> Optional[str]:
    raw = code.strip()
    if not raw:
        return None
    if "." in raw:
        suffix = raw.split(".", 1)[1].upper()
        if suffix in TS_TO_RQ_EXCHANGE:
            return ts_to_rq_order_book_id(raw.upper())
        return raw.upper()
    matches = [
        str(item["order_book_id"])
        for item in instruments
        if str(item.get("trading_code") or item.get("order_book_id", "").split(".", 1)[0]) == raw
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return sorted(matches)[0]
    return None


def load_codes_file(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(path)

    frame = pd.read_csv(path, dtype=str, comment="#")
    preferred_columns = [
        column for column in ("order_book_id", "code", "ts_code") if column in frame.columns
    ]
    if preferred_columns:
        values = frame[preferred_columns[0]].dropna().astype(str).tolist()
    else:
        frame = pd.read_csv(path, dtype=str, header=None, comment="#")
        if frame.empty or frame.shape[1] == 0:
            raise ValueError(f"codes file is empty: {path}")
        values = frame.iloc[:, 0].dropna().astype(str).tolist()
        if values and values[0].strip().lower() in {"order_book_id", "code", "ts_code"}:
            values = values[1:]

    codes = [value.strip() for value in values if value and value.strip()]
    if not codes:
        raise ValueError(f"codes file contains no codes: {path}")
    return codes


def build_code_filter(
    instruments: Sequence[Dict[str, object]],
    codes: Optional[str] = None,
    codes_file: Optional[str] = None,
) -> Optional[Set[str]]:
    raw_codes: List[str] = []
    if codes_file:
        raw_codes.extend(load_codes_file(Path(codes_file)))
    if codes:
        raw_codes.extend(code for code in codes.split(",") if code.strip())

    if not raw_codes:
        return None

    normalized: Set[str] = set()
    unmatched: List[str] = []
    for code in raw_codes:
        order_book_id = normalize_code_arg(code, instruments)
        if order_book_id:
            normalized.add(order_book_id)
        else:
            unmatched.append(code)

    if unmatched:
        preview = ", ".join(unmatched[:10])
        suffix = "..." if len(unmatched) > 10 else ""
        print(
            f"WARNING: skipped {len(unmatched)} codes not found in instruments.pk: {preview}{suffix}",
            file=sys.stderr,
        )
    if not normalized:
        raise ValueError("No selected codes match instruments.pk")
    return normalized


def select_instruments(
    instruments: Sequence[Dict[str, object]],
    universe: Set[str],
    codes: Optional[str] = None,
    codes_file: Optional[str] = None,
) -> Dict[str, List[str]]:
    code_filter = build_code_filter(instruments, codes=codes, codes_file=codes_file)

    selected = {"stock": [], "index": [], "etf": []}
    for instrument in instruments:
        order_book_id = str(instrument.get("order_book_id") or "")
        if not order_book_id or (code_filter is not None and order_book_id not in code_filter):
            continue
        ins_type = str(instrument.get("type") or "")
        if "stock" in universe and ins_type == "CS":
            selected["stock"].append(order_book_id)
        elif "index" in universe and ins_type == "INDX":
            selected["index"].append(order_book_id)
        elif "etf" in universe and ins_type in FUND_TYPES:
            selected["etf"].append(order_book_id)

    return {key: sorted(set(values)) for key, values in selected.items()}


def copy_bundle_if_needed(source: Path, output: Optional[str], overwrite: bool) -> Path:
    if output is None:
        return source
    target = Path(output)
    if target.exists():
        if not overwrite:
            raise FileExistsError(f"{target} already exists; pass --overwrite-output to replace it")
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def read_h5_dataset(path: Path, key: str, dtype: np.dtype) -> np.ndarray:
    if not path.exists():
        return np.empty(0, dtype=dtype)
    with h5py.File(path, "r") as h5:
        if key not in h5:
            return np.empty(0, dtype=dtype)
        return h5[key][:]


def merge_structured(existing: np.ndarray, new: np.ndarray, key_field: str) -> np.ndarray:
    if len(new) == 0:
        return existing
    if len(existing) == 0:
        merged = new
    else:
        new_keys = set(int(value) for value in new[key_field].tolist())
        keep_mask = np.array([int(value) not in new_keys for value in existing[key_field]])
        merged = np.concatenate([existing[keep_mask], new.astype(existing.dtype, copy=False)])
    order = np.argsort(merged[key_field], kind="mergesort")
    return merged[order]


def merge_int_dates(existing: np.ndarray, new_dates: Iterable[int]) -> np.ndarray:
    values = {int(value) for value in existing.tolist()} if len(existing) else set()
    values.update(int(value) for value in new_dates)
    return np.array(sorted(values), dtype=np.int64)


def write_dataset(path: Path, key: str, data: np.ndarray, dry_run: bool) -> None:
    if dry_run:
        return
    with h5py.File(path, "a") as h5:
        if key in h5:
            del h5[key]
        h5.create_dataset(key, data=data)


def dataframe_to_security_records(
    price: pd.DataFrame,
    limits: pd.DataFrame,
    wanted: Set[str],
) -> Tuple[Dict[str, np.ndarray], int]:
    if price.empty:
        return {}, 0
    df = price.copy()
    # Drop codes whose exchange suffix the bundle cannot represent
    # (Tushare daily/fund_daily may include OTC open-end funds '*.OF').
    df = df[
        df["ts_code"].map(
            lambda c: str(c).rsplit(".", 1)[-1].upper() in TS_TO_RQ_EXCHANGE
        )
    ]
    if df.empty:
        return {}, 0
    df["order_book_id"] = df["ts_code"].map(ts_to_rq_order_book_id)
    df = df[df["order_book_id"].isin(wanted)]
    if df.empty:
        return {}, 0

    if limits.empty:
        df["up_limit"] = np.nan
        df["down_limit"] = np.nan
    else:
        limit_cols = limits[["ts_code", "trade_date", "up_limit", "down_limit"]].copy()
        df = df.merge(limit_cols, on=["ts_code", "trade_date"], how="left")

    records: Dict[str, List[tuple]] = {}
    missing_limits = 0
    for row in df.itertuples(index=False):
        limit_up = float_or_nan(getattr(row, "up_limit", np.nan))
        limit_down = float_or_nan(getattr(row, "down_limit", np.nan))
        if np.isnan(limit_up) or np.isnan(limit_down):
            missing_limits += 1
        item = (
            date_to_dt_int(str(row.trade_date)),
            float(row.open),
            float(row.close),
            float(row.high),
            float(row.low),
            float(row.pre_close),
            limit_up,
            limit_down,
            float(row.vol) * 100.0,
            float(row.amount) * 1000.0,
        )
        records.setdefault(str(row.order_book_id), []).append(item)

    return {
        key: np.array(sorted(values, key=lambda item: item[0]), dtype=SECURITY_DTYPE)
        for key, values in records.items()
    }, missing_limits


def dataframe_to_index_records(price: pd.DataFrame, wanted: Set[str]) -> Dict[str, np.ndarray]:
    if price.empty:
        return {}
    df = price.copy()
    df["order_book_id"] = df["ts_code"].map(ts_to_rq_order_book_id)
    df = df[df["order_book_id"].isin(wanted)]
    records: Dict[str, List[tuple]] = {}
    for row in df.itertuples(index=False):
        item = (
            date_to_dt_int(str(row.trade_date)),
            float(row.open),
            float(row.close),
            float(row.high),
            float(row.low),
            float(row.pre_close),
            float(row.vol) * 100.0,
            float(row.amount) * 1000.0,
        )
        records.setdefault(str(row.order_book_id), []).append(item)
    return {
        key: np.array(sorted(values, key=lambda item: item[0]), dtype=INDEX_DTYPE)
        for key, values in records.items()
    }


def float_or_nan(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return np.nan
    return parsed


def fetch_security_bars(
    source: TushareSource,
    api_name: str,
    dates: Sequence[str],
    wanted_order_book_ids: Sequence[str],
) -> Tuple[Dict[str, np.ndarray], int]:
    wanted = set(wanted_order_book_ids)
    all_records: Dict[str, List[np.ndarray]] = {}
    missing_limits = 0
    for trading_date in dates:
        price = source.call(api_name, trade_date=trading_date)
        limits = source.call("stk_limit", trade_date=trading_date)
        records, missing = dataframe_to_security_records(price, limits, wanted)
        missing_limits += missing
        for order_book_id, data in records.items():
            all_records.setdefault(order_book_id, []).append(data)
    return {
        key: np.concatenate(chunks).astype(SECURITY_DTYPE, copy=False)
        for key, chunks in all_records.items()
        if chunks
    }, missing_limits


def fetch_index_bars(
    source: TushareSource,
    start: str,
    end: str,
    wanted_order_book_ids: Sequence[str],
) -> Dict[str, np.ndarray]:
    records: Dict[str, np.ndarray] = {}
    wanted = set(wanted_order_book_ids)
    for order_book_id in wanted_order_book_ids:
        try:
            ts_code = rq_to_ts_code(order_book_id)
        except ValueError:
            continue
        price = source.call("index_daily", ts_code=ts_code, start_date=start, end_date=end)
        converted = dataframe_to_index_records(price, wanted)
        records.update(converted)
    return records


def merge_bar_file(
    bundle: Path,
    file_name: str,
    dtype: np.dtype,
    records: Mapping[str, np.ndarray],
    dry_run: bool,
    missing_limits: int = 0,
) -> MergeStats:
    stats = MergeStats(file=file_name, missing_limit_rows=missing_limits)
    path = bundle / file_name
    for order_book_id, new_data in records.items():
        stats.instruments_seen += 1
        existing = read_h5_dataset(path, order_book_id, dtype)
        merged = merge_structured(existing.astype(dtype, copy=False), new_data, "datetime")
        if len(new_data):
            stats.instruments_updated += 1
            stats.rows_added_or_replaced += len(new_data)
            stats.rows_after_merge += len(merged)
            write_dataset(path, order_book_id, merged, dry_run=dry_run)
    return stats


def fetch_factor_rows(
    source: TushareSource,
    api_name: str,
    dates: Sequence[str],
    wanted_order_book_ids: Sequence[str],
) -> Dict[str, pd.DataFrame]:
    wanted = set(wanted_order_book_ids)
    chunks = []
    for trading_date in dates:
        df = source.call(api_name, trade_date=trading_date)
        if df.empty:
            continue
        # Drop codes whose exchange suffix the bundle cannot represent
        # (fund_adj also returns OTC open-end funds like '000001.OF').
        df = df[
            df["ts_code"].map(
                lambda c: str(c).rsplit(".", 1)[-1].upper() in TS_TO_RQ_EXCHANGE
            )
        ]
        if df.empty:
            continue
        df = df.copy()
        df["order_book_id"] = df["ts_code"].map(ts_to_rq_order_book_id)
        df = df[df["order_book_id"].isin(wanted)]
        if not df.empty:
            chunks.append(df[["order_book_id", "trade_date", "adj_factor"]])
    if not chunks:
        return {}
    data = pd.concat(chunks, ignore_index=True)
    result = {}
    for order_book_id, group in data.groupby("order_book_id"):
        result[str(order_book_id)] = group.sort_values("trade_date")
    return result


def current_factor_before(existing: np.ndarray, start_dt_int: int) -> float:
    if len(existing) == 0:
        return 1.0
    before = existing[existing["start_date"] < start_dt_int]
    if len(before) == 0:
        return 1.0
    return float(before[-1]["ex_cum_factor"])


def build_ex_factor_events(
    bundle: Path,
    order_book_id: str,
    factor_rows: pd.DataFrame,
    start: str,
) -> np.ndarray:
    if factor_rows.empty:
        return np.empty(0, dtype=EX_FACTOR_DTYPE)

    existing = read_h5_dataset(bundle / "ex_cum_factor.h5", order_book_id, EX_FACTOR_DTYPE)
    start_dt_int = date_to_dt_int(start)
    base_rq_factor = current_factor_before(existing, start_dt_int)

    rows = factor_rows.sort_values("trade_date")
    baseline_adj = float(rows.iloc[0]["adj_factor"])
    previous_adj = baseline_adj
    events = []
    for row in rows.itertuples(index=False):
        trade_date = str(row.trade_date)
        adj_factor = float(row.adj_factor)
        if trade_date < start:
            previous_adj = adj_factor
            baseline_adj = adj_factor
            continue
        if not np.isclose(adj_factor, previous_adj, rtol=0.0, atol=1e-12):
            rq_factor = base_rq_factor * (adj_factor / baseline_adj)
            events.append((date_to_dt_int(trade_date), rq_factor))
        previous_adj = adj_factor

    return np.array(events, dtype=EX_FACTOR_DTYPE)


def update_ex_factors(
    bundle: Path,
    source: TushareSource,
    start: str,
    factor_dates: Sequence[str],
    stock_ids: Sequence[str],
    fund_ids: Sequence[str],
    dry_run: bool,
) -> MergeStats:
    stats = MergeStats(file="ex_cum_factor.h5")
    stock_rows = fetch_factor_rows(source, "adj_factor", factor_dates, stock_ids)
    fund_rows = fetch_factor_rows(source, "fund_adj", factor_dates, fund_ids)
    all_rows = {**stock_rows, **fund_rows}
    path = bundle / "ex_cum_factor.h5"
    for order_book_id, rows in all_rows.items():
        new_events = build_ex_factor_events(bundle, order_book_id, rows, start)
        stats.instruments_seen += 1
        if len(new_events) == 0:
            continue
        existing = read_h5_dataset(path, order_book_id, EX_FACTOR_DTYPE)
        merged = merge_structured(existing.astype(EX_FACTOR_DTYPE, copy=False), new_events, "start_date")
        stats.instruments_updated += 1
        stats.rows_added_or_replaced += len(new_events)
        stats.rows_after_merge += len(merged)
        write_dataset(path, order_book_id, merged, dry_run=dry_run)
    return stats


def fetch_dividends_for_dates(
    source: TushareSource,
    dates: Sequence[str],
    stock_ids: Sequence[str],
    fund_ids: Sequence[str],
) -> Dict[str, np.ndarray]:
    stock_ts = {rq_to_ts_code(order_book_id) for order_book_id in stock_ids}
    fund_ts = {rq_to_ts_code(order_book_id) for order_book_id in fund_ids}
    records: Dict[str, List[tuple]] = {}
    for trading_date in dates:
        stock_div = source.call("dividend", ex_date=trading_date)
        if not stock_div.empty:
            stock_div = stock_div[stock_div["ts_code"].isin(stock_ts)]
            for row in stock_div.itertuples(index=False):
                order_book_id = ts_to_rq_order_book_id(row.ts_code)
                cash = float_or_nan(getattr(row, "cash_div_tax", np.nan))
                if np.isnan(cash):
                    cash = float_or_nan(getattr(row, "cash_div", np.nan))
                records.setdefault(order_book_id, []).append(
                    (
                        value_to_date_int(getattr(row, "record_date", None), value_to_date_int(row.ex_date)),
                        value_to_date_float(getattr(row, "ann_date", None)),
                        cash * 10.0,
                        value_to_date_int(row.ex_date),
                        value_to_date_int(getattr(row, "pay_date", None), value_to_date_int(row.ex_date)),
                        10.0,
                    )
                )

        fund_div = source.call("fund_div", ex_date=trading_date)
        if not fund_div.empty:
            fund_div = fund_div[fund_div["ts_code"].isin(fund_ts)]
            fund_div = fund_div.drop_duplicates(["ts_code", "ex_date", "pay_date", "div_cash"])
            for row in fund_div.itertuples(index=False):
                order_book_id = ts_to_rq_order_book_id(row.ts_code)
                cash = float_or_nan(getattr(row, "div_cash", np.nan))
                records.setdefault(order_book_id, []).append(
                    (
                        value_to_date_int(getattr(row, "record_date", None), value_to_date_int(row.ex_date)),
                        value_to_date_float(getattr(row, "ann_date", None)),
                        cash * 10.0,
                        value_to_date_int(row.ex_date),
                        value_to_date_int(getattr(row, "pay_date", None), value_to_date_int(row.ex_date)),
                        10.0,
                    )
                )
    return {
        key: np.array(sorted(values, key=lambda item: item[0]), dtype=DIVIDEND_DTYPE)
        for key, values in records.items()
    }


def update_dividends(
    bundle: Path,
    source: TushareSource,
    dates: Sequence[str],
    stock_ids: Sequence[str],
    fund_ids: Sequence[str],
    dry_run: bool,
) -> MergeStats:
    path = bundle / "dividends.h5"
    records = fetch_dividends_for_dates(source, dates, stock_ids, fund_ids)
    stats = MergeStats(file="dividends.h5")
    for order_book_id, new_data in records.items():
        stats.instruments_seen += 1
        existing = read_h5_dataset(path, order_book_id, DIVIDEND_DTYPE)
        merged = merge_structured(existing.astype(DIVIDEND_DTYPE, copy=False), new_data, "book_closure_date")
        stats.instruments_updated += 1
        stats.rows_added_or_replaced += len(new_data)
        stats.rows_after_merge += len(merged)
        write_dataset(path, order_book_id, merged, dry_run=dry_run)
    return stats


def update_suspended_days(
    bundle: Path,
    source: TushareSource,
    start: str,
    end: str,
    stock_ids: Sequence[str],
    dry_run: bool,
) -> MergeStats:
    stats = MergeStats(file="suspended_days.h5")
    wanted_ts = {rq_to_ts_code(order_book_id) for order_book_id in stock_ids}
    df = source.call("suspend_d", start_date=start, end_date=end)
    if df.empty:
        return stats
    df = df[df["ts_code"].isin(wanted_ts)]
    df = df[df["suspend_type"] == "S"]
    if "suspend_timing" in df.columns:
        df = df[df["suspend_timing"].isna()]

    grouped: Dict[str, List[int]] = {}
    for row in df.itertuples(index=False):
        grouped.setdefault(ts_to_rq_order_book_id(row.ts_code), []).append(int(row.trade_date))

    path = bundle / "suspended_days.h5"
    for order_book_id, dates in grouped.items():
        stats.instruments_seen += 1
        existing = read_h5_dataset(path, order_book_id, np.dtype(np.int64))
        merged = merge_int_dates(existing.astype(np.int64, copy=False), dates)
        stats.instruments_updated += 1
        stats.rows_added_or_replaced += len(set(dates))
        stats.rows_after_merge += len(merged)
        write_dataset(path, order_book_id, merged, dry_run=dry_run)
    return stats


def update_st_days_from_namechange(
    bundle: Path,
    source: TushareSource,
    start: str,
    end: str,
    trading_dates: Sequence[str],
    stock_ids: Sequence[str],
    previous_trading_date: Optional[str],
    dry_run: bool,
) -> MergeStats:
    stats = MergeStats(file="st_stock_days.h5")
    path = bundle / "st_stock_days.h5"
    stock_set = set(stock_ids)
    new_date_ints = [int(item) for item in trading_dates]

    # Extend names that were already ST on the prior bundle date.
    for order_book_id in stock_ids:
        existing = read_h5_dataset(path, order_book_id, np.dtype(np.int64))
        if len(existing) == 0:
            continue
        if previous_trading_date and int(np.max(existing)) >= int(previous_trading_date):
            merged = merge_int_dates(existing.astype(np.int64, copy=False), new_date_ints)
            stats.instruments_seen += 1
            stats.instruments_updated += 1
            stats.rows_added_or_replaced += len(new_date_ints)
            stats.rows_after_merge += len(merged)
            write_dataset(path, order_book_id, merged, dry_run=dry_run)

    df = source.call("namechange", start_date=start, end_date=end)
    if df.empty:
        return stats
    df["order_book_id"] = df["ts_code"].map(ts_to_rq_order_book_id)
    df = df[df["order_book_id"].isin(stock_set)]
    if df.empty:
        return stats

    for order_book_id, group in df.groupby("order_book_id"):
        existing = read_h5_dataset(path, order_book_id, np.dtype(np.int64))
        values = set(int(value) for value in existing.tolist()) if len(existing) else set()
        for row in group.itertuples(index=False):
            reason = str(getattr(row, "change_reason", "") or "")
            name = str(getattr(row, "name", "") or "")
            row_start = max(str(getattr(row, "start_date", start)), start)
            row_end_raw = getattr(row, "end_date", None)
            row_end = min(str(row_end_raw), end) if row_end_raw else end
            affected = [
                int(item)
                for item in trading_dates
                if row_start <= item <= row_end
            ]
            if "撤销ST" in reason:
                values.difference_update(affected)
            elif "ST" in reason or name.startswith("ST") or name.startswith("*ST"):
                values.update(affected)
        merged = np.array(sorted(values), dtype=np.int64)
        stats.instruments_seen += 1
        stats.instruments_updated += 1
        stats.rows_after_merge += len(merged)
        write_dataset(path, order_book_id, merged, dry_run=dry_run)
    return stats


def stats_to_dict(stats: MergeStats) -> Dict[str, object]:
    return {
        "file": stats.file,
        "instruments_seen": stats.instruments_seen,
        "instruments_updated": stats.instruments_updated,
        "rows_added_or_replaced": stats.rows_added_or_replaced,
        "rows_after_merge": stats.rows_after_merge,
        "missing_limit_rows": stats.missing_limit_rows,
        "skipped": stats.skipped,
    }


def command_update(args: argparse.Namespace) -> int:
    source_bundle = Path(args.bundle)
    if not source_bundle.exists():
        raise FileNotFoundError(source_bundle)

    start = normalize_date(args.start)
    end = normalize_date(args.end)
    universe = parse_universe(args.universe)
    source = ensure_tushare(
        args.token,
        sleep=args.sleep,
        rate_limit_per_minute=args.rate_limit_per_minute,
    )
    target_bundle = copy_bundle_if_needed(source_bundle, args.output_bundle, args.overwrite_output)

    instruments = load_instruments(target_bundle)
    selection = select_instruments(
        instruments,
        universe,
        codes=args.codes,
        codes_file=args.codes_file,
    )
    trading_dates = trading_dates_between(source, start, end)
    if not trading_dates:
        raise RuntimeError(f"No open trading dates found between {start} and {end}")

    previous_date = previous_local_trading_date(target_bundle, start)
    factor_dates = ([previous_date] if previous_date else []) + trading_dates

    manifest = UpdateManifest(
        source="tushare",
        bundle=str(source_bundle),
        output_bundle=str(target_bundle) if target_bundle != source_bundle else None,
        started_at=datetime.now().isoformat(timespec="seconds"),
        start=format_date(start),
        end=format_date(end),
        universe=sorted(universe),
        dry_run=bool(args.dry_run),
        trading_dates=trading_dates,
    )
    manifest.notes.append(
        f"Tushare requests are paced at {args.rate_limit_per_minute} calls/minute."
    )
    if args.codes_file:
        manifest.notes.append(f"Code selection loaded from {args.codes_file}.")
    if args.codes:
        manifest.notes.append(f"Code selection also includes --codes={args.codes}.")

    if "stock" in universe:
        stock_records, missing_limits = fetch_security_bars(
            source,
            "daily",
            trading_dates,
            selection["stock"],
        )
        stats = merge_bar_file(
            target_bundle,
            "stocks.h5",
            SECURITY_DTYPE,
            stock_records,
            dry_run=args.dry_run,
            missing_limits=missing_limits,
        )
        manifest.stats["stocks.h5"] = stats_to_dict(stats)

        suspended = update_suspended_days(
            target_bundle,
            source,
            start,
            end,
            selection["stock"],
            dry_run=args.dry_run,
        )
        manifest.stats["suspended_days.h5"] = stats_to_dict(suspended)

        if args.skip_st:
            manifest.notes.append("ST day update skipped by --skip-st.")
        else:
            st_stats = update_st_days_from_namechange(
                target_bundle,
                source,
                start,
                end,
                trading_dates,
                selection["stock"],
                previous_date,
                dry_run=args.dry_run,
            )
            manifest.stats["st_stock_days.h5"] = stats_to_dict(st_stats)
            manifest.notes.append("ST days are derived from Tushare namechange records.")

    if "etf" in universe:
        fund_records, missing_limits = fetch_security_bars(
            source,
            "fund_daily",
            trading_dates,
            selection["etf"],
        )
        stats = merge_bar_file(
            target_bundle,
            "funds.h5",
            SECURITY_DTYPE,
            fund_records,
            dry_run=args.dry_run,
            missing_limits=missing_limits,
        )
        manifest.stats["funds.h5"] = stats_to_dict(stats)

    if "index" in universe:
        index_records = fetch_index_bars(
            source,
            start,
            end,
            selection["index"],
        )
        stats = merge_bar_file(
            target_bundle,
            "indexes.h5",
            INDEX_DTYPE,
            index_records,
            dry_run=args.dry_run,
        )
        manifest.stats["indexes.h5"] = stats_to_dict(stats)

    factor_stock_ids = selection["stock"] if "stock" in universe else []
    factor_etf_ids = selection["etf"] if "etf" in universe else []
    if factor_stock_ids or factor_etf_ids:
        factor_stats = update_ex_factors(
            target_bundle,
            source,
            start,
            factor_dates,
            factor_stock_ids,
            factor_etf_ids,
            dry_run=args.dry_run,
        )
    else:
        factor_stats = MergeStats(file="ex_cum_factor.h5")
    manifest.stats["ex_cum_factor.h5"] = stats_to_dict(factor_stats)

    if factor_stock_ids or factor_etf_ids:
        dividend_stats = update_dividends(
            target_bundle,
            source,
            trading_dates,
            factor_stock_ids,
            factor_etf_ids,
            dry_run=args.dry_run,
        )
    else:
        dividend_stats = MergeStats(file="dividends.h5")
    manifest.stats["dividends.h5"] = stats_to_dict(dividend_stats)

    if args.manifest:
        manifest_path = Path(args.manifest)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        manifest_path = target_bundle.parent / f"quantboy_bundle_update_{stamp}.json"
    manifest.stats["tushare_requests"] = {"count": source.request_count}
    if not args.dry_run or args.manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8") as file:
            json.dump(manifest.__dict__, file, ensure_ascii=False, indent=2)

    print(json.dumps(manifest.__dict__, ensure_ascii=False, indent=2))
    return 0


def fetch_sample_records(
    source: TushareSource,
    start: str,
    end: str,
    stock_ids: Sequence[str],
    fund_ids: Sequence[str],
    index_ids: Sequence[str],
) -> Dict[str, Tuple[str, np.ndarray]]:
    dates = trading_dates_between(source, start, end)
    result: Dict[str, Tuple[str, np.ndarray]] = {}
    if stock_ids:
        records, _ = fetch_security_bars(source, "daily", dates, stock_ids)
        result.update({key: ("stocks.h5", value) for key, value in records.items()})
    if fund_ids:
        records, _ = fetch_security_bars(source, "fund_daily", dates, fund_ids)
        result.update({key: ("funds.h5", value) for key, value in records.items()})
    if index_ids:
        records = fetch_index_bars(source, start, end, index_ids)
        result.update({key: ("indexes.h5", value) for key, value in records.items()})
    return result


def compare_records(
    bundle: Path,
    samples: Mapping[str, Tuple[str, np.ndarray]],
    tolerance: float,
    relative_tolerance: float,
) -> List[Dict[str, object]]:
    rows = []
    for order_book_id, (file_name, tushare_data) in samples.items():
        dtype = SECURITY_DTYPE if file_name in {"stocks.h5", "funds.h5"} else INDEX_DTYPE
        existing = read_h5_dataset(bundle / file_name, order_book_id, dtype)
        existing_by_date = {int(row["datetime"]): row for row in existing}
        for row in tushare_data:
            dt = int(row["datetime"])
            if dt not in existing_by_date:
                rows.append(
                    {
                        "order_book_id": order_book_id,
                        "file": file_name,
                        "datetime": dt,
                        "status": "missing_in_bundle",
                    }
                )
                continue
            bundle_row = existing_by_date[dt]
            diffs = {}
            for field in dtype.names:
                if field == "datetime":
                    continue
                left = float(bundle_row[field])
                right = float(row[field])
                diff = abs(left - right)
                allowed = max(tolerance, relative_tolerance * max(1.0, abs(left), abs(right)))
                if diff > allowed:
                    diffs[field] = diff
            rows.append(
                {
                    "order_book_id": order_book_id,
                    "file": file_name,
                    "datetime": dt,
                    "status": "ok" if not diffs else "diff",
                    "max_abs_diff": max(diffs.values()) if diffs else 0.0,
                    "diff_fields": diffs,
                }
            )
    return rows


def command_compare(args: argparse.Namespace) -> int:
    bundle = Path(args.bundle)
    start = normalize_date(args.start)
    end = normalize_date(args.end)
    universe = parse_universe(args.universe)
    source = ensure_tushare(
        args.token,
        sleep=args.sleep,
        rate_limit_per_minute=args.rate_limit_per_minute,
    )
    instruments = load_instruments(bundle)
    codes = args.codes
    if not codes and not args.codes_file:
        codes = DEFAULT_COMPARE_CODES
    selection = select_instruments(
        instruments,
        universe,
        codes=codes,
        codes_file=args.codes_file,
    )
    samples = fetch_sample_records(
        source,
        start,
        end,
        selection["stock"],
        selection["etf"],
        selection["index"],
    )
    rows = compare_records(bundle, samples, args.tolerance, args.relative_tolerance)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 1 if any(row.get("status") == "diff" for row in rows) else 0


def main() -> int:
    args = parse_args()
    if args.command == "update":
        return command_update(args)
    if args.command == "compare":
        return command_compare(args)
    raise RuntimeError(f"Unsupported command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
