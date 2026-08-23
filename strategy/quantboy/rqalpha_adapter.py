"""
RQAlpha adapter for QuantBoy target-weight strategies.

This adapter lets a QuantBoy strategy that returns `{code: weight}` run inside
RQAlpha. It is intentionally small and currently targets ETF/stock daily
research with RQAlpha's own bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import pandas as pd


@dataclass
class RQAlphaAdapterConfig:
    codes: List[str]
    history_bars: int = 260
    rebalance: str = "daily"
    max_total_weight: float = 0.99
    use_pre_start_history: bool = False
    min_avg_turnover: float = 0.0
    liquidity_lookback: int = 20
    avoid_limit_trades: bool = True
    exclude_buy_boards: List[str] = field(default_factory=list)
    bundle_path: Optional[str] = None
    fast_history_cache: bool = True
    history_cache_workers: int = 8


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
        self.config.rebalance = self.config.rebalance.lower()
        if self.config.rebalance not in {"daily", "weekly", "monthly"}:
            raise ValueError(f"unsupported rebalance mode: {self.config.rebalance}")
        self.order_book_ids = [to_rqalpha_order_book_id(code) for code in config.codes]
        self._last_rebalance_key: Optional[str] = None
        self._history_start_date: Optional[pd.Timestamp] = None
        self._close_history_cache: Dict[str, pd.Series] = {}
        self._turnover_history_cache: Dict[str, pd.Series] = {}
        self._preloaded_close_history = False
        self._preloaded_turnover_history = False

    def init_context(self, context) -> None:
        from rqalpha.apis import update_universe

        context.quantboy_adapter = self
        if not self.config.use_pre_start_history:
            self._history_start_date = pd.Timestamp(context.config.base.start_date)
        update_universe(self.order_book_ids)
        self._preload_close_history_cache()
        self._preload_turnover_history_cache()

    def handle_bar(self, context, bar_dict) -> None:
        trading_date = pd.Timestamp(context.now.date())
        tradable_order_book_ids = [
            order_book_id for order_book_id in self.order_book_ids
            if order_book_id in bar_dict and not getattr(bar_dict[order_book_id], "isnan", False)
        ]
        if self._should_rebalance(trading_date):
            total_value = getattr(getattr(context, "portfolio", None), "total_value", 0.0)
            candidate_order_book_ids = [
                order_book_id for order_book_id in tradable_order_book_ids
                if self._passes_liquidity_filter(order_book_id, trading_date)
                and not self._is_excluded_buy_board(order_book_id)
                and self._passes_limit_candidate_filter(
                    context,
                    order_book_id,
                    bar_dict[order_book_id],
                    total_value,
                )
            ]
            tradable_codes = [
                from_rqalpha_order_book_id(order_book_id)
                for order_book_id in candidate_order_book_ids
            ]

            history = {}
            if getattr(self.strategy, "requires_history", True):
                history = self._build_history(candidate_order_book_ids, trading_date)
            target_weights = self.strategy.target_weights(trading_date, history, tradable_codes)
            target_weights = self._normalize_weights(target_weights)
            self._apply_target_weights(target_weights, tradable_order_book_ids, bar_dict, context)

        self._update_close_history_cache(trading_date, tradable_order_book_ids, bar_dict)

    def _should_rebalance(self, trading_date: pd.Timestamp) -> bool:
        if self.config.rebalance == "daily":
            key = trading_date.strftime("%Y-%m-%d")
        elif self.config.rebalance == "weekly":
            year, week, _ = trading_date.isocalendar()
            key = f"{year}-W{week:02d}"
        else:
            key = trading_date.strftime("%Y-%m")

        if key == self._last_rebalance_key:
            return False
        self._last_rebalance_key = key
        return True

    def _build_history(
        self,
        order_book_ids: Iterable[str],
        trading_date: pd.Timestamp,
    ) -> Dict[str, pd.DataFrame]:
        if self._uses_close_history_cache():
            return self._build_close_history(order_book_ids, trading_date)

        from rqalpha.apis import history_bars

        history = {}
        fields = self._history_fields()
        for order_book_id in order_book_ids:
            bars = history_bars(
                order_book_id,
                self.config.history_bars,
                "1d",
                fields=fields,
                include_now=False,
                adjust_type="pre",
            )
            code = from_rqalpha_order_book_id(order_book_id)
            df = self._bars_to_frame(bars)
            if self._history_start_date is not None:
                df = df[df.index >= self._history_start_date]
            history[code] = df
        return history

    def _history_fields(self) -> List[str]:
        fields = list(getattr(self.strategy, "history_fields", ["close"]))
        if "datetime" not in fields:
            fields.insert(0, "datetime")
        return fields

    def _uses_close_history_cache(self) -> bool:
        return self._history_fields() == ["datetime", "close"]

    def _build_close_history(
        self,
        order_book_ids: Iterable[str],
        trading_date: pd.Timestamp,
    ) -> Dict[str, pd.DataFrame]:
        history = {}
        for order_book_id in order_book_ids:
            series = self._close_history_cache.get(order_book_id)
            if series is None:
                series = self._load_initial_close_history(order_book_id)
                self._close_history_cache[order_book_id] = series
            series = series[series.index < trading_date].tail(self.config.history_bars)
            code = from_rqalpha_order_book_id(order_book_id)
            history[code] = series.to_frame(name="close")
        return history

    def _load_initial_close_history(self, order_book_id: str) -> pd.Series:
        from rqalpha.apis import history_bars

        bars = history_bars(
            order_book_id,
            self.config.history_bars,
            "1d",
            fields=["datetime", "close"],
            include_now=False,
            adjust_type="pre",
        )
        df = self._bars_to_frame(bars)
        if self._history_start_date is not None:
            df = df[df.index >= self._history_start_date]
        if "close" not in df.columns:
            return pd.Series(dtype=float)
        return df["close"].dropna().tail(self.config.history_bars)

    def _preload_close_history_cache(self) -> None:
        if not self.config.fast_history_cache:
            return
        if not getattr(self.strategy, "requires_history", True):
            return
        if not self._uses_close_history_cache():
            return

        bundle_path = self._bundle_path()
        if bundle_path is None:
            return

        pairs = [
            (order_book_id, self._bundle_h5_file(bundle_path, order_book_id))
            for order_book_id in self.order_book_ids
        ]
        pairs = [
            (order_book_id, file_path)
            for order_book_id, file_path in pairs
            if file_path is not None and file_path.exists()
        ]
        if not pairs:
            return

        workers = max(1, int(self.config.history_cache_workers))
        workers = min(workers, len(pairs))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self._read_close_series_from_h5, order_book_id, file_path): order_book_id
                for order_book_id, file_path in pairs
            }
            for future in as_completed(futures):
                order_book_id = futures[future]
                try:
                    series = future.result()
                except Exception:
                    continue
                if not series.empty:
                    self._close_history_cache[order_book_id] = series

        if self._close_history_cache:
            self._preloaded_close_history = True

    def _preload_turnover_history_cache(self) -> None:
        if not self.config.fast_history_cache:
            return
        if self.config.min_avg_turnover <= 0:
            return

        bundle_path = self._bundle_path()
        if bundle_path is None:
            return

        pairs = [
            (order_book_id, self._bundle_h5_file(bundle_path, order_book_id))
            for order_book_id in self.order_book_ids
        ]
        pairs = [
            (order_book_id, file_path)
            for order_book_id, file_path in pairs
            if file_path is not None and file_path.exists()
        ]
        if not pairs:
            return

        workers = max(1, int(self.config.history_cache_workers))
        workers = min(workers, len(pairs))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    self._read_field_series_from_h5,
                    order_book_id,
                    file_path,
                    "total_turnover",
                ): order_book_id
                for order_book_id, file_path in pairs
            }
            for future in as_completed(futures):
                order_book_id = futures[future]
                try:
                    series = future.result()
                except Exception:
                    continue
                if not series.empty:
                    self._turnover_history_cache[order_book_id] = series

        if self._turnover_history_cache:
            self._preloaded_turnover_history = True

    def _bundle_path(self) -> Optional[Path]:
        raw = self.config.bundle_path or os.environ.get("QUANTBOY_RQ_BUNDLE")
        if not raw:
            return None
        path = Path(raw)
        return path if path.exists() else None

    @staticmethod
    def _bundle_h5_file(bundle_path: Path, order_book_id: str) -> Optional[Path]:
        if order_book_id.endswith((".XSHG", ".XSHE")):
            code = from_rqalpha_order_book_id(order_book_id)
            if code.startswith(("1", "5")):
                return bundle_path / "funds.h5"
            return bundle_path / "stocks.h5"
        return None

    def _read_close_series_from_h5(self, order_book_id: str, file_path: Path) -> pd.Series:
        return self._read_field_series_from_h5(order_book_id, file_path, "close")

    def _read_field_series_from_h5(
        self,
        order_book_id: str,
        file_path: Path,
        field: str,
    ) -> pd.Series:
        import h5py

        with h5py.File(file_path, "r") as file:
            if order_book_id not in file:
                return pd.Series(dtype=float)
            data = file[order_book_id][:]

        if len(data) == 0 or field not in data.dtype.names:
            return pd.Series(dtype=float)
        dates = pd.to_datetime(
            pd.Series(data["datetime"]).astype(str).str[:8],
            format="%Y%m%d",
        )
        series = pd.Series(data[field], index=dates).dropna().sort_index()
        if self._history_start_date is not None:
            series = series[series.index >= self._history_start_date]
        return series

    def _passes_liquidity_filter(
        self,
        order_book_id: str,
        trading_date: pd.Timestamp,
    ) -> bool:
        if self.config.min_avg_turnover <= 0:
            return True
        series = self._turnover_history_cache.get(order_book_id)
        if series is None:
            bundle_path = self._bundle_path()
            file_path = None if bundle_path is None else self._bundle_h5_file(bundle_path, order_book_id)
            if file_path is None or not file_path.exists():
                return False
            series = self._read_field_series_from_h5(order_book_id, file_path, "total_turnover")
            self._turnover_history_cache[order_book_id] = series

        lookback = max(1, int(self.config.liquidity_lookback))
        recent = series[series.index < trading_date].tail(lookback)
        if len(recent) < lookback:
            return False
        average_turnover = recent.mean()
        return bool(pd.notna(average_turnover) and average_turnover >= self.config.min_avg_turnover)

    @staticmethod
    def _is_limit_up(bar) -> bool:
        close = getattr(bar, "close", None)
        limit_up = getattr(bar, "limit_up", None)
        if close is None or limit_up is None or pd.isna(close) or pd.isna(limit_up):
            return False
        return close >= limit_up

    @staticmethod
    def _is_limit_down(bar) -> bool:
        close = getattr(bar, "close", None)
        limit_down = getattr(bar, "limit_down", None)
        if close is None or limit_down is None or pd.isna(close) or pd.isna(limit_down):
            return False
        return close <= limit_down

    def _is_excluded_buy_board(self, order_book_id: str) -> bool:
        excluded = {
            str(board).strip().lower()
            for board in self.config.exclude_buy_boards
            if str(board).strip()
        }
        if not excluded:
            return False

        code = from_rqalpha_order_book_id(order_book_id)
        board_aliases = {
            "star": {"star", "sci-tech", "科创板", "科创版"},
            "chinext": {"chinext", "创业板"},
        }
        blocked_star = bool(excluded & board_aliases["star"])
        blocked_chinext = bool(excluded & board_aliases["chinext"])

        if blocked_star and order_book_id.endswith(".XSHG") and code.startswith(("688", "689")):
            return True
        if blocked_chinext and order_book_id.endswith(".XSHE") and code.startswith(("300", "301", "302")):
            return True
        return False

    def _passes_limit_candidate_filter(
        self,
        context,
        order_book_id: str,
        bar,
        total_value: float,
    ) -> bool:
        if not self.config.avoid_limit_trades:
            return True
        if not self._is_limit_up(bar) and not self._is_limit_down(bar):
            return True
        return self._current_weight(context, order_book_id, total_value) > 0

    def _update_close_history_cache(
        self,
        trading_date: pd.Timestamp,
        order_book_ids: Iterable[str],
        bar_dict,
    ) -> None:
        if not getattr(self.strategy, "requires_history", True):
            return
        if not self._uses_close_history_cache():
            return
        if self._preloaded_close_history:
            return

        for order_book_id in order_book_ids:
            bar = bar_dict[order_book_id]
            close = getattr(bar, "close", None)
            if close is None or pd.isna(close):
                continue

            series = self._close_history_cache.get(order_book_id)
            if series is None:
                series = pd.Series(dtype=float)
            if trading_date in series.index:
                series.loc[trading_date] = close
            else:
                series = pd.concat([series, pd.Series([close], index=[trading_date])])
            self._close_history_cache[order_book_id] = series.tail(self.config.history_bars)

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

    def _apply_target_weights(
        self,
        target_weights: Dict[str, float],
        tradable_order_book_ids: Iterable[str],
        bar_dict,
        context,
    ) -> None:
        from rqalpha.apis import order_target_percent

        total_value = getattr(getattr(context, "portfolio", None), "total_value", 0.0)
        target_order_book_ids: Set[str] = {
            to_rqalpha_order_book_id(code) for code in target_weights
        }

        # Sell first so buys have cash available.
        for order_book_id in tradable_order_book_ids:
            if order_book_id not in target_order_book_ids:
                if (
                    self.config.avoid_limit_trades
                    and self._is_limit_down(bar_dict[order_book_id])
                    and self._current_weight(context, order_book_id, total_value) > 0
                ):
                    continue
                order_target_percent(order_book_id, 0.0)

        for code, weight in target_weights.items():
            order_book_id = to_rqalpha_order_book_id(code)
            current_weight = self._current_weight(context, order_book_id, total_value)
            if self._is_excluded_buy_board(order_book_id) and weight > current_weight:
                continue
            if self.config.avoid_limit_trades:
                bar = bar_dict[order_book_id]
                if self._is_limit_up(bar) and weight > current_weight:
                    continue
                if self._is_limit_down(bar) and weight < current_weight:
                    continue
            order_target_percent(order_book_id, weight)

    @staticmethod
    def _current_weight(context, order_book_id: str, total_value: float) -> float:
        if total_value <= 0:
            return 0.0
        portfolio = getattr(context, "portfolio", None)
        positions = getattr(portfolio, "positions", None)
        position = None
        if positions is not None:
            try:
                position = positions.get(order_book_id)
            except AttributeError:
                try:
                    position = positions[order_book_id]
                except Exception:
                    position = None
        market_value = getattr(position, "market_value", 0.0) if position is not None else 0.0
        if pd.isna(market_value):
            return 0.0
        return float(market_value) / float(total_value)
