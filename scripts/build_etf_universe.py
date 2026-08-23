#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build reusable strategy universes from the local RQAlpha bundle metadata.
"""

from __future__ import annotations

import argparse
import csv
import math
import pickle
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd
import requests


HS300_CONS_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/"
    "file/autofile/cons/000300cons.xls"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build universe files from RQAlpha instruments.pk."
    )
    parser.add_argument(
        "--bundle",
        default="data/rqalpha_bundle/bundle",
        help="RQAlpha bundle directory.",
    )
    parser.add_argument(
        "--preset",
        default="all_etf",
        choices=[
            "broad_etf",
            "all_etf",
            "all_etf_liquid",
            "hs300",
            "all_etf_plus_hs300",
            "all_etf_liquid_plus_hs300",
        ],
        help="Universe preset to build.",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Optional backtest start date. Excludes instruments delisted before this date.",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Optional backtest end date. Excludes instruments listed after this date.",
    )
    parser.add_argument(
        "--fund-types",
        default=None,
        help=(
            "Optional comma-separated fund_type filter. Defaults to StockIndex "
            "for ETF presets; use 'all' to include Money/Bond/QDII/Other ETFs."
        ),
    )
    parser.add_argument(
        "--hs300-file",
        default=None,
        help=(
            "Optional CSV/XLS file for current HS300 stock constituents. "
            "If omitted for hs300 presets, downloads the latest official CSI file."
        ),
    )
    parser.add_argument(
        "--min-latest-size",
        type=float,
        default=500_000_000,
        help="Minimum latest_size for liquid ETF presets. Default: 500,000,000.",
    )
    parser.add_argument(
        "--min-listed-days",
        type=int,
        default=120,
        help="Minimum days listed before --start for liquid ETF presets. Default: 120.",
    )
    parser.add_argument(
        "--include-hk",
        action="store_true",
        help="Include Hong Kong/Hang Seng related ETFs in liquid ETF presets.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output CSV path.",
    )
    return parser.parse_args()


def parse_date(value: object) -> Optional[pd.Timestamp]:
    if value in (None, "", "0000-00-00"):
        return None
    try:
        return pd.Timestamp(value)
    except Exception:
        return None


def load_instruments(bundle: Path) -> List[Dict[str, object]]:
    path = bundle / "instruments.pk"
    with path.open("rb") as file:
        return pickle.load(file)


def parse_fund_types(raw: Optional[str]) -> Optional[set[str]]:
    if raw is None:
        return None
    if raw.strip().lower() == "all":
        return None
    fund_types = {item.strip() for item in raw.split(",") if item.strip()}
    if not fund_types:
        raise ValueError("--fund-types cannot be empty")
    return fund_types


BROAD_ETF_CODES = {
    "510300",
    "510500",
    "159915",
    "510050",
    "588000",
}


def normalize_code(value: object) -> str:
    code = str(value).strip()
    if "." in code:
        code = code.split(".", 1)[0]
    return code


def instrument_row(instrument: Dict[str, object], universe: str) -> Dict[str, object]:
    order_book_id = str(instrument.get("order_book_id"))
    return {
        "code": normalize_code(order_book_id),
        "order_book_id": order_book_id,
        "symbol": instrument.get("symbol"),
        "exchange": instrument.get("exchange"),
        "instrument_type": instrument.get("type"),
        "fund_type": instrument.get("fund_type"),
        "listed_date": instrument.get("listed_date"),
        "de_listed_date": instrument.get("de_listed_date"),
        "status": instrument.get("status"),
        "latest_size": instrument.get("latest_size"),
        "universe": universe,
    }


def parse_float(value: object) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def in_period(
    instrument: Dict[str, object],
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
) -> bool:
    listed_date = parse_date(instrument.get("listed_date"))
    de_listed_date = parse_date(instrument.get("de_listed_date"))

    if end is not None and listed_date is not None and listed_date > end:
        return False
    if start is not None and de_listed_date is not None and de_listed_date < start:
        return False
    return True


def is_hk_related(instrument: Dict[str, object]) -> bool:
    symbol = str(instrument.get("symbol") or "")
    underlying_name = str(instrument.get("underlying_name") or "")
    text = f"{symbol}{underlying_name}"
    return any(keyword in text for keyword in ["港股", "恒生", "香港"])


def passes_liquid_filter(
    instrument: Dict[str, object],
    start: Optional[pd.Timestamp],
    min_latest_size: float,
    min_listed_days: int,
    include_hk: bool,
) -> bool:
    latest_size = parse_float(instrument.get("latest_size"))
    if latest_size is None or latest_size < min_latest_size:
        return False

    listed_date = parse_date(instrument.get("listed_date"))
    if start is None or listed_date is None:
        return False
    if listed_date > start - pd.Timedelta(days=min_listed_days):
        return False

    if not include_hk and is_hk_related(instrument):
        return False
    return True


def load_hs300_codes_from_csv(path: Path) -> List[str]:
    codes = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            code = normalize_code(line.split(",", 1)[0])
            if line_number == 1 and code.lower() in {"code", "order_book_id"}:
                continue
            if code:
                codes.append(code)
    if not codes:
        raise ValueError(f"HS300 file is empty: {path}")
    return list(dict.fromkeys(codes))


def extract_hs300_codes_from_xls(content: bytes) -> List[str]:
    codes = []
    for match in re.findall(rb"(?<!\d)\d{6}(?!\d)", content):
        code = match.decode("ascii")
        if code == "000300":
            continue
        if code.startswith(("0", "3", "6")):
            codes.append(code)

    deduped = list(dict.fromkeys(codes))
    if len(deduped) < 250:
        raise ValueError(f"too few HS300 codes parsed from XLS: {len(deduped)}")
    return deduped[:300]


def download_hs300_codes() -> List[str]:
    response = requests.get(
        HS300_CONS_URL,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    return extract_hs300_codes_from_xls(response.content)


def load_hs300_codes(path: Optional[Path]) -> List[str]:
    if path is None:
        return download_hs300_codes()
    if path.suffix.lower() == ".xls":
        return extract_hs300_codes_from_xls(path.read_bytes())
    return load_hs300_codes_from_csv(path)


def stock_exchange(code: str) -> str:
    if code.startswith(("5", "6", "9")):
        return "XSHG"
    return "XSHE"


def build_hs300_rows(
    instruments_by_order_book_id: Dict[str, Dict[str, object]],
    codes: Sequence[str],
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
    universe: str,
) -> List[Dict[str, object]]:
    rows = []
    missing = []
    for code in codes:
        order_book_id = f"{code}.{stock_exchange(code)}"
        instrument = instruments_by_order_book_id.get(order_book_id)
        if instrument is None:
            missing.append(order_book_id)
            continue
        if not in_period(instrument, start, end):
            continue
        rows.append(instrument_row(instrument, universe))
    if missing:
        preview = ", ".join(missing[:10])
        print(f"warning: missing HS300 instruments: {len(missing)} ({preview})")
    return rows


def build_etf_rows(
    instruments: Sequence[Dict[str, object]],
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
    fund_types: Optional[set[str]],
    broad_only: bool,
    liquid_only: bool,
    min_latest_size: float,
    min_listed_days: int,
    include_hk: bool,
    universe: str,
) -> List[Dict[str, object]]:
    rows = []
    for instrument in instruments:
        if instrument.get("type") != "ETF":
            continue
        code = normalize_code(instrument.get("order_book_id"))
        if broad_only and code not in BROAD_ETF_CODES:
            continue
        if fund_types is not None and instrument.get("fund_type") not in fund_types:
            continue
        if not in_period(instrument, start, end):
            continue
        if liquid_only and not passes_liquid_filter(
            instrument,
            start,
            min_latest_size,
            min_listed_days,
            include_hk,
        ):
            continue
        rows.append(instrument_row(instrument, universe))

    return sorted(rows, key=lambda row: row["order_book_id"])


def build_rows(args: argparse.Namespace) -> List[Dict[str, object]]:
    bundle = Path(args.bundle)
    instruments = load_instruments(bundle)
    instruments_by_order_book_id = {
        str(instrument.get("order_book_id")): instrument
        for instrument in instruments
    }
    start = parse_date(args.start)
    end = parse_date(args.end)
    fund_types = parse_fund_types(args.fund_types)
    if args.fund_types is None and args.preset in {
        "broad_etf",
        "all_etf",
        "all_etf_liquid",
        "all_etf_plus_hs300",
        "all_etf_liquid_plus_hs300",
    }:
        fund_types = {"StockIndex"}

    rows = []
    if args.preset in {
        "broad_etf",
        "all_etf",
        "all_etf_liquid",
        "all_etf_plus_hs300",
        "all_etf_liquid_plus_hs300",
    }:
        liquid_only = args.preset in {
            "all_etf_liquid",
            "all_etf_liquid_plus_hs300",
        }
        rows.extend(
            build_etf_rows(
                instruments,
                start,
                end,
                fund_types,
                broad_only=args.preset == "broad_etf",
                liquid_only=liquid_only,
                min_latest_size=args.min_latest_size,
                min_listed_days=args.min_listed_days,
                include_hk=args.include_hk,
                universe=(
                    "broad_etf"
                    if args.preset == "broad_etf"
                    else "all_etf_liquid"
                    if liquid_only
                    else "all_etf"
                ),
            )
        )

    if args.preset in {"hs300", "all_etf_plus_hs300", "all_etf_liquid_plus_hs300"}:
        rows.extend(
            build_hs300_rows(
                instruments_by_order_book_id,
                load_hs300_codes(Path(args.hs300_file) if args.hs300_file else None),
                start,
                end,
                universe="hs300",
            )
        )

    deduped = {}
    for row in rows:
        deduped[row["order_book_id"]] = row
    return sorted(deduped.values(), key=lambda row: row["order_book_id"])


def write_rows(rows: Iterable[Dict[str, object]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "code",
        "order_book_id",
        "symbol",
        "exchange",
        "instrument_type",
        "fund_type",
        "listed_date",
        "de_listed_date",
        "status",
        "latest_size",
        "universe",
    ]
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    rows = build_rows(args)
    output = Path(args.output)
    write_rows(rows, output)
    print(f"{args.preset} universe: {len(rows)}")
    print(f"output: {output}")


if __name__ == "__main__":
    main()
