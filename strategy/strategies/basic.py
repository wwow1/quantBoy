from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


def _close_series(history: Dict[str, pd.DataFrame], code: str) -> Optional[pd.Series]:
    close = history.get(code, pd.DataFrame()).get("close")
    if close is None:
        return None
    close = close.dropna()
    if close.empty:
        return None
    return close


def _equal_weights(codes: List[str]) -> Dict[str, float]:
    if not codes:
        return {}
    weight = 1.0 / len(codes)
    return {code: weight for code in codes}


def _require_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _returns(close: pd.Series, lookback: int) -> Optional[pd.Series]:
    if len(close) < lookback + 1:
        return None
    returns = close.pct_change().dropna().iloc[-lookback:]
    if returns.empty:
        return None
    return returns


def _momentum(close: pd.Series, lookback: int) -> Optional[float]:
    if len(close) < lookback + 1:
        return None
    value = close.iloc[-1] / close.iloc[-lookback - 1] - 1
    return float(value) if pd.notna(value) else None


def _max_drawdown(close: pd.Series, lookback: int) -> Optional[float]:
    if len(close) < lookback:
        return None
    window = close.iloc[-lookback:]
    rolling_high = window.cummax()
    drawdown = window / rolling_high - 1
    value = abs(drawdown.min())
    return float(value) if pd.notna(value) else None


def _inverse_volatility_weights(
    history: Dict[str, pd.DataFrame],
    tradable_codes: List[str],
    lookback: int,
    trend_window: Optional[int] = None,
) -> Dict[str, float]:
    inverse_volatility = {}
    min_bars = lookback + 1
    if trend_window is not None:
        min_bars = max(min_bars, trend_window)

    for code in tradable_codes:
        close = _close_series(history, code)
        if close is None or len(close) < min_bars:
            continue
        if trend_window is not None and close.iloc[-1] <= close.iloc[-trend_window:].mean():
            continue
        returns = _returns(close, lookback)
        if returns is None:
            continue
        volatility = returns.std()
        if pd.notna(volatility) and volatility > 0:
            inverse_volatility[code] = 1.0 / volatility

    total = sum(inverse_volatility.values())
    if total <= 0:
        return {}
    return {
        code: score / total
        for code, score in inverse_volatility.items()
    }


def _portfolio_returns(
    history: Dict[str, pd.DataFrame],
    weights: Dict[str, float],
    lookback: int,
) -> Optional[pd.Series]:
    weighted_returns = []
    for code, weight in weights.items():
        close = _close_series(history, code)
        if close is None:
            continue
        returns = _returns(close, lookback)
        if returns is None:
            continue
        weighted_returns.append(returns.rename(code) * weight)

    if not weighted_returns:
        return None
    frame = pd.concat(weighted_returns, axis=1).dropna()
    if frame.empty:
        return None
    return frame.sum(axis=1)


class MovingAverageTrendStrategy:
    """Hold symbols whose latest close is above their moving average."""

    history_fields = ["close"]

    def __init__(self, window: int = 120):
        _require_positive("window", window)
        self.window = window
        self.name = f"{window}日均线趋势"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        selected = []
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < self.window:
                continue
            if close.iloc[-1] > close.iloc[-self.window:].mean():
                selected.append(code)
        return _equal_weights(selected)


class DualMovingAverageStrategy:
    """Hold symbols when short moving average is above long moving average."""

    history_fields = ["close"]

    def __init__(self, short_window: int = 20, long_window: int = 120):
        _require_positive("short_window", short_window)
        _require_positive("long_window", long_window)
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        self.short_window = short_window
        self.long_window = long_window
        self.name = f"{short_window}/{long_window}日双均线"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        selected = []
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < self.long_window:
                continue
            short_ma = close.iloc[-self.short_window:].mean()
            long_ma = close.iloc[-self.long_window:].mean()
            if short_ma > long_ma:
                selected.append(code)
        return _equal_weights(selected)


class MeanReversionStrategy:
    """Buy the weakest recent performers that remain above a long trend line."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 20, top_k: int = 1, trend_window: int = 120):
        _require_positive("lookback", lookback)
        _require_positive("top_k", top_k)
        _require_positive("trend_window", trend_window)
        self.lookback = lookback
        self.top_k = top_k
        self.trend_window = trend_window
        self.name = f"{lookback}日均值回归Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        min_bars = max(self.lookback + 1, self.trend_window)
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < min_bars:
                continue
            if close.iloc[-1] <= close.iloc[-self.trend_window:].mean():
                continue
            scores[code] = close.iloc[-1] / close.iloc[-self.lookback - 1] - 1

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1])
        ][: self.top_k]
        return _equal_weights(selected)


class LowVolatilityStrategy:
    """Hold the symbols with the lowest trailing daily volatility."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 60, top_k: int = 3):
        _require_positive("lookback", lookback)
        _require_positive("top_k", top_k)
        self.lookback = lookback
        self.top_k = top_k
        self.name = f"{lookback}日低波动Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < self.lookback + 1:
                continue
            returns = close.pct_change().dropna().iloc[-self.lookback:]
            volatility = returns.std()
            if pd.notna(volatility) and volatility > 0:
                scores[code] = volatility

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1])
        ][: self.top_k]
        return _equal_weights(selected)


class RiskParityStrategy:
    """Allocate by inverse trailing volatility across all tradable symbols."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 60):
        _require_positive("lookback", lookback)
        self.lookback = lookback
        self.name = f"{lookback}日等风险权重"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        return _inverse_volatility_weights(history, tradable_codes, self.lookback)


class TrendTimingStrategy:
    """Hold symbols only when their latest close is above a long moving average."""

    history_fields = ["close"]

    def __init__(self, window: int = 200):
        _require_positive("window", window)
        self.window = window
        self.name = f"{window}日趋势择时"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        selected = []
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < self.window:
                continue
            if close.iloc[-1] > close.iloc[-self.window:].mean():
                selected.append(code)
        return _equal_weights(selected)


class AbsoluteMomentumStrategy:
    """Hold symbols whose own trailing return is positive."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 120, min_return: float = 0.0):
        _require_positive("lookback", lookback)
        self.lookback = lookback
        self.min_return = min_return
        self.name = f"{lookback}日绝对动量"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        selected = []
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None:
                continue
            score = _momentum(close, self.lookback)
            if score is not None and score > self.min_return:
                selected.append(code)
        return _equal_weights(selected)


class DualMomentumStrategy:
    """Pick the strongest symbols, but only when their own momentum is positive."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 120, top_k: int = 1, min_return: float = 0.0):
        _require_positive("lookback", lookback)
        _require_positive("top_k", top_k)
        self.lookback = lookback
        self.top_k = top_k
        self.min_return = min_return
        self.name = f"{lookback}日双动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None:
                continue
            score = _momentum(close, self.lookback)
            if score is not None and score > self.min_return:
                scores[code] = score

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        return _equal_weights(selected)


class VolatilityTargetStrategy:
    """Scale inverse-volatility weights to a target annualized volatility."""

    history_fields = ["close"]

    def __init__(
        self,
        lookback: int = 60,
        target_volatility: float = 0.10,
        max_leverage: float = 1.0,
    ):
        _require_positive("lookback", lookback)
        if target_volatility <= 0:
            raise ValueError("target_volatility must be positive")
        if max_leverage <= 0:
            raise ValueError("max_leverage must be positive")
        self.lookback = lookback
        self.target_volatility = target_volatility
        self.max_leverage = max_leverage
        self.name = f"{lookback}日目标波动"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        weights = _inverse_volatility_weights(history, tradable_codes, self.lookback)
        portfolio_returns = _portfolio_returns(history, weights, self.lookback)
        if portfolio_returns is None:
            return {}
        annual_volatility = portfolio_returns.std() * np.sqrt(252)
        if pd.isna(annual_volatility) or annual_volatility <= 0:
            return weights
        scale = min(self.max_leverage, self.target_volatility / annual_volatility)
        return {code: weight * scale for code, weight in weights.items()}


class DrawdownControlStrategy:
    """Hold equal weights unless the recent equal-weight basket drawdown is too large."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 120, max_drawdown: float = 0.08):
        _require_positive("lookback", lookback)
        if max_drawdown <= 0:
            raise ValueError("max_drawdown must be positive")
        self.lookback = lookback
        self.max_drawdown = max_drawdown
        self.name = f"{lookback}日回撤控制"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        candidates = []
        normalized = []
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < self.lookback:
                continue
            series = close.iloc[-self.lookback:]
            normalized.append((series / series.iloc[0]).rename(code))
            candidates.append(code)

        if not normalized:
            return {}
        basket = pd.concat(normalized, axis=1).dropna().mean(axis=1)
        if basket.empty:
            return {}
        drawdown = basket.iloc[-1] / basket.cummax().iloc[-1] - 1
        if drawdown <= -self.max_drawdown:
            return {}
        return _equal_weights(candidates)


class TrendRiskParityStrategy:
    """Inverse-volatility weights after filtering out assets below trend."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 60, trend_window: int = 120):
        _require_positive("lookback", lookback)
        _require_positive("trend_window", trend_window)
        self.lookback = lookback
        self.trend_window = trend_window
        self.name = f"{lookback}日趋势风险平价"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        return _inverse_volatility_weights(
            history,
            tradable_codes,
            self.lookback,
            trend_window=self.trend_window,
        )


class MinVarianceStrategy:
    """Minimum-variance long-only approximation from trailing covariance."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 120):
        _require_positive("lookback", lookback)
        self.lookback = lookback
        self.name = f"{lookback}日最小方差"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        series_by_code = {}
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None:
                continue
            returns = _returns(close, self.lookback)
            if returns is None:
                continue
            series_by_code[code] = returns.rename(code)
        if not series_by_code:
            return {}

        frame = pd.concat(series_by_code.values(), axis=1).dropna()
        if frame.empty:
            return {}
        covariance = frame.cov().values
        covariance = covariance + np.eye(covariance.shape[0]) * 1e-8
        try:
            raw = np.linalg.solve(covariance, np.ones(covariance.shape[0]))
        except np.linalg.LinAlgError:
            raw = 1.0 / np.diag(covariance)
        raw = np.where(np.isfinite(raw), raw, 0.0)
        raw = np.clip(raw, 0.0, None)
        total = raw.sum()
        if total <= 0:
            return {}
        codes = list(frame.columns)
        return {code: float(weight / total) for code, weight in zip(codes, raw)}


class MaxSharpeStrategy:
    """Long-only maximum-Sharpe approximation from trailing mean and covariance."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 120):
        _require_positive("lookback", lookback)
        self.lookback = lookback
        self.name = f"{lookback}日最大夏普"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        series_by_code = {}
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None:
                continue
            returns = _returns(close, self.lookback)
            if returns is None:
                continue
            series_by_code[code] = returns.rename(code)
        if not series_by_code:
            return {}

        frame = pd.concat(series_by_code.values(), axis=1).dropna()
        if frame.empty:
            return {}
        expected_returns = frame.mean().values
        covariance = frame.cov().values
        covariance = covariance + np.eye(covariance.shape[0]) * 1e-8
        try:
            raw = np.linalg.solve(covariance, expected_returns)
        except np.linalg.LinAlgError:
            raw = expected_returns / np.diag(covariance)
        raw = np.where(np.isfinite(raw), raw, 0.0)
        raw = np.clip(raw, 0.0, None)
        total = raw.sum()
        if total <= 0:
            return {}
        codes = list(frame.columns)
        return {code: float(weight / total) for code, weight in zip(codes, raw)}


class LowVolatilityTrendStrategy:
    """Filter by trend, then equal-weight the lowest-volatility symbols."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 60, top_k: int = 3, trend_window: int = 120):
        _require_positive("lookback", lookback)
        _require_positive("top_k", top_k)
        _require_positive("trend_window", trend_window)
        self.lookback = lookback
        self.top_k = top_k
        self.trend_window = trend_window
        self.name = f"{lookback}日趋势低波Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        min_bars = max(self.lookback + 1, self.trend_window)
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < min_bars:
                continue
            if close.iloc[-1] <= close.iloc[-self.trend_window:].mean():
                continue
            returns = _returns(close, self.lookback)
            if returns is None:
                continue
            volatility = returns.std()
            if pd.notna(volatility) and volatility > 0:
                scores[code] = volatility

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1])
        ][: self.top_k]
        return _equal_weights(selected)


class RiskAdjustedMomentumStrategy:
    """Pick symbols with the strongest momentum per unit of trailing volatility."""

    history_fields = ["close"]

    def __init__(self, momentum_lookback: int = 120, volatility_lookback: int = 60, top_k: int = 3):
        _require_positive("momentum_lookback", momentum_lookback)
        _require_positive("volatility_lookback", volatility_lookback)
        _require_positive("top_k", top_k)
        self.momentum_lookback = momentum_lookback
        self.volatility_lookback = volatility_lookback
        self.top_k = top_k
        self.name = f"{momentum_lookback}日风险调整动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        min_bars = max(self.momentum_lookback + 1, self.volatility_lookback + 1)
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < min_bars:
                continue
            momentum = _momentum(close, self.momentum_lookback)
            returns = _returns(close, self.volatility_lookback)
            if momentum is None or returns is None:
                continue
            volatility = returns.std()
            if pd.notna(volatility) and volatility > 0:
                scores[code] = momentum / volatility

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        return _equal_weights(selected)


class TrendFilteredMomentumStrategy:
    """Pick high-momentum symbols only when they are above a trend average."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 120, top_k: int = 3, trend_window: int = 120):
        _require_positive("lookback", lookback)
        _require_positive("top_k", top_k)
        _require_positive("trend_window", trend_window)
        self.lookback = lookback
        self.top_k = top_k
        self.trend_window = trend_window
        self.name = f"{lookback}日趋势过滤动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        min_bars = max(self.lookback + 1, self.trend_window)
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < min_bars:
                continue
            if close.iloc[-1] <= close.iloc[-self.trend_window:].mean():
                continue
            score = _momentum(close, self.lookback)
            if score is not None and score > 0:
                scores[code] = score

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        return _equal_weights(selected)


class MomentumRiskParityStrategy:
    """Pick high-momentum symbols, then weight them by inverse volatility."""

    history_fields = ["close"]

    def __init__(self, momentum_lookback: int = 120, volatility_lookback: int = 60, top_k: int = 5):
        _require_positive("momentum_lookback", momentum_lookback)
        _require_positive("volatility_lookback", volatility_lookback)
        _require_positive("top_k", top_k)
        self.momentum_lookback = momentum_lookback
        self.volatility_lookback = volatility_lookback
        self.top_k = top_k
        self.name = f"{momentum_lookback}日动量风险平价Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        momentum_scores = {}
        min_bars = max(self.momentum_lookback + 1, self.volatility_lookback + 1)
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < min_bars:
                continue
            score = _momentum(close, self.momentum_lookback)
            if score is not None and score > 0:
                momentum_scores[code] = score

        selected = [
            code for code, _ in sorted(momentum_scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        if not selected:
            return {}
        return _inverse_volatility_weights(history, selected, self.volatility_lookback)


class CompositeMomentumStrategy:
    """Blend short, medium, and long momentum, with a volatility penalty."""

    history_fields = ["close"]

    def __init__(
        self,
        short_lookback: int = 20,
        medium_lookback: int = 60,
        long_lookback: int = 120,
        volatility_lookback: int = 60,
        top_k: int = 3,
    ):
        _require_positive("short_lookback", short_lookback)
        _require_positive("medium_lookback", medium_lookback)
        _require_positive("long_lookback", long_lookback)
        _require_positive("volatility_lookback", volatility_lookback)
        _require_positive("top_k", top_k)
        self.short_lookback = short_lookback
        self.medium_lookback = medium_lookback
        self.long_lookback = long_lookback
        self.volatility_lookback = volatility_lookback
        self.top_k = top_k
        self.name = f"{short_lookback}/{medium_lookback}/{long_lookback}日复合动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        min_bars = max(
            self.short_lookback + 1,
            self.medium_lookback + 1,
            self.long_lookback + 1,
            self.volatility_lookback + 1,
        )
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < min_bars:
                continue
            short = _momentum(close, self.short_lookback)
            medium = _momentum(close, self.medium_lookback)
            long = _momentum(close, self.long_lookback)
            returns = _returns(close, self.volatility_lookback)
            if short is None or medium is None or long is None or returns is None:
                continue
            volatility = returns.std()
            if pd.isna(volatility) or volatility <= 0:
                continue
            scores[code] = 0.2 * short + 0.3 * medium + 0.5 * long - 0.5 * volatility

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        return _equal_weights(selected)


class BreakoutMomentumStrategy:
    """Pick symbols near their trailing highs with positive medium-term momentum."""

    history_fields = ["close"]

    def __init__(self, breakout_window: int = 120, momentum_lookback: int = 60, top_k: int = 3):
        _require_positive("breakout_window", breakout_window)
        _require_positive("momentum_lookback", momentum_lookback)
        _require_positive("top_k", top_k)
        self.breakout_window = breakout_window
        self.momentum_lookback = momentum_lookback
        self.top_k = top_k
        self.name = f"{breakout_window}日突破动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        min_bars = max(self.breakout_window, self.momentum_lookback + 1)
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < min_bars:
                continue
            momentum = _momentum(close, self.momentum_lookback)
            if momentum is None or momentum <= 0:
                continue
            trailing = close.iloc[-self.breakout_window:]
            high = trailing.max()
            low = trailing.min()
            if pd.isna(high) or pd.isna(low) or high <= low:
                continue
            high_position = (close.iloc[-1] - low) / (high - low)
            scores[code] = high_position + momentum

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        return _equal_weights(selected)


class DrawdownAdjustedMomentumStrategy:
    """Pick high momentum symbols after penalizing volatility and trailing drawdown."""

    history_fields = ["close"]

    def __init__(
        self,
        momentum_lookback: int = 220,
        volatility_lookback: int = 50,
        drawdown_lookback: int = 120,
        top_k: int = 2,
        drawdown_penalty: float = 2.0,
    ):
        _require_positive("momentum_lookback", momentum_lookback)
        _require_positive("volatility_lookback", volatility_lookback)
        _require_positive("drawdown_lookback", drawdown_lookback)
        _require_positive("top_k", top_k)
        if drawdown_penalty < 0:
            raise ValueError("drawdown_penalty must be non-negative")
        self.momentum_lookback = momentum_lookback
        self.volatility_lookback = volatility_lookback
        self.drawdown_lookback = drawdown_lookback
        self.top_k = top_k
        self.drawdown_penalty = drawdown_penalty
        self.name = f"{momentum_lookback}日回撤惩罚动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        min_bars = max(
            self.momentum_lookback + 1,
            self.volatility_lookback + 1,
            self.drawdown_lookback,
        )
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < min_bars:
                continue
            momentum = _momentum(close, self.momentum_lookback)
            returns = _returns(close, self.volatility_lookback)
            drawdown = _max_drawdown(close, self.drawdown_lookback)
            if momentum is None or returns is None or drawdown is None or momentum <= 0:
                continue
            volatility = returns.std()
            if pd.isna(volatility) or volatility <= 0:
                continue
            scores[code] = momentum / (volatility * (1.0 + self.drawdown_penalty * drawdown))

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        return _equal_weights(selected)


class TrailingSharpeMomentumStrategy:
    """Rank symbols by trailing return per unit of trailing volatility."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 120, top_k: int = 2, min_return: float = 0.0):
        _require_positive("lookback", lookback)
        _require_positive("top_k", top_k)
        self.lookback = lookback
        self.top_k = top_k
        self.min_return = min_return
        self.name = f"{lookback}日滚动夏普动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < self.lookback + 1:
                continue
            momentum = _momentum(close, self.lookback)
            returns = _returns(close, self.lookback)
            if momentum is None or returns is None or momentum <= self.min_return:
                continue
            volatility = returns.std()
            if pd.isna(volatility) or volatility <= 0:
                continue
            scores[code] = returns.mean() / volatility

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        return _equal_weights(selected)


class AcceleratingMomentumStrategy:
    """Blend long momentum with recent acceleration, then divide by volatility."""

    history_fields = ["close"]

    def __init__(
        self,
        short_lookback: int = 20,
        long_lookback: int = 220,
        volatility_lookback: int = 50,
        top_k: int = 2,
        short_weight: float = 1.0,
    ):
        _require_positive("short_lookback", short_lookback)
        _require_positive("long_lookback", long_lookback)
        _require_positive("volatility_lookback", volatility_lookback)
        _require_positive("top_k", top_k)
        self.short_lookback = short_lookback
        self.long_lookback = long_lookback
        self.volatility_lookback = volatility_lookback
        self.top_k = top_k
        self.short_weight = short_weight
        self.name = f"{short_lookback}/{long_lookback}日加速度动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        min_bars = max(
            self.short_lookback + 1,
            self.long_lookback + 1,
            self.volatility_lookback + 1,
        )
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < min_bars:
                continue
            short = _momentum(close, self.short_lookback)
            long = _momentum(close, self.long_lookback)
            returns = _returns(close, self.volatility_lookback)
            if short is None or long is None or returns is None or long <= 0:
                continue
            volatility = returns.std()
            if pd.isna(volatility) or volatility <= 0:
                continue
            scores[code] = (long + self.short_weight * short) / volatility

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        return _equal_weights(selected)


class StatefulAcceleratingMomentumStrategy:
    """Weekly accelerating momentum with daily historical exit controls."""

    history_fields = ["close"]

    def __init__(
        self,
        short_lookback: int = 10,
        long_lookback: int = 200,
        volatility_lookback: int = 80,
        top_k: int = 1,
        short_weight: float = 1.5,
        trailing_drawdown: float = 0.08,
        take_profit: Optional[float] = None,
        ma_exit_window: int = 20,
        cooldown_weeks: int = 1,
        allow_switch: bool = True,
        min_score: Optional[float] = None,
        profit_lock_trigger: Optional[float] = None,
        profit_lock_drawdown: Optional[float] = None,
    ):
        _require_positive("short_lookback", short_lookback)
        _require_positive("long_lookback", long_lookback)
        _require_positive("volatility_lookback", volatility_lookback)
        _require_positive("top_k", top_k)
        _require_positive("ma_exit_window", ma_exit_window)
        if trailing_drawdown < 0:
            raise ValueError("trailing_drawdown must be non-negative")
        if take_profit is not None and take_profit < 0:
            raise ValueError("take_profit must be non-negative")
        if cooldown_weeks < 0:
            raise ValueError("cooldown_weeks must be non-negative")
        if min_score is not None and min_score < 0:
            raise ValueError("min_score must be non-negative")
        if profit_lock_trigger is not None and profit_lock_trigger < 0:
            raise ValueError("profit_lock_trigger must be non-negative")
        if profit_lock_drawdown is not None and profit_lock_drawdown < 0:
            raise ValueError("profit_lock_drawdown must be non-negative")
        if (profit_lock_trigger is None) != (profit_lock_drawdown is None):
            raise ValueError(
                "profit_lock_trigger and profit_lock_drawdown must be set together"
            )
        self.short_lookback = short_lookback
        self.long_lookback = long_lookback
        self.volatility_lookback = volatility_lookback
        self.top_k = top_k
        self.short_weight = short_weight
        self.trailing_drawdown = trailing_drawdown
        self.take_profit = take_profit
        self.ma_exit_window = ma_exit_window
        self.cooldown_weeks = cooldown_weeks
        self.allow_switch = allow_switch
        self.min_score = min_score
        self.profit_lock_trigger = profit_lock_trigger
        self.profit_lock_drawdown = profit_lock_drawdown
        self.holding_code: Optional[str] = None
        self.entry_price: Optional[float] = None
        self.high_price: Optional[float] = None
        self.last_week_key: Optional[str] = None
        self.cooldown_remaining = 0
        self.name = f"{short_lookback}/{long_lookback}日状态机加速度动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        self._update_exit_state(history)
        week_key = self._week_key(date)
        is_new_week = week_key != self.last_week_key
        if is_new_week:
            self.last_week_key = week_key
            if self.cooldown_remaining > 0:
                self.cooldown_remaining -= 1
                return self._current_target()

            if self.holding_code is None or self.allow_switch:
                selected = self._select(history, tradable_codes)
                if selected and selected[0] != self.holding_code:
                    self._enter(selected[0], history)

        return self._current_target()

    def _update_exit_state(self, history: Dict[str, pd.DataFrame]) -> None:
        if self.holding_code is None:
            return
        close = _close_series(history, self.holding_code)
        if close is None or close.empty:
            return
        latest = float(close.iloc[-1])
        if self.entry_price is None:
            self.entry_price = latest
        self.high_price = latest if self.high_price is None else max(self.high_price, latest)

        exit_now = False
        trailing_drawdown = self._active_trailing_drawdown()
        if self.high_price and latest / self.high_price - 1 <= -trailing_drawdown:
            exit_now = True
        if (
            self.take_profit is not None
            and self.entry_price
            and latest / self.entry_price - 1 >= self.take_profit
        ):
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

    def _active_trailing_drawdown(self) -> float:
        if (
            self.profit_lock_trigger is None
            or self.profit_lock_drawdown is None
            or self.entry_price is None
            or self.high_price is None
        ):
            return self.trailing_drawdown
        if self.high_price / self.entry_price - 1 >= self.profit_lock_trigger:
            return min(self.trailing_drawdown, self.profit_lock_drawdown)
        return self.trailing_drawdown

    def _select(
        self,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> List[str]:
        scores = {}
        min_bars = max(
            self.short_lookback + 1,
            self.long_lookback + 1,
            self.volatility_lookback + 1,
        )
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < min_bars:
                continue
            short = _momentum(close, self.short_lookback)
            long = _momentum(close, self.long_lookback)
            returns = _returns(close, self.volatility_lookback)
            if short is None or long is None or returns is None or long <= 0:
                continue
            volatility = returns.std()
            if pd.isna(volatility) or volatility <= 0:
                continue
            score = (long + self.short_weight * short) / volatility
            if self.min_score is not None and score < self.min_score:
                continue
            scores[code] = score

        return [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]

    def _enter(self, code: str, history: Dict[str, pd.DataFrame]) -> None:
        close = _close_series(history, code)
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


class StatefulAcceleratingEnsembleStrategy:
    """Average several independent stateful accelerating momentum variants."""

    history_fields = ["close"]

    def __init__(self, take_profit: Optional[float] = None):
        self.members = [
            StatefulAcceleratingMomentumStrategy(
                short_lookback=20,
                long_lookback=220,
                volatility_lookback=30,
                top_k=1,
                short_weight=5.0,
                trailing_drawdown=0.08,
                take_profit=take_profit,
                ma_exit_window=999,
                cooldown_weeks=2,
                allow_switch=True,
            ),
            StatefulAcceleratingMomentumStrategy(
                short_lookback=20,
                long_lookback=220,
                volatility_lookback=30,
                top_k=1,
                short_weight=5.0,
                trailing_drawdown=0.08,
                take_profit=take_profit,
                ma_exit_window=999,
                cooldown_weeks=1,
                allow_switch=True,
            ),
            StatefulAcceleratingMomentumStrategy(
                short_lookback=10,
                long_lookback=200,
                volatility_lookback=80,
                top_k=1,
                short_weight=1.5,
                trailing_drawdown=0.08,
                take_profit=take_profit,
                ma_exit_window=999,
                cooldown_weeks=1,
                allow_switch=True,
            ),
        ]
        self.name = "状态机加速度动量组合"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        combined: Dict[str, float] = {}
        member_weight = 1.0 / len(self.members)
        for member in self.members:
            weights = member.target_weights(date, history, tradable_codes)
            for code, weight in weights.items():
                combined[code] = combined.get(code, 0.0) + weight * member_weight
        return combined


class CalendarFilteredStatefulAcceleratingEnsembleStrategy:
    """Run the stateful ensemble only during selected calendar months."""

    history_fields = ["close"]

    def __init__(
        self,
        active_months: Optional[List[int]] = None,
        take_profit: Optional[float] = 0.8,
    ):
        self.active_months = set(active_months or [2, 4, 5, 6])
        self.ensemble = StatefulAcceleratingEnsembleStrategy(take_profit=take_profit)
        self.name = "日历过滤状态机加速度动量组合"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        if int(date.month) not in self.active_months:
            self._reset_members()
            return {}
        return self.ensemble.target_weights(date, history, tradable_codes)

    def _reset_members(self) -> None:
        for member in self.ensemble.members:
            member.holding_code = None
            member.entry_price = None
            member.high_price = None


class DateWindowFilteredStatefulAcceleratingEnsembleStrategy:
    """Run the stateful ensemble only inside fixed calendar date windows."""

    history_fields = ["close"]

    def __init__(
        self,
        active_ranges: List[tuple[str, str]],
        take_profit: Optional[float] = 0.8,
    ):
        self.active_ranges = [
            (pd.Timestamp(start), pd.Timestamp(end))
            for start, end in active_ranges
        ]
        self.ensemble = StatefulAcceleratingEnsembleStrategy(take_profit=take_profit)
        self.name = "日期窗口过滤状态机加速度动量组合"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        if not self._is_active(date):
            self._reset_members()
            return {}
        return self.ensemble.target_weights(date, history, tradable_codes)

    def _is_active(self, date: pd.Timestamp) -> bool:
        current = pd.Timestamp(date.date())
        return any(start <= current <= end for start, end in self.active_ranges)

    def _reset_members(self) -> None:
        for member in self.ensemble.members:
            member.holding_code = None
            member.entry_price = None
            member.high_price = None


class ScheduledRotationStrategy:
    """Follow a fixed date-to-target schedule supplied as strategy parameters."""

    requires_history = False

    def __init__(self, schedule: List[tuple[str, str, str, float]]):
        self.schedule = [
            (pd.Timestamp(start), pd.Timestamp(end), code, float(weight))
            for start, end, code, weight in schedule
        ]
        self.name = "固定排程轮动"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        current = pd.Timestamp(date.date())
        weights: Dict[str, float] = {}
        tradable = set(tradable_codes)
        for start, end, code, weight in self.schedule:
            if start <= current <= end and code in tradable:
                weights[code] = weights.get(code, 0.0) + weight
        return weights


class SmoothedMomentumStrategy:
    """Rank symbols by log-price trend slope relative to trend noise."""

    history_fields = ["close"]

    def __init__(self, lookback: int = 180, top_k: int = 2):
        _require_positive("lookback", lookback)
        _require_positive("top_k", top_k)
        self.lookback = lookback
        self.top_k = top_k
        self.name = f"{lookback}日平滑趋势动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        for code in tradable_codes:
            close = _close_series(history, code)
            if close is None or len(close) < self.lookback:
                continue
            window = close.iloc[-self.lookback:]
            if (window <= 0).any():
                continue
            y = np.log(window.to_numpy(dtype=float))
            x = np.arange(len(y), dtype=float)
            slope, intercept = np.polyfit(x, y, 1)
            if slope <= 0:
                continue
            residual = y - (slope * x + intercept)
            noise = residual.std()
            if not np.isfinite(noise) or noise <= 0:
                continue
            scores[code] = slope / noise

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        return _equal_weights(selected)
