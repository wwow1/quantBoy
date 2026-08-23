from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


FACTOR_WEIGHTS = {
    "risk_adjusted_momentum": 0.35,
    "medium_momentum": 0.15,
    "acceleration": 0.15,
    "trend_strength": 0.15,
    "breakout_position": 0.10,
    "drawdown": 0.05,
    "liquidity": 0.05,
}

FACTOR_PROFILES = {
    "risk_adjusted": {
        "risk_adjusted_momentum": 1.0,
    },
    "balanced": FACTOR_WEIGHTS,
    "trend_quality": {
        "risk_adjusted_momentum": 0.65,
        "acceleration": 0.20,
        "trend_strength": 0.10,
        "drawdown": 0.05,
    },
}


@dataclass(frozen=True)
class BundleMultiFactorConfig:
    long_lookback: int = 220
    medium_lookback: int = 60
    short_lookback: int = 20
    volatility_lookback: int = 50
    drawdown_lookback: int = 120
    breakout_lookback: int = 120
    liquidity_lookback: int = 20
    top_k: int = 2
    min_long_momentum: float = 0.0
    min_trend_strength: float = 0.0
    factor_profile: str = "trend_quality"
    weight_mode: str = "equal"

    def __post_init__(self) -> None:
        for field_name in (
            "long_lookback",
            "medium_lookback",
            "short_lookback",
            "volatility_lookback",
            "drawdown_lookback",
            "breakout_lookback",
            "liquidity_lookback",
            "top_k",
        ):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.factor_profile not in FACTOR_PROFILES:
            available = ", ".join(sorted(FACTOR_PROFILES))
            raise ValueError(f"factor_profile must be one of: {available}")
        if self.weight_mode not in {"equal", "inverse_volatility"}:
            raise ValueError("weight_mode must be equal or inverse_volatility")

    @property
    def min_bars(self) -> int:
        return max(
            self.long_lookback + 1,
            self.medium_lookback + 1,
            self.short_lookback + 1,
            self.volatility_lookback + 1,
            self.drawdown_lookback,
            self.breakout_lookback,
            self.liquidity_lookback,
        )

    @property
    def factor_weights(self) -> Dict[str, float]:
        return FACTOR_PROFILES[self.factor_profile]


@dataclass(frozen=True)
class FactorSnapshot:
    code: str
    risk_adjusted_momentum: float
    medium_momentum: float
    acceleration: float
    trend_strength: float
    breakout_position: float
    drawdown: float
    liquidity: float
    volatility: float


def _series(
    history: Dict[str, pd.DataFrame],
    code: str,
    field: str,
) -> Optional[pd.Series]:
    values = history.get(code, pd.DataFrame()).get(field)
    if values is None:
        return None
    values = values.dropna()
    if values.empty:
        return None
    return values


def _momentum(close: pd.Series, lookback: int) -> Optional[float]:
    if len(close) < lookback + 1:
        return None
    value = close.iloc[-1] / close.iloc[-lookback - 1] - 1
    return float(value) if pd.notna(value) else None


def _returns(close: pd.Series, lookback: int) -> Optional[pd.Series]:
    if len(close) < lookback + 1:
        return None
    values = close.pct_change().dropna().iloc[-lookback:]
    if values.empty:
        return None
    return values


def _max_drawdown(close: pd.Series, lookback: int) -> Optional[float]:
    if len(close) < lookback:
        return None
    window = close.iloc[-lookback:]
    drawdown = window / window.cummax() - 1
    value = abs(drawdown.min())
    return float(value) if pd.notna(value) else None


def _rank_percentiles(
    snapshots: Dict[str, FactorSnapshot],
    field_name: str,
    *,
    higher_is_better: bool = True,
) -> Dict[str, float]:
    values = {
        code: getattr(snapshot, field_name)
        for code, snapshot in snapshots.items()
        if np.isfinite(getattr(snapshot, field_name))
    }
    if not values:
        return {}
    series = pd.Series(values, dtype=float)
    ranked = series.rank(pct=True, ascending=higher_is_better)
    return {code: float(value) for code, value in ranked.items()}


def _factor_snapshot(
    code: str,
    history: Dict[str, pd.DataFrame],
    config: BundleMultiFactorConfig,
) -> Optional[FactorSnapshot]:
    close = _series(history, code, "close")
    high = _series(history, code, "high")
    low = _series(history, code, "low")
    turnover = _series(history, code, "total_turnover")
    if turnover is None:
        turnover = _series(history, code, "amount")
    if close is None or len(close) < config.min_bars:
        return None

    long_momentum = _momentum(close, config.long_lookback)
    medium_momentum = _momentum(close, config.medium_lookback)
    short_momentum = _momentum(close, config.short_lookback)
    returns = _returns(close, config.volatility_lookback)
    drawdown = _max_drawdown(close, config.drawdown_lookback)
    if (
        long_momentum is None
        or medium_momentum is None
        or short_momentum is None
        or returns is None
        or drawdown is None
    ):
        return None

    volatility = returns.std()
    if pd.isna(volatility) or volatility <= 0:
        return None

    trend_strength = close.iloc[-1] / close.iloc[-config.long_lookback:].mean() - 1
    if (
        long_momentum <= config.min_long_momentum
        or trend_strength <= config.min_trend_strength
    ):
        return None

    price_high = close if high is None else high
    price_low = close if low is None else low
    recent_high = price_high.iloc[-config.breakout_lookback:].max()
    recent_low = price_low.iloc[-config.breakout_lookback:].min()
    if pd.isna(recent_high) or pd.isna(recent_low) or recent_high <= recent_low:
        return None
    breakout_position = (close.iloc[-1] - recent_low) / (recent_high - recent_low)

    avg_turnover = 0.0
    if turnover is not None and len(turnover) >= config.liquidity_lookback:
        avg_turnover = turnover.iloc[-config.liquidity_lookback:].mean()
        if pd.isna(avg_turnover) or avg_turnover <= 0:
            avg_turnover = 0.0

    return FactorSnapshot(
        code=code,
        risk_adjusted_momentum=float(long_momentum / volatility),
        medium_momentum=float(medium_momentum),
        acceleration=float(short_momentum - medium_momentum),
        trend_strength=float(trend_strength),
        breakout_position=float(breakout_position),
        drawdown=float(drawdown),
        liquidity=float(np.log1p(avg_turnover)),
        volatility=float(volatility),
    )


def _composite_scores(
    snapshots: Dict[str, FactorSnapshot],
    factor_weights: Dict[str, float],
) -> Dict[str, float]:
    ranks = {
        "risk_adjusted_momentum": _rank_percentiles(snapshots, "risk_adjusted_momentum"),
        "medium_momentum": _rank_percentiles(snapshots, "medium_momentum"),
        "acceleration": _rank_percentiles(snapshots, "acceleration"),
        "trend_strength": _rank_percentiles(snapshots, "trend_strength"),
        "breakout_position": _rank_percentiles(snapshots, "breakout_position"),
        "drawdown": _rank_percentiles(snapshots, "drawdown", higher_is_better=False),
        "liquidity": _rank_percentiles(snapshots, "liquidity"),
    }
    return {
        code: sum(
            factor_weights[factor_name] * ranks[factor_name].get(code, 0.0)
            for factor_name in factor_weights
        )
        for code in snapshots
    }


def _selected_weights(
    selected: List[str],
    snapshots: Dict[str, FactorSnapshot],
    weight_mode: str,
) -> Dict[str, float]:
    if weight_mode == "equal":
        weight = 1.0 / len(selected)
        return {code: weight for code in selected}

    inverse_volatility = {
        code: 1.0 / snapshots[code].volatility
        for code in selected
        if snapshots[code].volatility > 0
    }
    total = sum(inverse_volatility.values())
    if total <= 0:
        weight = 1.0 / len(selected)
        return {code: weight for code in selected}
    return {
        code: float(value / total)
        for code, value in inverse_volatility.items()
    }


class BundleMultiFactorMomentumStrategy:
    """Bundle-data multi-factor strategy with fixed interpretable factors."""

    history_fields = ["close"]

    def __init__(
        self,
        long_lookback: int = 220,
        medium_lookback: int = 60,
        short_lookback: int = 20,
        volatility_lookback: int = 50,
        drawdown_lookback: int = 120,
        breakout_lookback: int = 120,
        liquidity_lookback: int = 20,
        top_k: int = 2,
        min_long_momentum: float = 0.0,
        min_trend_strength: float = 0.0,
        factor_profile: str = "trend_quality",
        weight_mode: str = "equal",
    ):
        self.config = BundleMultiFactorConfig(
            long_lookback=long_lookback,
            medium_lookback=medium_lookback,
            short_lookback=short_lookback,
            volatility_lookback=volatility_lookback,
            drawdown_lookback=drawdown_lookback,
            breakout_lookback=breakout_lookback,
            liquidity_lookback=liquidity_lookback,
            top_k=top_k,
            min_long_momentum=min_long_momentum,
            min_trend_strength=min_trend_strength,
            factor_profile=factor_profile,
            weight_mode=weight_mode,
        )
        self.name = (
            f"{long_lookback}/{medium_lookback}/{short_lookback}日"
            f"bundle多因子{factor_profile}Top{top_k}"
        )

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        snapshots = {
            code: snapshot
            for code in tradable_codes
            if (snapshot := _factor_snapshot(code, history, self.config)) is not None
        }
        if not snapshots:
            return {}

        scores = _composite_scores(snapshots, self.config.factor_weights)
        selected = [
            code
            for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.config.top_k]
        if not selected:
            return {}
        return _selected_weights(selected, snapshots, self.config.weight_mode)


class StatefulBundleMultiFactorMomentumStrategy:
    """Stateful wrapper around bundle multi-factor ranking with daily exits."""

    history_fields = ["close"]

    def __init__(
        self,
        long_lookback: int = 220,
        medium_lookback: int = 60,
        short_lookback: int = 20,
        volatility_lookback: int = 50,
        drawdown_lookback: int = 120,
        breakout_lookback: int = 120,
        liquidity_lookback: int = 20,
        top_k: int = 1,
        min_long_momentum: float = 0.0,
        min_trend_strength: float = 0.0,
        factor_profile: str = "trend_quality",
        trailing_drawdown: float = 0.08,
        ma_exit_window: int = 20,
        cooldown_weeks: int = 1,
        allow_switch: bool = True,
    ):
        if trailing_drawdown < 0:
            raise ValueError("trailing_drawdown must be non-negative")
        if ma_exit_window <= 0:
            raise ValueError("ma_exit_window must be positive")
        if cooldown_weeks < 0:
            raise ValueError("cooldown_weeks must be non-negative")
        self.config = BundleMultiFactorConfig(
            long_lookback=long_lookback,
            medium_lookback=medium_lookback,
            short_lookback=short_lookback,
            volatility_lookback=volatility_lookback,
            drawdown_lookback=drawdown_lookback,
            breakout_lookback=breakout_lookback,
            liquidity_lookback=liquidity_lookback,
            top_k=top_k,
            min_long_momentum=min_long_momentum,
            min_trend_strength=min_trend_strength,
            factor_profile=factor_profile,
            weight_mode="equal",
        )
        self.trailing_drawdown = trailing_drawdown
        self.ma_exit_window = ma_exit_window
        self.cooldown_weeks = cooldown_weeks
        self.allow_switch = allow_switch
        self.holding_code: Optional[str] = None
        self.entry_price: Optional[float] = None
        self.high_price: Optional[float] = None
        self.last_week_key: Optional[str] = None
        self.cooldown_remaining = 0
        self.name = (
            f"{long_lookback}/{medium_lookback}/{short_lookback}日"
            f"状态机bundle多因子{factor_profile}"
        )

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        self._update_exit_state(history)
        week_key = self._week_key(date)
        if week_key != self.last_week_key:
            self.last_week_key = week_key
            if self.cooldown_remaining > 0:
                self.cooldown_remaining -= 1
                return self._current_target()
            if self.holding_code is None or self.allow_switch:
                selected = self._select(history, tradable_codes)
                if selected and selected[0] != self.holding_code:
                    self._enter(selected[0], history)
        return self._current_target()

    def _select(
        self,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> List[str]:
        snapshots = {
            code: snapshot
            for code in tradable_codes
            if (snapshot := _factor_snapshot(code, history, self.config)) is not None
        }
        if not snapshots:
            return []
        scores = _composite_scores(snapshots, self.config.factor_weights)
        return [
            code
            for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.config.top_k]

    def _update_exit_state(self, history: Dict[str, pd.DataFrame]) -> None:
        if self.holding_code is None:
            return
        close = _series(history, self.holding_code, "close")
        if close is None or close.empty:
            return
        latest = float(close.iloc[-1])
        if self.entry_price is None:
            self.entry_price = latest
        self.high_price = latest if self.high_price is None else max(self.high_price, latest)

        exit_now = False
        if self.high_price and latest / self.high_price - 1 <= -self.trailing_drawdown:
            exit_now = True
        if len(close) >= self.ma_exit_window:
            moving_average = close.iloc[-self.ma_exit_window:].mean()
            if pd.notna(moving_average) and latest < moving_average:
                exit_now = True

        if exit_now:
            self.holding_code = None
            self.entry_price = None
            self.high_price = None
            self.cooldown_remaining = self.cooldown_weeks

    def _enter(self, code: str, history: Dict[str, pd.DataFrame]) -> None:
        close = _series(history, code, "close")
        if close is None or close.empty:
            return
        latest = float(close.iloc[-1])
        self.holding_code = code
        self.entry_price = latest
        self.high_price = latest

    def _current_target(self) -> Dict[str, float]:
        if self.holding_code is None:
            return {}
        return {self.holding_code: 1.0}

    @staticmethod
    def _week_key(date: pd.Timestamp) -> str:
        year, week, _ = date.isocalendar()
        return f"{year}-W{week:02d}"
