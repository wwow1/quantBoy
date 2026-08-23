from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd


def _close_series(
    history: Dict[str, pd.DataFrame],
    code: str,
) -> Optional[pd.Series]:
    close = history.get(code, pd.DataFrame()).get("close")
    if close is None:
        return None
    close = close.dropna()
    if close.empty:
        return None
    return close


class MarketTrendFilterStrategy:
    """Gate a target-weight strategy by a reference symbol's own trend."""

    history_fields = ["close"]

    def __init__(
        self,
        inner_strategy,
        reference_code: str = "510300",
        trend_window: int = 120,
        min_momentum: Optional[float] = None,
    ):
        if trend_window <= 0:
            raise ValueError("trend_window must be positive")
        self.inner_strategy = inner_strategy
        self.reference_code = reference_code.split(".", 1)[0]
        self.trend_window = trend_window
        self.min_momentum = min_momentum
        self.name = f"{getattr(inner_strategy, 'name', 'strategy')} with market trend filter"

        inner_fields = list(getattr(inner_strategy, "history_fields", ["close"]))
        self.history_fields = sorted(set(inner_fields + ["close"]))
        self.requires_history = getattr(inner_strategy, "requires_history", True)

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        if not self._market_allows_risk(history):
            self._reset_inner_state()
            return {}
        return self.inner_strategy.target_weights(date, history, tradable_codes)

    def _market_allows_risk(self, history: Dict[str, pd.DataFrame]) -> bool:
        close = _close_series(history, self.reference_code)
        if close is None or len(close) < self.trend_window:
            return False
        latest = close.iloc[-1]
        trend = close.iloc[-self.trend_window:].mean()
        if pd.isna(latest) or pd.isna(trend) or latest <= trend:
            return False
        if self.min_momentum is None:
            return True
        if len(close) < self.trend_window + 1:
            return False
        momentum = latest / close.iloc[-self.trend_window - 1] - 1
        return bool(pd.notna(momentum) and momentum >= self.min_momentum)

    def _reset_inner_state(self) -> None:
        for name in ("holding_code", "entry_price", "high_price"):
            if hasattr(self.inner_strategy, name):
                setattr(self.inner_strategy, name, None)
        if hasattr(self.inner_strategy, "cooldown_remaining"):
            setattr(self.inner_strategy, "cooldown_remaining", 0)


class WeightedStrategyEnsemble:
    """Combine target weights from multiple independent strategies."""

    def __init__(self, members: Sequence[Tuple[object, float]], name: str = "weighted ensemble"):
        if not members:
            raise ValueError("members must not be empty")
        total = sum(weight for _, weight in members)
        if total <= 0:
            raise ValueError("member weights must sum to a positive value")
        self.members = [(strategy, weight / total) for strategy, weight in members]
        self.name = name
        fields = []
        self.requires_history = False
        for strategy, _ in self.members:
            fields.extend(getattr(strategy, "history_fields", ["close"]))
            self.requires_history = self.requires_history or getattr(strategy, "requires_history", True)
        self.history_fields = sorted(set(fields))

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        combined: Dict[str, float] = {}
        for strategy, member_weight in self.members:
            weights = strategy.target_weights(date, history, tradable_codes)
            for code, weight in weights.items():
                combined[code] = combined.get(code, 0.0) + member_weight * weight
        return combined
