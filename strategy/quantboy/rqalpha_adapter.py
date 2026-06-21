"""
RQAlpha adapter for QuantBoy target-weight strategies.

This adapter lets a QuantBoy strategy that returns `{code: weight}` run inside
RQAlpha. It is intentionally small and currently targets ETF/stock daily
research with RQAlpha's own bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set

import pandas as pd


@dataclass
class RQAlphaAdapterConfig:
    codes: List[str]
    history_bars: int = 260
    rebalance: str = "monthly"
    max_total_weight: float = 0.99
    use_pre_start_history: bool = False


def to_rqalpha_order_book_id(code: str) -> str:
    if "." in code:
        return code
    if code.startswith(("5", "6", "9")):
        return f"{code}.XSHG"
    return f"{code}.XSHE"


def from_rqalpha_order_book_id(order_book_id: str) -> str:
    return order_book_id.split(".", 1)[0]


class RQAlphaTargetWeightAdapter:
    def __init__(self, strategy, config: RQAlphaAdapterConfig):
        self.strategy = strategy
        self.config = config
        self.order_book_ids = [to_rqalpha_order_book_id(code) for code in config.codes]
        self._last_rebalance_key: Optional[str] = None
        self._history_start_date: Optional[pd.Timestamp] = None

    def init_context(self, context) -> None:
        from rqalpha.apis import update_universe

        context.quantboy_adapter = self
        if not self.config.use_pre_start_history:
            self._history_start_date = pd.Timestamp(context.config.base.start_date)
        update_universe(self.order_book_ids)

    def handle_bar(self, context, bar_dict) -> None:
        trading_date = pd.Timestamp(context.now.date())
        if not self._should_rebalance(trading_date):
            return

        tradable_order_book_ids = [
            order_book_id for order_book_id in self.order_book_ids
            if order_book_id in bar_dict and not getattr(bar_dict[order_book_id], "isnan", False)
        ]
        tradable_codes = [from_rqalpha_order_book_id(order_book_id) for order_book_id in tradable_order_book_ids]

        history = self._build_history(tradable_order_book_ids)
        target_weights = self.strategy.target_weights(trading_date, history, tradable_codes)
        target_weights = self._normalize_weights(target_weights)
        self._apply_target_weights(target_weights)

    def _should_rebalance(self, trading_date: pd.Timestamp) -> bool:
        if self.config.rebalance != "monthly":
            raise ValueError(f"unsupported rebalance mode: {self.config.rebalance}")
        key = trading_date.strftime("%Y-%m")
        if key == self._last_rebalance_key:
            return False
        self._last_rebalance_key = key
        return True

    def _build_history(self, order_book_ids: Iterable[str]) -> Dict[str, pd.DataFrame]:
        from rqalpha.apis import history_bars

        history = {}
        for order_book_id in order_book_ids:
            bars = history_bars(
                order_book_id,
                self.config.history_bars,
                "1d",
                fields=["datetime", "open", "high", "low", "close", "volume", "total_turnover"],
                include_now=False,
                adjust_type="pre",
            )
            code = from_rqalpha_order_book_id(order_book_id)
            df = self._bars_to_frame(bars)
            if self._history_start_date is not None:
                df = df[df.index >= self._history_start_date]
            history[code] = df
        return history

    @staticmethod
    def _bars_to_frame(bars) -> pd.DataFrame:
        if bars is None or len(bars) == 0:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])

        df = pd.DataFrame(bars)
        if "datetime" in df.columns:
            dt = df["datetime"].astype(str).str[:8]
            df["date"] = pd.to_datetime(dt, format="%Y%m%d")
            df = df.set_index("date")
            df = df.drop(columns=["datetime"])
        if "total_turnover" in df.columns:
            df = df.rename(columns={"total_turnover": "amount"})
        return df.sort_index()

    def _normalize_weights(self, target_weights: Dict[str, float]) -> Dict[str, float]:
        weights = {code: max(float(weight), 0.0) for code, weight in target_weights.items()}
        total = sum(weights.values())
        if total <= 0:
            return {}
        scale = min(total, self.config.max_total_weight) / total
        return {code: weight * scale for code, weight in weights.items() if weight > 0}

    def _apply_target_weights(self, target_weights: Dict[str, float]) -> None:
        from rqalpha.apis import order_target_percent

        target_order_book_ids: Set[str] = {
            to_rqalpha_order_book_id(code) for code in target_weights
        }

        # Sell first so buys have cash available.
        for order_book_id in self.order_book_ids:
            if order_book_id not in target_order_book_ids:
                order_target_percent(order_book_id, 0.0)

        for code, weight in target_weights.items():
            order_target_percent(to_rqalpha_order_book_id(code), weight)
