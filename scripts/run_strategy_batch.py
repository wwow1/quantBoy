#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run built-in QuantBoy target-weight strategies in batch through RQAlpha.
"""

from __future__ import annotations

import argparse
import os
import pickle
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml


DEFAULT_STRATEGIES = [
    "equal_weight",
    "momentum",
    "ma_trend",
    "dual_ma",
    "mean_reversion",
    "low_volatility",
    "risk_parity",
    "trend_timing",
    "absolute_momentum",
    "dual_momentum",
    "volatility_target",
    "drawdown_control",
    "trend_risk_parity",
    "min_variance",
    "max_sharpe",
    "low_volatility_trend",
    "sector_rotation",
    "risk_adjusted_momentum",
    "trend_filtered_momentum",
    "momentum_risk_parity",
    "composite_momentum",
    "breakout_momentum",
    "drawdown_adjusted_momentum",
    "trailing_sharpe_momentum",
    "accelerating_momentum",
    "stateful_accelerating_momentum",
    "stateful_accelerating_ensemble",
    "calendar_filtered_stateful_ensemble",
    "date_window_stateful_ensemble",
    "scheduled_rotation",
    "smoothed_momentum",
    "bundle_multifactor_momentum",
    "stateful_bundle_multifactor_momentum",
]

DEFAULT_CONFIG = "config/backtest.yaml"
DEFAULT_CODES = "510300,510500,159915,510050,588000"
SUPPORTED_REBALANCES = ["daily", "weekly", "monthly"]


@dataclass(frozen=True)
class StrategySpec:
    name: str
    env: Dict[str, str]


@dataclass(frozen=True)
class BatchRun:
    name: str
    codes: Optional[Any]
    codes_file: Optional[str]
    output_dir: Optional[str]


STRATEGY_SPECS = {
    "equal_weight": StrategySpec("equal_weight", {}),
    "momentum": StrategySpec(
        "momentum",
        {
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "120",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "1",
        },
    ),
    "ma_trend": StrategySpec(
        "ma_trend",
        {
            "QUANTBOY_RQ_MA_WINDOW": "120",
        },
    ),
    "dual_ma": StrategySpec(
        "dual_ma",
        {
            "QUANTBOY_RQ_SHORT_WINDOW": "20",
            "QUANTBOY_RQ_LONG_WINDOW": "120",
        },
    ),
    "mean_reversion": StrategySpec(
        "mean_reversion",
        {
            "QUANTBOY_RQ_MEAN_REVERSION_LOOKBACK": "20",
            "QUANTBOY_RQ_MEAN_REVERSION_TOP_K": "1",
            "QUANTBOY_RQ_TREND_WINDOW": "120",
        },
    ),
    "low_volatility": StrategySpec(
        "low_volatility",
        {
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
            "QUANTBOY_RQ_LOW_VOLATILITY_TOP_K": "3",
        },
    ),
    "risk_parity": StrategySpec(
        "risk_parity",
        {
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
        },
    ),
    "trend_timing": StrategySpec(
        "trend_timing",
        {
            "QUANTBOY_RQ_TREND_WINDOW": "200",
        },
    ),
    "absolute_momentum": StrategySpec(
        "absolute_momentum",
        {
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "120",
            "QUANTBOY_RQ_MIN_RETURN": "0",
        },
    ),
    "dual_momentum": StrategySpec(
        "dual_momentum",
        {
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "120",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "1",
            "QUANTBOY_RQ_MIN_RETURN": "0",
        },
    ),
    "volatility_target": StrategySpec(
        "volatility_target",
        {
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
            "QUANTBOY_RQ_TARGET_VOLATILITY": "0.10",
            "QUANTBOY_RQ_MAX_LEVERAGE": "1.0",
        },
    ),
    "drawdown_control": StrategySpec(
        "drawdown_control",
        {
            "QUANTBOY_RQ_DRAWDOWN_LOOKBACK": "120",
            "QUANTBOY_RQ_MAX_DRAWDOWN": "0.08",
        },
    ),
    "trend_risk_parity": StrategySpec(
        "trend_risk_parity",
        {
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
            "QUANTBOY_RQ_TREND_WINDOW": "120",
        },
    ),
    "min_variance": StrategySpec(
        "min_variance",
        {
            "QUANTBOY_RQ_COVARIANCE_LOOKBACK": "120",
        },
    ),
    "max_sharpe": StrategySpec(
        "max_sharpe",
        {
            "QUANTBOY_RQ_COVARIANCE_LOOKBACK": "120",
        },
    ),
    "low_volatility_trend": StrategySpec(
        "low_volatility_trend",
        {
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
            "QUANTBOY_RQ_LOW_VOLATILITY_TOP_K": "3",
            "QUANTBOY_RQ_TREND_WINDOW": "120",
        },
    ),
    "sector_rotation": StrategySpec(
        "sector_rotation",
        {
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "120",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "1",
        },
    ),
    "risk_adjusted_momentum": StrategySpec(
        "risk_adjusted_momentum",
        {
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "120",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "3",
        },
    ),
    "trend_filtered_momentum": StrategySpec(
        "trend_filtered_momentum",
        {
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "120",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "3",
            "QUANTBOY_RQ_TREND_WINDOW": "120",
        },
    ),
    "momentum_risk_parity": StrategySpec(
        "momentum_risk_parity",
        {
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "120",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "5",
        },
    ),
    "composite_momentum": StrategySpec(
        "composite_momentum",
        {
            "QUANTBOY_RQ_SHORT_LOOKBACK": "20",
            "QUANTBOY_RQ_MEDIUM_LOOKBACK": "60",
            "QUANTBOY_RQ_LONG_LOOKBACK": "120",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "3",
        },
    ),
    "breakout_momentum": StrategySpec(
        "breakout_momentum",
        {
            "QUANTBOY_RQ_BREAKOUT_WINDOW": "120",
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "60",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "3",
        },
    ),
    "drawdown_adjusted_momentum": StrategySpec(
        "drawdown_adjusted_momentum",
        {
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "220",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "50",
            "QUANTBOY_RQ_DRAWDOWN_LOOKBACK": "120",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "2",
            "QUANTBOY_RQ_DRAWDOWN_PENALTY": "2.0",
        },
    ),
    "trailing_sharpe_momentum": StrategySpec(
        "trailing_sharpe_momentum",
        {
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "120",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "2",
            "QUANTBOY_RQ_MIN_RETURN": "0",
        },
    ),
    "accelerating_momentum": StrategySpec(
        "accelerating_momentum",
        {
            "QUANTBOY_RQ_SHORT_LOOKBACK": "20",
            "QUANTBOY_RQ_LONG_LOOKBACK": "220",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "50",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "1",
            "QUANTBOY_RQ_SHORT_WEIGHT": "1.0",
        },
    ),
    "stateful_accelerating_momentum": StrategySpec(
        "stateful_accelerating_momentum",
        {
            "QUANTBOY_RQ_SHORT_LOOKBACK": "10",
            "QUANTBOY_RQ_LONG_LOOKBACK": "200",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "80",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "1",
            "QUANTBOY_RQ_SHORT_WEIGHT": "1.5",
            "QUANTBOY_RQ_TRAILING_DRAWDOWN": "0.08",
            "QUANTBOY_RQ_MA_EXIT_WINDOW": "20",
            "QUANTBOY_RQ_COOLDOWN_WEEKS": "1",
            "QUANTBOY_RQ_ALLOW_SWITCH": "1",
            "QUANTBOY_RQ_MIN_SCORE": "",
            "QUANTBOY_RQ_MARKET_FILTER": "0",
            "QUANTBOY_RQ_MARKET_FILTER_CODE": "510300",
            "QUANTBOY_RQ_MARKET_TREND_WINDOW": "120",
            "QUANTBOY_RQ_MARKET_MIN_MOMENTUM": "",
            "QUANTBOY_RQ_PROFIT_LOCK_TRIGGER": "",
            "QUANTBOY_RQ_PROFIT_LOCK_DRAWDOWN": "",
        },
    ),
    "stateful_accelerating_ensemble": StrategySpec(
        "stateful_accelerating_ensemble",
        {},
    ),
    "calendar_filtered_stateful_ensemble": StrategySpec(
        "calendar_filtered_stateful_ensemble",
        {
            "QUANTBOY_RQ_TAKE_PROFIT": "0.8",
            "QUANTBOY_RQ_ACTIVE_MONTHS": "2,4,5,6",
        },
    ),
    "date_window_stateful_ensemble": StrategySpec(
        "date_window_stateful_ensemble",
        {
            "QUANTBOY_RQ_TAKE_PROFIT": "0.8",
            "QUANTBOY_RQ_ACTIVE_RANGES": "",
        },
    ),
    "scheduled_rotation": StrategySpec(
        "scheduled_rotation",
        {
            "QUANTBOY_RQ_SCHEDULE": "",
        },
    ),
    "smoothed_momentum": StrategySpec(
        "smoothed_momentum",
        {
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "180",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "2",
        },
    ),
    "bundle_multifactor_momentum": StrategySpec(
        "bundle_multifactor_momentum",
        {
            "QUANTBOY_RQ_LONG_LOOKBACK": "220",
            "QUANTBOY_RQ_MEDIUM_LOOKBACK": "60",
            "QUANTBOY_RQ_SHORT_LOOKBACK": "20",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "50",
            "QUANTBOY_RQ_DRAWDOWN_LOOKBACK": "120",
            "QUANTBOY_RQ_BREAKOUT_WINDOW": "120",
            "QUANTBOY_RQ_LIQUIDITY_LOOKBACK": "20",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "2",
            "QUANTBOY_RQ_MIN_RETURN": "0",
            "QUANTBOY_RQ_MIN_TREND_STRENGTH": "0",
            "QUANTBOY_RQ_FACTOR_PROFILE": "trend_quality",
            "QUANTBOY_RQ_WEIGHT_MODE": "equal",
        },
    ),
    "stateful_bundle_multifactor_momentum": StrategySpec(
        "stateful_bundle_multifactor_momentum",
        {
            "QUANTBOY_RQ_LONG_LOOKBACK": "220",
            "QUANTBOY_RQ_MEDIUM_LOOKBACK": "60",
            "QUANTBOY_RQ_SHORT_LOOKBACK": "20",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "50",
            "QUANTBOY_RQ_DRAWDOWN_LOOKBACK": "120",
            "QUANTBOY_RQ_BREAKOUT_WINDOW": "120",
            "QUANTBOY_RQ_LIQUIDITY_LOOKBACK": "20",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "1",
            "QUANTBOY_RQ_MIN_RETURN": "0",
            "QUANTBOY_RQ_MIN_TREND_STRENGTH": "0",
            "QUANTBOY_RQ_FACTOR_PROFILE": "trend_quality",
            "QUANTBOY_RQ_TRAILING_DRAWDOWN": "0.08",
            "QUANTBOY_RQ_MA_EXIT_WINDOW": "20",
            "QUANTBOY_RQ_COOLDOWN_WEEKS": "1",
            "QUANTBOY_RQ_ALLOW_SWITCH": "1",
        },
    ),
}

STRATEGY_PARAMETER_ENV = {
    "momentum": {
        "lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
    },
    "ma_trend": {
        "window": "QUANTBOY_RQ_MA_WINDOW",
    },
    "dual_ma": {
        "short_window": "QUANTBOY_RQ_SHORT_WINDOW",
        "long_window": "QUANTBOY_RQ_LONG_WINDOW",
    },
    "mean_reversion": {
        "lookback": "QUANTBOY_RQ_MEAN_REVERSION_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MEAN_REVERSION_TOP_K",
        "trend_window": "QUANTBOY_RQ_TREND_WINDOW",
    },
    "low_volatility": {
        "lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "top_k": "QUANTBOY_RQ_LOW_VOLATILITY_TOP_K",
    },
    "risk_parity": {
        "lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
    },
    "trend_timing": {
        "window": "QUANTBOY_RQ_TREND_WINDOW",
    },
    "absolute_momentum": {
        "lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "min_return": "QUANTBOY_RQ_MIN_RETURN",
    },
    "dual_momentum": {
        "lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
        "min_return": "QUANTBOY_RQ_MIN_RETURN",
    },
    "volatility_target": {
        "lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "target_volatility": "QUANTBOY_RQ_TARGET_VOLATILITY",
        "max_leverage": "QUANTBOY_RQ_MAX_LEVERAGE",
    },
    "drawdown_control": {
        "lookback": "QUANTBOY_RQ_DRAWDOWN_LOOKBACK",
        "max_drawdown": "QUANTBOY_RQ_MAX_DRAWDOWN",
    },
    "trend_risk_parity": {
        "lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "trend_window": "QUANTBOY_RQ_TREND_WINDOW",
    },
    "min_variance": {
        "lookback": "QUANTBOY_RQ_COVARIANCE_LOOKBACK",
    },
    "max_sharpe": {
        "lookback": "QUANTBOY_RQ_COVARIANCE_LOOKBACK",
    },
    "low_volatility_trend": {
        "lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "top_k": "QUANTBOY_RQ_LOW_VOLATILITY_TOP_K",
        "trend_window": "QUANTBOY_RQ_TREND_WINDOW",
    },
    "sector_rotation": {
        "lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
    },
    "risk_adjusted_momentum": {
        "momentum_lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "volatility_lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
    },
    "trend_filtered_momentum": {
        "lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
        "trend_window": "QUANTBOY_RQ_TREND_WINDOW",
    },
    "momentum_risk_parity": {
        "momentum_lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "volatility_lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
    },
    "composite_momentum": {
        "short_lookback": "QUANTBOY_RQ_SHORT_LOOKBACK",
        "medium_lookback": "QUANTBOY_RQ_MEDIUM_LOOKBACK",
        "long_lookback": "QUANTBOY_RQ_LONG_LOOKBACK",
        "volatility_lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
    },
    "breakout_momentum": {
        "breakout_window": "QUANTBOY_RQ_BREAKOUT_WINDOW",
        "momentum_lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
    },
    "drawdown_adjusted_momentum": {
        "momentum_lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "volatility_lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "drawdown_lookback": "QUANTBOY_RQ_DRAWDOWN_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
        "drawdown_penalty": "QUANTBOY_RQ_DRAWDOWN_PENALTY",
    },
    "trailing_sharpe_momentum": {
        "lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
        "min_return": "QUANTBOY_RQ_MIN_RETURN",
    },
    "accelerating_momentum": {
        "short_lookback": "QUANTBOY_RQ_SHORT_LOOKBACK",
        "long_lookback": "QUANTBOY_RQ_LONG_LOOKBACK",
        "volatility_lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
        "short_weight": "QUANTBOY_RQ_SHORT_WEIGHT",
    },
    "stateful_accelerating_momentum": {
        "short_lookback": "QUANTBOY_RQ_SHORT_LOOKBACK",
        "long_lookback": "QUANTBOY_RQ_LONG_LOOKBACK",
        "volatility_lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
        "short_weight": "QUANTBOY_RQ_SHORT_WEIGHT",
        "trailing_drawdown": "QUANTBOY_RQ_TRAILING_DRAWDOWN",
        "take_profit": "QUANTBOY_RQ_TAKE_PROFIT",
        "ma_exit_window": "QUANTBOY_RQ_MA_EXIT_WINDOW",
        "cooldown_weeks": "QUANTBOY_RQ_COOLDOWN_WEEKS",
        "allow_switch": "QUANTBOY_RQ_ALLOW_SWITCH",
        "min_score": "QUANTBOY_RQ_MIN_SCORE",
        "market_filter": "QUANTBOY_RQ_MARKET_FILTER",
        "market_filter_code": "QUANTBOY_RQ_MARKET_FILTER_CODE",
        "market_trend_window": "QUANTBOY_RQ_MARKET_TREND_WINDOW",
        "market_min_momentum": "QUANTBOY_RQ_MARKET_MIN_MOMENTUM",
        "profit_lock_trigger": "QUANTBOY_RQ_PROFIT_LOCK_TRIGGER",
        "profit_lock_drawdown": "QUANTBOY_RQ_PROFIT_LOCK_DRAWDOWN",
    },
    "stateful_accelerating_ensemble": {
        "take_profit": "QUANTBOY_RQ_TAKE_PROFIT",
    },
    "calendar_filtered_stateful_ensemble": {
        "take_profit": "QUANTBOY_RQ_TAKE_PROFIT",
        "active_months": "QUANTBOY_RQ_ACTIVE_MONTHS",
    },
    "date_window_stateful_ensemble": {
        "take_profit": "QUANTBOY_RQ_TAKE_PROFIT",
        "active_ranges": "QUANTBOY_RQ_ACTIVE_RANGES",
    },
    "scheduled_rotation": {
        "schedule": "QUANTBOY_RQ_SCHEDULE",
    },
    "smoothed_momentum": {
        "lookback": "QUANTBOY_RQ_MOMENTUM_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
    },
    "bundle_multifactor_momentum": {
        "long_lookback": "QUANTBOY_RQ_LONG_LOOKBACK",
        "medium_lookback": "QUANTBOY_RQ_MEDIUM_LOOKBACK",
        "short_lookback": "QUANTBOY_RQ_SHORT_LOOKBACK",
        "volatility_lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "drawdown_lookback": "QUANTBOY_RQ_DRAWDOWN_LOOKBACK",
        "breakout_window": "QUANTBOY_RQ_BREAKOUT_WINDOW",
        "liquidity_lookback": "QUANTBOY_RQ_LIQUIDITY_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
        "min_long_momentum": "QUANTBOY_RQ_MIN_RETURN",
        "min_trend_strength": "QUANTBOY_RQ_MIN_TREND_STRENGTH",
        "factor_profile": "QUANTBOY_RQ_FACTOR_PROFILE",
        "weight_mode": "QUANTBOY_RQ_WEIGHT_MODE",
    },
    "stateful_bundle_multifactor_momentum": {
        "long_lookback": "QUANTBOY_RQ_LONG_LOOKBACK",
        "medium_lookback": "QUANTBOY_RQ_MEDIUM_LOOKBACK",
        "short_lookback": "QUANTBOY_RQ_SHORT_LOOKBACK",
        "volatility_lookback": "QUANTBOY_RQ_VOLATILITY_LOOKBACK",
        "drawdown_lookback": "QUANTBOY_RQ_DRAWDOWN_LOOKBACK",
        "breakout_window": "QUANTBOY_RQ_BREAKOUT_WINDOW",
        "liquidity_lookback": "QUANTBOY_RQ_LIQUIDITY_LOOKBACK",
        "top_k": "QUANTBOY_RQ_MOMENTUM_TOP_K",
        "min_long_momentum": "QUANTBOY_RQ_MIN_RETURN",
        "min_trend_strength": "QUANTBOY_RQ_MIN_TREND_STRENGTH",
        "factor_profile": "QUANTBOY_RQ_FACTOR_PROFILE",
        "trailing_drawdown": "QUANTBOY_RQ_TRAILING_DRAWDOWN",
        "ma_exit_window": "QUANTBOY_RQ_MA_EXIT_WINDOW",
        "cooldown_weeks": "QUANTBOY_RQ_COOLDOWN_WEEKS",
        "allow_switch": "QUANTBOY_RQ_ALLOW_SWITCH",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-run QuantBoy strategies through RQAlpha."
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help="YAML config file. Defaults to config/backtest.yaml.",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="Ignore the YAML config file and use command line/default values only.",
    )
    parser.add_argument("--start", default=None, help="Backtest start date, YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Backtest end date, YYYY-MM-DD.")
    parser.add_argument(
        "--strategies",
        default=None,
        help="Comma-separated strategy keys.",
    )
    parser.add_argument(
        "--codes",
        default=None,
        help="Comma-separated stock/ETF codes passed to QuantBoy strategies.",
    )
    parser.add_argument(
        "--codes-file",
        default=None,
        help=(
            "Optional universe file. Reads the first CSV column from each row. "
            "When set, this overrides --codes."
        ),
    )
    parser.add_argument(
        "--rebalance",
        default=None,
        choices=SUPPORTED_REBALANCES,
        help="Single rebalance frequency controlled by the QuantBoy adapter.",
    )
    parser.add_argument(
        "--rebalances",
        default=None,
        help=(
            "Comma-separated rebalance frequencies, or 'all'. "
            "When set, this overrides --rebalance."
        ),
    )
    parser.add_argument(
        "--history-bars",
        type=int,
        default=None,
        help="History bars requested from RQAlpha for each strategy decision.",
    )
    parser.add_argument(
        "--history-cache-workers",
        type=int,
        default=None,
        help="Worker threads per RQAlpha process for preloading bundle close history.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help="Number of RQAlpha strategy combinations to run concurrently.",
    )
    parser.add_argument(
        "--max-total-weight",
        type=float,
        default=None,
        help="Max gross target weight before orders are sent to RQAlpha.",
    )
    parser.add_argument(
        "--use-pre-start-history",
        action="store_true",
        default=None,
        help="Allow strategy signals to use bundle history before the backtest start date.",
    )
    parser.add_argument(
        "--min-avg-turnover",
        type=float,
        default=None,
        help="Minimum trailing average turnover in yuan for strategy candidates.",
    )
    parser.add_argument(
        "--liquidity-lookback",
        type=int,
        default=None,
        help="Trailing bars used by --min-avg-turnover. Defaults to 20.",
    )
    parser.add_argument(
        "--avoid-limit-trades",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Avoid submitting orders on limit-up/limit-down bars. Defaults to true.",
    )
    parser.add_argument(
        "--exclude-buy-boards",
        default=None,
        help=(
            "Comma-separated stock boards that cannot be bought or added. "
            "Supported values: star, chinext."
        ),
    )
    parser.add_argument(
        "--cash",
        type=float,
        default=None,
        help="Initial stock account cash.",
    )
    parser.add_argument(
        "--benchmark",
        default=None,
        help="RQAlpha benchmark order_book_id.",
    )
    parser.add_argument(
        "--slippage",
        type=float,
        default=None,
        help="RQAlpha price-ratio slippage.",
    )
    parser.add_argument(
        "--bundle",
        default=None,
        help="RQAlpha bundle directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory. Defaults to outputs/backtests/<start>_<end>.",
    )
    parser.add_argument(
        "--rqalpha-bin",
        default=None,
        help="Path to rqalpha executable.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="RQAlpha log level.",
    )
    args = parser.parse_args()
    args.cli_universe_override = any(
        item == "--codes"
        or item.startswith("--codes=")
        or item == "--codes-file"
        or item.startswith("--codes-file=")
        for item in sys.argv[1:]
    )
    args.cli_rebalance_override = any(
        item == "--rebalance" or item.startswith("--rebalance=")
        for item in sys.argv[1:]
    ) and not any(
        item == "--rebalances" or item.startswith("--rebalances=")
        for item in sys.argv[1:]
    )
    return args


def load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError(f"config must be a YAML object: {config_path}")
    return config


def _stringify(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return _stringify(value)


def _list_or_csv(raw: Any, field: str) -> List[str]:
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        return [_stringify(item).strip() for item in raw if _stringify(item).strip()]
    raise ValueError(f"{field} must be a comma-separated string or YAML list")


def _csv_codes(raw: Any, field: str) -> str:
    return ",".join(_list_or_csv(raw, field))


def _config_value(args: argparse.Namespace, config: Dict[str, Any], key: str, default: Any) -> Any:
    value = getattr(args, key)
    if value is not None:
        return value
    return config.get(key, default)


def apply_config(args: argparse.Namespace, config: Dict[str, Any]) -> argparse.Namespace:
    args.start = _string_or_none(_config_value(args, config, "start", None))
    args.end = _string_or_none(_config_value(args, config, "end", None))
    args.strategies = _config_value(args, config, "strategies", DEFAULT_STRATEGIES)
    args.codes = _config_value(args, config, "codes", None)
    args.codes_file = _string_or_none(_config_value(args, config, "codes_file", None))
    args.rebalance = _string_or_none(_config_value(args, config, "rebalance", "daily"))
    args.rebalances = None if args.cli_rebalance_override else _config_value(
        args,
        config,
        "rebalances",
        None,
    )
    args.history_bars = int(_config_value(args, config, "history_bars", 260))
    args.use_pre_start_history = bool(
        _config_value(args, config, "use_pre_start_history", False)
    )
    args.min_avg_turnover = float(_config_value(args, config, "min_avg_turnover", 0.0))
    args.liquidity_lookback = int(_config_value(args, config, "liquidity_lookback", 20))
    args.avoid_limit_trades = bool(_config_value(args, config, "avoid_limit_trades", True))
    args.exclude_buy_boards = _list_or_csv(
        _config_value(args, config, "exclude_buy_boards", []),
        "exclude_buy_boards",
    )
    args.history_cache_workers = int(
        _config_value(args, config, "history_cache_workers", 8)
    )
    args.jobs = int(_config_value(args, config, "jobs", 1))
    args.max_total_weight = float(_config_value(args, config, "max_total_weight", 0.99))
    args.cash = float(_config_value(args, config, "cash", 100_000))
    args.benchmark = _string_or_none(_config_value(args, config, "benchmark", "000300.XSHG"))
    args.slippage = float(_config_value(args, config, "slippage", 0.001))
    args.bundle = _string_or_none(
        _config_value(args, config, "bundle", "data/rqalpha_bundle/bundle")
    )
    args.output_dir = _string_or_none(_config_value(args, config, "output_dir", None))
    args.rqalpha_bin = _string_or_none(
        _config_value(args, config, "rqalpha_bin", ".venv/bin/rqalpha")
    )
    args.log_level = _string_or_none(_config_value(args, config, "log_level", "error"))
    args.strategy_parameters = config.get("strategy_parameters", {})
    args.config_runs = [] if args.cli_universe_override else config.get("runs", [])

    missing = [name for name in ["start", "end"] if not getattr(args, name)]
    if missing:
        names = ", ".join(f"--{name}" for name in missing)
        raise ValueError(f"missing required backtest date(s): {names}")
    return args


def parse_strategies(raw: Any) -> List[str]:
    strategies = _list_or_csv(raw, "strategies")
    unknown = [name for name in strategies if name not in STRATEGY_SPECS]
    if unknown:
        supported = ", ".join(sorted(STRATEGY_SPECS))
        raise ValueError(f"unsupported strategies: {unknown}; supported: {supported}")
    return strategies


def parse_rebalances(raw: Any, fallback: str) -> List[str]:
    if raw is None:
        return [fallback]
    if isinstance(raw, str) and raw.strip() == "all":
        return SUPPORTED_REBALANCES
    rebalances = _list_or_csv(raw, "rebalances")
    unknown = [rebalance for rebalance in rebalances if rebalance not in SUPPORTED_REBALANCES]
    if unknown:
        supported = ", ".join(SUPPORTED_REBALANCES)
        raise ValueError(f"unsupported rebalances: {unknown}; supported: {supported}")
    if not rebalances:
        raise ValueError("--rebalances cannot be empty")
    return rebalances


def parse_strategy_parameter_env(strategy: str, raw: Dict[str, Any]) -> Dict[str, str]:
    supported = STRATEGY_PARAMETER_ENV.get(strategy, {})
    env = {}
    for key, value in raw.items():
        if key.startswith("QUANTBOY_RQ_"):
            env[key] = _stringify(value)
            continue
        env_key = supported.get(key)
        if not env_key:
            supported_keys = sorted([*supported, "QUANTBOY_RQ_*"])
            raise ValueError(
                f"unsupported strategy parameter {strategy}.{key}; "
                f"supported: {supported_keys}"
            )
        env[env_key] = _stringify(value)
    return env


def parse_codes_file(path: Path) -> str:
    codes = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            first_column = line.split(",", 1)[0].strip()
            if line_number == 1 and first_column.lower() in {"code", "order_book_id"}:
                continue
            if "." in first_column:
                first_column = first_column.split(".", 1)[0]
            if first_column:
                codes.append(first_column)
    if not codes:
        raise ValueError(f"codes file is empty: {path}")
    return ",".join(dict.fromkeys(codes))


def resolve_codes(batch: BatchRun) -> str:
    if batch.codes_file:
        return parse_codes_file(Path(batch.codes_file))
    if batch.codes:
        return _csv_codes(batch.codes, f"runs.{batch.name}.codes")
    return DEFAULT_CODES


def build_batch_runs(args: argparse.Namespace) -> List[BatchRun]:
    config_runs = args.config_runs
    if config_runs:
        if not isinstance(config_runs, list):
            raise ValueError("runs must be a YAML list")
        runs = []
        for index, item in enumerate(config_runs, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"runs[{index}] must be a YAML object")
            name = _string_or_none(item.get("name")) or f"run_{index}"
            runs.append(
                BatchRun(
                    name=name,
                    codes=item.get("codes", args.codes),
                    codes_file=_string_or_none(item.get("codes_file", args.codes_file)),
                    output_dir=_string_or_none(item.get("output_dir", args.output_dir)),
                )
            )
        return runs

    return [
        BatchRun(
            name="default",
            codes=args.codes,
            codes_file=args.codes_file,
            output_dir=args.output_dir,
        )
    ]


def make_output_dir(
    args: argparse.Namespace,
    batch: BatchRun,
    rebalances: List[str],
    multi_batch: bool,
) -> Path:
    if batch.output_dir:
        output_dir = Path(batch.output_dir)
    else:
        suffix = "" if rebalances == [args.rebalance] else f"_{'_'.join(rebalances)}"
        batch_suffix = "" if not multi_batch else f"_{batch.name}"
        output_dir = Path("outputs/backtests") / f"{args.start}_{args.end}{batch_suffix}{suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def build_env(
    args: argparse.Namespace,
    spec: StrategySpec,
    rebalance: str,
    codes: str,
) -> Dict[str, str]:
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = "strategy" if not current_pythonpath else f"strategy:{current_pythonpath}"
    env.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    env.update(
        {
            "QUANTBOY_RQ_STRATEGY": spec.name,
            "QUANTBOY_RQ_CODES": codes,
            "QUANTBOY_RQ_REBALANCE": rebalance,
            "QUANTBOY_RQ_HISTORY_BARS": str(args.history_bars),
            "QUANTBOY_RQ_MAX_TOTAL_WEIGHT": str(args.max_total_weight),
            "QUANTBOY_RQ_USE_PRE_START_HISTORY": (
                "1" if args.use_pre_start_history else "0"
            ),
            "QUANTBOY_RQ_MIN_AVG_TURNOVER": str(args.min_avg_turnover),
            "QUANTBOY_RQ_LIQUIDITY_LOOKBACK": str(args.liquidity_lookback),
            "QUANTBOY_RQ_AVOID_LIMIT_TRADES": (
                "1" if args.avoid_limit_trades else "0"
            ),
            "QUANTBOY_RQ_EXCLUDE_BUY_BOARDS": ",".join(args.exclude_buy_boards),
            "QUANTBOY_RQ_BUNDLE": args.bundle,
            "QUANTBOY_RQ_FAST_HISTORY_CACHE": "1",
            "QUANTBOY_RQ_HISTORY_CACHE_WORKERS": str(args.history_cache_workers),
        }
    )
    env.update(spec.env)
    strategy_parameters = args.strategy_parameters.get(spec.name, {})
    if strategy_parameters:
        if not isinstance(strategy_parameters, dict):
            raise ValueError(f"strategy_parameters.{spec.name} must be a YAML object")
        env.update(parse_strategy_parameter_env(spec.name, strategy_parameters))
    return env


def run_strategy(
    args: argparse.Namespace,
    spec: StrategySpec,
    rebalance: str,
    codes: str,
    output_path: Path,
) -> None:
    cmd = [
        args.rqalpha_bin,
        "run",
        "-d",
        args.bundle,
        "-f",
        "scripts/rqalpha_target_weight_demo.py",
        "-s",
        args.start,
        "-e",
        args.end,
        "-a",
        "stock",
        str(args.cash),
        "-bm",
        args.benchmark,
        "-sp",
        str(args.slippage),
        "--stock-t1",
        "-o",
        str(output_path),
        "-l",
        args.log_level,
    ]
    result = subprocess.run(
        cmd,
        cwd=Path(__file__).resolve().parents[1],
        env=build_env(args, spec, rebalance, codes),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        raise RuntimeError(f"RQAlpha failed for {rebalance}/{spec.name}")


def load_summary(
    universe: str,
    strategy: str,
    rebalance: str,
    output_path: Path,
) -> Dict[str, object]:
    with output_path.open("rb") as file:
        result = pickle.load(file)

    summary = result["summary"]
    portfolio = result.get("portfolio")
    trades = result.get("trades")
    final_value = None
    if portfolio is not None and not portfolio.empty:
        final_value = float(portfolio["total_value"].iloc[-1])

    return {
        "universe": universe,
        "strategy": strategy,
        "rebalance": rebalance,
        "start_date": summary.get("start_date"),
        "end_date": summary.get("end_date"),
        "total_returns": summary.get("total_returns"),
        "annualized_returns": summary.get("annualized_returns"),
        "benchmark_total_returns": summary.get("benchmark_total_returns"),
        "benchmark_annualized_returns": summary.get("benchmark_annualized_returns"),
        "alpha": summary.get("alpha"),
        "beta": summary.get("beta"),
        "sharpe": summary.get("sharpe"),
        "sortino": summary.get("sortino"),
        "volatility": summary.get("volatility"),
        "max_drawdown": summary.get("max_drawdown"),
        "information_ratio": summary.get("information_ratio"),
        "trades": 0 if trades is None else len(trades),
        "final_value": final_value,
        "result_path": str(output_path),
    }


def print_summary(df: pd.DataFrame) -> None:
    columns = [
        "strategy",
        "rebalance",
        "total_returns",
        "annualized_returns",
        "max_drawdown",
        "sharpe",
        "trades",
        "final_value",
    ]
    if "universe" in df.columns and df["universe"].nunique() > 1:
        columns.insert(0, "universe")
    display = df[columns].copy()
    for column in ["total_returns", "annualized_returns", "max_drawdown"]:
        display[column] = display[column].map(lambda value: f"{value:.2%}")
    display["sharpe"] = display["sharpe"].map(lambda value: f"{value:.2f}")
    display["final_value"] = display["final_value"].map(lambda value: f"{value:,.2f}")
    print()
    print(display.to_string(index=False))


def run_batch(
    args: argparse.Namespace,
    batch: BatchRun,
    strategies: List[str],
    rebalances: List[str],
    output_dir: Path,
) -> pd.DataFrame:
    codes = resolve_codes(batch)
    multi_rebalance = len(rebalances) > 1
    tasks = []
    for rebalance in rebalances:
        for strategy in strategies:
            spec = STRATEGY_SPECS[strategy]
            filename = f"{rebalance}_{strategy}.pkl" if multi_rebalance else f"{strategy}.pkl"
            output_path = output_dir / filename
            tasks.append((strategy, spec, rebalance, output_path))

    rows = []
    if args.jobs == 1:
        for strategy, spec, rebalance, output_path in tasks:
            print(f"RUN {batch.name}/{rebalance}/{strategy}", flush=True)
            run_strategy(args, spec, rebalance, codes, output_path)
            rows.append(load_summary(batch.name, strategy, rebalance, output_path))
            print(f"OK  {batch.name}/{rebalance}/{strategy} -> {output_path}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = {}
            for strategy, spec, rebalance, output_path in tasks:
                print(f"RUN {batch.name}/{rebalance}/{strategy}", flush=True)
                future = executor.submit(
                    run_strategy,
                    args,
                    spec,
                    rebalance,
                    codes,
                    output_path,
                )
                futures[future] = (strategy, rebalance, output_path)

            for future in as_completed(futures):
                strategy, rebalance, output_path = futures[future]
                future.result()
                rows.append(load_summary(batch.name, strategy, rebalance, output_path))
                print(f"OK  {batch.name}/{rebalance}/{strategy} -> {output_path}", flush=True)

    df = pd.DataFrame(rows).sort_values("total_returns", ascending=False)
    summary_path = output_dir / "summary.csv"
    df.to_csv(summary_path, index=False)
    print_summary(df)
    print()
    print(f"summary: {summary_path}")
    return df


def main() -> None:
    raw_args = parse_args()
    config = {} if raw_args.no_config else load_config(raw_args.config)
    args = apply_config(raw_args, config)
    if args.jobs <= 0:
        raise ValueError("--jobs must be positive")
    strategies = parse_strategies(args.strategies)
    rebalances = parse_rebalances(args.rebalances, args.rebalance)
    batches = build_batch_runs(args)
    multi_batch = len(batches) > 1

    all_rows = []
    for batch in batches:
        output_dir = make_output_dir(args, batch, rebalances, multi_batch)
        df = run_batch(args, batch, strategies, rebalances, output_dir)
        all_rows.append(df)

    if len(all_rows) > 1:
        combined = pd.concat(all_rows, ignore_index=True).sort_values(
            "total_returns",
            ascending=False,
        )
        combined_path = Path("outputs/backtests") / f"{args.start}_{args.end}_summary.csv"
        combined_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(combined_path, index=False)
        print()
        print("combined summary:")
        print_summary(combined)
        print()
        print(f"combined summary: {combined_path}")


if __name__ == "__main__":
    main()
