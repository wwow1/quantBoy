#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run QuantBoy target-weight strategies inside RQAlpha.

Examples:
    QUANTBOY_RQ_STRATEGY=equal_weight \
    QUANTBOY_RQ_REBALANCE=daily \
    PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib .venv/bin/rqalpha run \
      -d data/rqalpha_bundle/bundle \
      -f scripts/rqalpha_target_weight_demo.py \
      -s 2020-11-16 \
      -e 2026-03-20 \
      -a stock 100000 \
      -bm 000300.XSHG \
      -sp 0.001 \
      --stock-t1 \
      --report /tmp/rqalpha_target_weight_equal_weight \
      -o /tmp/rqalpha_target_weight_equal_weight.pkl \
      -l error
"""

import os
from pathlib import Path

from quantboy import RQAlphaAdapterConfig, RQAlphaTargetWeightAdapter
from strategies import (
    AbsoluteMomentumStrategy,
    AcceleratingMomentumStrategy,
    BreakoutMomentumStrategy,
    BundleMultiFactorMomentumStrategy,
    CalendarFilteredStatefulAcceleratingEnsembleStrategy,
    CompositeMomentumStrategy,
    DateWindowFilteredStatefulAcceleratingEnsembleStrategy,
    DrawdownAdjustedMomentumStrategy,
    DrawdownControlStrategy,
    DualMovingAverageStrategy,
    DualMomentumStrategy,
    EqualWeightStrategy,
    LowVolatilityStrategy,
    LowVolatilityTrendStrategy,
    MaxSharpeStrategy,
    MeanReversionStrategy,
    MinVarianceStrategy,
    MomentumRiskParityStrategy,
    MomentumRotationStrategy,
    MovingAverageTrendStrategy,
    MarketTrendFilterStrategy,
    RiskAdjustedMomentumStrategy,
    RiskParityStrategy,
    ScheduledRotationStrategy,
    SentimentBiasStrategy,
    SmoothedMomentumStrategy,
    StatefulBundleMultiFactorMomentumStrategy,
    StatefulAcceleratingEnsembleStrategy,
    StatefulAcceleratingMomentumStrategy,
    TrailingSharpeMomentumStrategy,
    TrendFilteredMomentumStrategy,
    TrendRiskParityStrategy,
    TrendTimingStrategy,
    VolatilityTargetStrategy,
    WeightedStrategyEnsemble,
)


DEFAULT_CODES = ["510300", "510500", "159915", "510050", "588000"]


def _parse_codes() -> list[str]:
    raw = os.environ.get("QUANTBOY_RQ_CODES")
    if not raw:
        return DEFAULT_CODES
    return [code.strip() for code in raw.split(",") if code.strip()]


def _parse_csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_date_ranges(name: str) -> list[tuple[str, str]]:
    raw = os.environ.get(name, "")
    ranges = []
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        start, end = item.split(":", 1)
        ranges.append((start.strip(), end.strip()))
    return ranges


def _parse_schedule(name: str) -> list[tuple[str, str, str, float]]:
    raw = os.environ.get(name, "")
    schedule = []
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = [part.strip() for part in item.split(":")]
        if len(parts) == 3:
            start, end, code = parts
            weight = 1.0
        elif len(parts) == 4:
            start, end, code, raw_weight = parts
            weight = float(raw_weight)
        else:
            raise ValueError(
                "QUANTBOY_RQ_SCHEDULE items must be start:end:code[:weight]"
            )
        schedule.append((start, end, code, weight))
    return schedule


def _build_strategy():
    strategy_name = os.environ.get("QUANTBOY_RQ_STRATEGY", "equal_weight")
    strategy = _build_base_strategy(strategy_name)
    if os.environ.get("QUANTBOY_RQ_MARKET_FILTER", "0") == "1":
        raw_min_momentum = os.environ.get("QUANTBOY_RQ_MARKET_MIN_MOMENTUM", "")
        min_momentum = None if raw_min_momentum == "" else float(raw_min_momentum)
        strategy = MarketTrendFilterStrategy(
            strategy,
            reference_code=os.environ.get("QUANTBOY_RQ_MARKET_FILTER_CODE", "510300"),
            trend_window=int(os.environ.get("QUANTBOY_RQ_MARKET_TREND_WINDOW", "120")),
            min_momentum=min_momentum,
        )
    if os.environ.get("QUANTBOY_RQ_SENTIMENT_BIAS", "0") == "1":
        strategy = SentimentBiasStrategy(
            strategy,
            db_path=os.environ.get(
                "QUANTBOY_RQ_SENTIMENT_DB",
                str(Path(__file__).resolve().parents[1] / "data" / "event_factors.db"),
            ),
            max_tilt=float(os.environ.get("QUANTBOY_RQ_SENTIMENT_TILT", "0.15")),
            max_age_weeks=int(os.environ.get("QUANTBOY_RQ_SENTIMENT_MAX_AGE_WEEKS", "4")),
        )
    return strategy


def _build_base_strategy(strategy_name: str):
    if strategy_name == "equal_weight":
        return EqualWeightStrategy()
    if strategy_name == "momentum":
        lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "120"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "1"))
        return MomentumRotationStrategy(lookback=lookback, top_k=top_k)
    if strategy_name == "ma_trend":
        window = int(os.environ.get("QUANTBOY_RQ_MA_WINDOW", "120"))
        return MovingAverageTrendStrategy(window=window)
    if strategy_name == "dual_ma":
        short_window = int(os.environ.get("QUANTBOY_RQ_SHORT_WINDOW", "20"))
        long_window = int(os.environ.get("QUANTBOY_RQ_LONG_WINDOW", "120"))
        return DualMovingAverageStrategy(
            short_window=short_window,
            long_window=long_window,
        )
    if strategy_name == "mean_reversion":
        lookback = int(os.environ.get("QUANTBOY_RQ_MEAN_REVERSION_LOOKBACK", "20"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MEAN_REVERSION_TOP_K", "1"))
        trend_window = int(os.environ.get("QUANTBOY_RQ_TREND_WINDOW", "120"))
        return MeanReversionStrategy(
            lookback=lookback,
            top_k=top_k,
            trend_window=trend_window,
        )
    if strategy_name == "low_volatility":
        lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "60"))
        top_k = int(os.environ.get("QUANTBOY_RQ_LOW_VOLATILITY_TOP_K", "3"))
        return LowVolatilityStrategy(lookback=lookback, top_k=top_k)
    if strategy_name == "risk_parity":
        lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "60"))
        return RiskParityStrategy(lookback=lookback)
    if strategy_name == "trend_timing":
        window = int(os.environ.get("QUANTBOY_RQ_TREND_WINDOW", "200"))
        return TrendTimingStrategy(window=window)
    if strategy_name == "absolute_momentum":
        lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "120"))
        min_return = float(os.environ.get("QUANTBOY_RQ_MIN_RETURN", "0"))
        return AbsoluteMomentumStrategy(lookback=lookback, min_return=min_return)
    if strategy_name == "dual_momentum":
        lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "120"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "1"))
        min_return = float(os.environ.get("QUANTBOY_RQ_MIN_RETURN", "0"))
        return DualMomentumStrategy(
            lookback=lookback,
            top_k=top_k,
            min_return=min_return,
        )
    if strategy_name == "volatility_target":
        lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "60"))
        target_volatility = float(os.environ.get("QUANTBOY_RQ_TARGET_VOLATILITY", "0.10"))
        max_leverage = float(os.environ.get("QUANTBOY_RQ_MAX_LEVERAGE", "1.0"))
        return VolatilityTargetStrategy(
            lookback=lookback,
            target_volatility=target_volatility,
            max_leverage=max_leverage,
        )
    if strategy_name == "drawdown_control":
        lookback = int(os.environ.get("QUANTBOY_RQ_DRAWDOWN_LOOKBACK", "120"))
        max_drawdown = float(os.environ.get("QUANTBOY_RQ_MAX_DRAWDOWN", "0.08"))
        return DrawdownControlStrategy(lookback=lookback, max_drawdown=max_drawdown)
    if strategy_name == "trend_risk_parity":
        lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "60"))
        trend_window = int(os.environ.get("QUANTBOY_RQ_TREND_WINDOW", "120"))
        return TrendRiskParityStrategy(lookback=lookback, trend_window=trend_window)
    if strategy_name == "min_variance":
        lookback = int(os.environ.get("QUANTBOY_RQ_COVARIANCE_LOOKBACK", "120"))
        return MinVarianceStrategy(lookback=lookback)
    if strategy_name == "max_sharpe":
        lookback = int(os.environ.get("QUANTBOY_RQ_COVARIANCE_LOOKBACK", "120"))
        return MaxSharpeStrategy(lookback=lookback)
    if strategy_name == "low_volatility_trend":
        lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "60"))
        top_k = int(os.environ.get("QUANTBOY_RQ_LOW_VOLATILITY_TOP_K", "3"))
        trend_window = int(os.environ.get("QUANTBOY_RQ_TREND_WINDOW", "120"))
        return LowVolatilityTrendStrategy(
            lookback=lookback,
            top_k=top_k,
            trend_window=trend_window,
        )
    if strategy_name == "sector_rotation":
        lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "120"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "1"))
        return MomentumRotationStrategy(lookback=lookback, top_k=top_k)
    if strategy_name == "risk_adjusted_momentum":
        momentum_lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "120"))
        volatility_lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "60"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "3"))
        return RiskAdjustedMomentumStrategy(
            momentum_lookback=momentum_lookback,
            volatility_lookback=volatility_lookback,
            top_k=top_k,
        )
    if strategy_name == "trend_filtered_momentum":
        lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "120"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "3"))
        trend_window = int(os.environ.get("QUANTBOY_RQ_TREND_WINDOW", "120"))
        return TrendFilteredMomentumStrategy(
            lookback=lookback,
            top_k=top_k,
            trend_window=trend_window,
        )
    if strategy_name == "momentum_risk_parity":
        momentum_lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "120"))
        volatility_lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "60"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "5"))
        return MomentumRiskParityStrategy(
            momentum_lookback=momentum_lookback,
            volatility_lookback=volatility_lookback,
            top_k=top_k,
        )
    if strategy_name == "composite_momentum":
        short_lookback = int(os.environ.get("QUANTBOY_RQ_SHORT_LOOKBACK", "20"))
        medium_lookback = int(os.environ.get("QUANTBOY_RQ_MEDIUM_LOOKBACK", "60"))
        long_lookback = int(os.environ.get("QUANTBOY_RQ_LONG_LOOKBACK", "120"))
        volatility_lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "60"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "3"))
        return CompositeMomentumStrategy(
            short_lookback=short_lookback,
            medium_lookback=medium_lookback,
            long_lookback=long_lookback,
            volatility_lookback=volatility_lookback,
            top_k=top_k,
        )
    if strategy_name == "breakout_momentum":
        breakout_window = int(os.environ.get("QUANTBOY_RQ_BREAKOUT_WINDOW", "120"))
        momentum_lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "60"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "3"))
        return BreakoutMomentumStrategy(
            breakout_window=breakout_window,
            momentum_lookback=momentum_lookback,
            top_k=top_k,
        )
    if strategy_name == "drawdown_adjusted_momentum":
        momentum_lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "220"))
        volatility_lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "50"))
        drawdown_lookback = int(os.environ.get("QUANTBOY_RQ_DRAWDOWN_LOOKBACK", "120"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "2"))
        drawdown_penalty = float(os.environ.get("QUANTBOY_RQ_DRAWDOWN_PENALTY", "2.0"))
        return DrawdownAdjustedMomentumStrategy(
            momentum_lookback=momentum_lookback,
            volatility_lookback=volatility_lookback,
            drawdown_lookback=drawdown_lookback,
            top_k=top_k,
            drawdown_penalty=drawdown_penalty,
        )
    if strategy_name == "trailing_sharpe_momentum":
        lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "120"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "2"))
        min_return = float(os.environ.get("QUANTBOY_RQ_MIN_RETURN", "0"))
        return TrailingSharpeMomentumStrategy(
            lookback=lookback,
            top_k=top_k,
            min_return=min_return,
        )
    if strategy_name == "accelerating_momentum":
        short_lookback = int(os.environ.get("QUANTBOY_RQ_SHORT_LOOKBACK", "20"))
        long_lookback = int(os.environ.get("QUANTBOY_RQ_LONG_LOOKBACK", "220"))
        volatility_lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "50"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "2"))
        short_weight = float(os.environ.get("QUANTBOY_RQ_SHORT_WEIGHT", "1.0"))
        return AcceleratingMomentumStrategy(
            short_lookback=short_lookback,
            long_lookback=long_lookback,
            volatility_lookback=volatility_lookback,
            top_k=top_k,
            short_weight=short_weight,
        )
    if strategy_name == "stateful_accelerating_momentum":
        short_lookback = int(os.environ.get("QUANTBOY_RQ_SHORT_LOOKBACK", "10"))
        long_lookback = int(os.environ.get("QUANTBOY_RQ_LONG_LOOKBACK", "200"))
        volatility_lookback = int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "80"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "1"))
        short_weight = float(os.environ.get("QUANTBOY_RQ_SHORT_WEIGHT", "1.5"))
        trailing_drawdown = float(os.environ.get("QUANTBOY_RQ_TRAILING_DRAWDOWN", "0.08"))
        raw_take_profit = os.environ.get("QUANTBOY_RQ_TAKE_PROFIT", "")
        take_profit = None if raw_take_profit == "" else float(raw_take_profit)
        ma_exit_window = int(os.environ.get("QUANTBOY_RQ_MA_EXIT_WINDOW", "20"))
        cooldown_weeks = int(os.environ.get("QUANTBOY_RQ_COOLDOWN_WEEKS", "1"))
        allow_switch = os.environ.get("QUANTBOY_RQ_ALLOW_SWITCH", "1") != "0"
        raw_min_score = os.environ.get("QUANTBOY_RQ_MIN_SCORE", "")
        min_score = None if raw_min_score == "" else float(raw_min_score)
        raw_profit_lock_trigger = os.environ.get("QUANTBOY_RQ_PROFIT_LOCK_TRIGGER", "")
        raw_profit_lock_drawdown = os.environ.get("QUANTBOY_RQ_PROFIT_LOCK_DRAWDOWN", "")
        profit_lock_trigger = (
            None if raw_profit_lock_trigger == "" else float(raw_profit_lock_trigger)
        )
        profit_lock_drawdown = (
            None if raw_profit_lock_drawdown == "" else float(raw_profit_lock_drawdown)
        )
        return StatefulAcceleratingMomentumStrategy(
            short_lookback=short_lookback,
            long_lookback=long_lookback,
            volatility_lookback=volatility_lookback,
            top_k=top_k,
            short_weight=short_weight,
            trailing_drawdown=trailing_drawdown,
            take_profit=take_profit,
            ma_exit_window=ma_exit_window,
            cooldown_weeks=cooldown_weeks,
            allow_switch=allow_switch,
            min_score=min_score,
            profit_lock_trigger=profit_lock_trigger,
            profit_lock_drawdown=profit_lock_drawdown,
        )
    if strategy_name == "stateful_accelerating_ensemble":
        raw_take_profit = os.environ.get("QUANTBOY_RQ_TAKE_PROFIT", "")
        take_profit = None if raw_take_profit == "" else float(raw_take_profit)
        return StatefulAcceleratingEnsembleStrategy(take_profit=take_profit)
    if strategy_name == "calendar_filtered_stateful_ensemble":
        raw_take_profit = os.environ.get("QUANTBOY_RQ_TAKE_PROFIT", "0.8")
        take_profit = None if raw_take_profit == "" else float(raw_take_profit)
        active_months = [
            int(item)
            for item in os.environ.get("QUANTBOY_RQ_ACTIVE_MONTHS", "2,4,5,6").split(",")
            if item.strip()
        ]
        return CalendarFilteredStatefulAcceleratingEnsembleStrategy(
            active_months=active_months,
            take_profit=take_profit,
        )
    if strategy_name == "date_window_stateful_ensemble":
        raw_take_profit = os.environ.get("QUANTBOY_RQ_TAKE_PROFIT", "0.8")
        take_profit = None if raw_take_profit == "" else float(raw_take_profit)
        active_ranges = _parse_date_ranges("QUANTBOY_RQ_ACTIVE_RANGES")
        return DateWindowFilteredStatefulAcceleratingEnsembleStrategy(
            active_ranges=active_ranges,
            take_profit=take_profit,
        )
    if strategy_name == "scheduled_rotation":
        return ScheduledRotationStrategy(_parse_schedule("QUANTBOY_RQ_SCHEDULE"))
    if strategy_name == "smoothed_momentum":
        lookback = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_LOOKBACK", "180"))
        top_k = int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "2"))
        return SmoothedMomentumStrategy(lookback=lookback, top_k=top_k)
    if strategy_name == "bundle_multifactor_momentum":
        return BundleMultiFactorMomentumStrategy(
            long_lookback=int(os.environ.get("QUANTBOY_RQ_LONG_LOOKBACK", "220")),
            medium_lookback=int(os.environ.get("QUANTBOY_RQ_MEDIUM_LOOKBACK", "60")),
            short_lookback=int(os.environ.get("QUANTBOY_RQ_SHORT_LOOKBACK", "20")),
            volatility_lookback=int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "50")),
            drawdown_lookback=int(os.environ.get("QUANTBOY_RQ_DRAWDOWN_LOOKBACK", "120")),
            breakout_lookback=int(os.environ.get("QUANTBOY_RQ_BREAKOUT_WINDOW", "120")),
            liquidity_lookback=int(os.environ.get("QUANTBOY_RQ_LIQUIDITY_LOOKBACK", "20")),
            top_k=int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "2")),
            min_long_momentum=float(os.environ.get("QUANTBOY_RQ_MIN_RETURN", "0")),
            min_trend_strength=float(os.environ.get("QUANTBOY_RQ_MIN_TREND_STRENGTH", "0")),
            factor_profile=os.environ.get("QUANTBOY_RQ_FACTOR_PROFILE", "trend_quality"),
            weight_mode=os.environ.get("QUANTBOY_RQ_WEIGHT_MODE", "equal"),
        )
    if strategy_name == "stateful_bundle_multifactor_momentum":
        return StatefulBundleMultiFactorMomentumStrategy(
            long_lookback=int(os.environ.get("QUANTBOY_RQ_LONG_LOOKBACK", "220")),
            medium_lookback=int(os.environ.get("QUANTBOY_RQ_MEDIUM_LOOKBACK", "60")),
            short_lookback=int(os.environ.get("QUANTBOY_RQ_SHORT_LOOKBACK", "20")),
            volatility_lookback=int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "50")),
            drawdown_lookback=int(os.environ.get("QUANTBOY_RQ_DRAWDOWN_LOOKBACK", "120")),
            breakout_lookback=int(os.environ.get("QUANTBOY_RQ_BREAKOUT_WINDOW", "120")),
            liquidity_lookback=int(os.environ.get("QUANTBOY_RQ_LIQUIDITY_LOOKBACK", "20")),
            top_k=int(os.environ.get("QUANTBOY_RQ_MOMENTUM_TOP_K", "1")),
            min_long_momentum=float(os.environ.get("QUANTBOY_RQ_MIN_RETURN", "0")),
            min_trend_strength=float(os.environ.get("QUANTBOY_RQ_MIN_TREND_STRENGTH", "0")),
            factor_profile=os.environ.get("QUANTBOY_RQ_FACTOR_PROFILE", "trend_quality"),
            trailing_drawdown=float(os.environ.get("QUANTBOY_RQ_TRAILING_DRAWDOWN", "0.08")),
            ma_exit_window=int(os.environ.get("QUANTBOY_RQ_MA_EXIT_WINDOW", "20")),
            cooldown_weeks=int(os.environ.get("QUANTBOY_RQ_COOLDOWN_WEEKS", "1")),
            allow_switch=os.environ.get("QUANTBOY_RQ_ALLOW_SWITCH", "1") != "0",
        )
    if strategy_name == "ensemble_stateful_risk_adjusted":
        raw_take_profit = os.environ.get("QUANTBOY_RQ_TAKE_PROFIT", "0.8")
        take_profit = None if raw_take_profit == "" else float(raw_take_profit)
        stateful_weight = float(os.environ.get("QUANTBOY_RQ_STATEFUL_WEIGHT", "0.7"))
        stateful = StatefulAcceleratingMomentumStrategy(
            short_lookback=int(os.environ.get("QUANTBOY_RQ_SHORT_LOOKBACK", "10")),
            long_lookback=int(os.environ.get("QUANTBOY_RQ_LONG_LOOKBACK", "200")),
            volatility_lookback=int(os.environ.get("QUANTBOY_RQ_VOLATILITY_LOOKBACK", "80")),
            top_k=1,
            short_weight=float(os.environ.get("QUANTBOY_RQ_SHORT_WEIGHT", "1.5")),
            trailing_drawdown=float(os.environ.get("QUANTBOY_RQ_TRAILING_DRAWDOWN", "0.08")),
            take_profit=take_profit,
            ma_exit_window=int(os.environ.get("QUANTBOY_RQ_MA_EXIT_WINDOW", "20")),
            cooldown_weeks=int(os.environ.get("QUANTBOY_RQ_COOLDOWN_WEEKS", "1")),
            allow_switch=os.environ.get("QUANTBOY_RQ_ALLOW_SWITCH", "1") != "0",
            profit_lock_trigger=(
                None
                if os.environ.get("QUANTBOY_RQ_PROFIT_LOCK_TRIGGER", "") == ""
                else float(os.environ["QUANTBOY_RQ_PROFIT_LOCK_TRIGGER"])
            ),
            profit_lock_drawdown=(
                None
                if os.environ.get("QUANTBOY_RQ_PROFIT_LOCK_DRAWDOWN", "") == ""
                else float(os.environ["QUANTBOY_RQ_PROFIT_LOCK_DRAWDOWN"])
            ),
        )
        risk_adjusted = RiskAdjustedMomentumStrategy(
            momentum_lookback=int(os.environ.get("QUANTBOY_RQ_RISK_MOMENTUM_LOOKBACK", "220")),
            volatility_lookback=int(os.environ.get("QUANTBOY_RQ_RISK_VOLATILITY_LOOKBACK", "50")),
            top_k=int(os.environ.get("QUANTBOY_RQ_RISK_TOP_K", "2")),
        )
        return WeightedStrategyEnsemble(
            [
                (stateful, stateful_weight),
                (risk_adjusted, 1.0 - stateful_weight),
            ],
            name="stateful accelerating + risk adjusted momentum ensemble",
        )
    raise ValueError(f"unsupported QUANTBOY_RQ_STRATEGY: {strategy_name}")


def init(context):
    history_bars = int(os.environ.get("QUANTBOY_RQ_HISTORY_BARS", "260"))
    max_total_weight = float(os.environ.get("QUANTBOY_RQ_MAX_TOTAL_WEIGHT", "0.99"))
    rebalance = os.environ.get("QUANTBOY_RQ_REBALANCE", "daily")
    use_pre_start_history = os.environ.get("QUANTBOY_RQ_USE_PRE_START_HISTORY", "0") != "0"
    min_avg_turnover = float(os.environ.get("QUANTBOY_RQ_MIN_AVG_TURNOVER", "0"))
    liquidity_lookback = int(os.environ.get("QUANTBOY_RQ_LIQUIDITY_LOOKBACK", "20"))
    avoid_limit_trades = os.environ.get("QUANTBOY_RQ_AVOID_LIMIT_TRADES", "1") != "0"
    exclude_buy_boards = _parse_csv_env("QUANTBOY_RQ_EXCLUDE_BUY_BOARDS")
    fast_history_cache = os.environ.get("QUANTBOY_RQ_FAST_HISTORY_CACHE", "1") != "0"
    history_cache_workers = int(os.environ.get("QUANTBOY_RQ_HISTORY_CACHE_WORKERS", "8"))
    bundle_path = os.environ.get("QUANTBOY_RQ_BUNDLE", "data/rqalpha_bundle/bundle")
    adapter = RQAlphaTargetWeightAdapter(
        _build_strategy(),
        RQAlphaAdapterConfig(
            codes=_parse_codes(),
            history_bars=history_bars,
            rebalance=rebalance,
            max_total_weight=max_total_weight,
            use_pre_start_history=use_pre_start_history,
            min_avg_turnover=min_avg_turnover,
            liquidity_lookback=liquidity_lookback,
            avoid_limit_trades=avoid_limit_trades,
            exclude_buy_boards=exclude_buy_boards,
            bundle_path=bundle_path,
            fast_history_cache=fast_history_cache,
            history_cache_workers=history_cache_workers,
        ),
    )
    adapter.init_context(context)


def handle_bar(context, bar_dict):
    context.quantboy_adapter.handle_bar(context, bar_dict)
