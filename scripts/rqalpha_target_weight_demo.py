#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run QuantBoy target-weight strategies inside RQAlpha.

Examples:
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
"""

import os

from quantboy import RQAlphaAdapterConfig, RQAlphaTargetWeightAdapter
from strategies import EqualWeightStrategy, MomentumRotationStrategy


DEFAULT_CODES = ["510300", "510500", "159915", "510050", "588000"]


def _parse_codes() -> list[str]:
    raw = os.environ.get("QUANTBOY_RQ_CODES")
    if not raw:
        return DEFAULT_CODES
    return [code.strip() for code in raw.split(",") if code.strip()]


def _build_strategy():
    strategy_name = os.environ.get("QUANTBOY_RQ_STRATEGY", "equal_weight")
    if strategy_name == "equal_weight":
        return EqualWeightStrategy()
    if strategy_name == "momentum":
        lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "120"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "1"))
        return MomentumRotationStrategy(lookback=lookback, top_k=top_k)
    raise ValueError(f"unsupported QUANTBOY_RQ_STRATEGY: {strategy_name}")


def init(context):
    history_bars = int(os.environ.get("QUANTBOY_RQ_HISTORY_BARS", "260"))
    max_total_weight = float(os.environ.get("QUANTBOY_RQ_MAX_TOTAL_WEIGHT", "0.99"))
    adapter = RQAlphaTargetWeightAdapter(
        _build_strategy(),
        RQAlphaAdapterConfig(
            codes=_parse_codes(),
            history_bars=history_bars,
            max_total_weight=max_total_weight,
        ),
    )
    adapter.init_context(context)


def handle_bar(context, bar_dict):
    context.quantboy_adapter.handle_bar(context, bar_dict)
