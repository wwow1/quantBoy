from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


def _week_start(date_str: str) -> str:
    """Monday of the ISO week containing YYYYMMDD."""
    d = datetime.strptime(date_str, "%Y%m%d")
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("%Y%m%d")


def _available_from(week: str) -> str:
    """First date a week's aggregated score may be used (next Monday)."""
    d = datetime.strptime(week, "%Y%m%d") + timedelta(days=7)
    return d.strftime("%Y%m%d")


def _days_between(a: str, b: str) -> int:
    da = datetime.strptime(a, "%Y%m%d")
    db = datetime.strptime(b, "%Y%m%d")
    return (db - da).days


class SentimentBiasStrategy:
    """Tilt an inner strategy's target weights by LLM research-title sentiment.

    Sentiment is a *bias*, not a signal: each held code's weight is scaled by
    ``(1 + max_tilt * centered_score)`` where centered_score is the code's
    weekly bull_ratio score minus the cross-sectional mean over ALL codes
    scored that week (not just held ones, so single-name strategies still
    get a tilt), then weights are renormalized to the inner strategy's
    total exposure. ``max_tilt`` caps the per-name distortion
    (default 0.15 => +-15%).

    PIT: a week's score is only usable from the following Monday
    (week + 7 days), and scores older than ``max_age_weeks`` are treated
    as missing (no tilt).
    """

    def __init__(
        self,
        inner_strategy,
        db_path: str,
        max_tilt: float = 0.15,
        max_age_weeks: int = 4,
        table: str = "research_sentiment",
    ):
        self.inner_strategy = inner_strategy
        self.max_tilt = max_tilt
        self.max_age_weeks = max_age_weeks
        self.history_fields = getattr(inner_strategy, "history_fields", [])
        self.requires_history = getattr(inner_strategy, "requires_history", True)
        self._scores: Dict[str, List[Tuple[str, float]]] = {}
        self._week_means: Dict[str, float] = {}
        self._loaded = False
        self._db_path = db_path
        self._table = table

    def _load(self) -> None:
        self._loaded = True
        path = Path(self._db_path)
        if not path.exists():
            return
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            df = pd.read_sql(
                f"SELECT ts_code, week, bull_ratio FROM {self._table} "
                "WHERE n_reports >= 1 ORDER BY week",
                conn,
            )
        except Exception:
            return
        finally:
            conn.close()
        week_sum: Dict[str, float] = {}
        week_n: Dict[str, int] = {}
        for ts_code, week, bull_ratio in df.itertuples(index=False, name=None):
            code = str(ts_code).split(".")[0]
            week = str(week)
            score = 2.0 * float(bull_ratio) - 1.0
            self._scores.setdefault(code, []).append((week, score))
            week_sum[week] = week_sum.get(week, 0.0) + score
            week_n[week] = week_n.get(week, 0) + 1
        self._week_means = {w: week_sum[w] / week_n[w] for w in week_sum}

    def _score(self, code: str, date: str) -> Optional[Tuple[float, float]]:
        """(score, cross-sectional mean) usable at ``date``, else None."""
        series = self._scores.get(code)
        if not series:
            return None
        usable = [
            (week, score)
            for week, score in series
            if _available_from(week) <= date
        ]
        if not usable:
            return None
        week, score = usable[-1]
        if _days_between(week, _week_start(date)) // 7 > self.max_age_weeks:
            return None
        cross = self._week_means.get(week)
        if cross is None:
            return None
        return score, cross

    def target_weights(
        self,
        date: str,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        weights = self.inner_strategy.target_weights(date, history, tradable_codes)
        if not self._loaded:
            self._load()
        if not weights or not self._scores:
            return weights
        raw = {code: self._score(code, date) for code in weights}
        known = [c for c, v in raw.items() if v is not None]
        if not known:
            return weights
        tilted = {}
        for code, weight in weights.items():
            pair = raw[code]
            factor = 1.0 + self.max_tilt * (pair[0] - pair[1]) if pair else 1.0
            tilted[code] = weight * factor
        total = sum(tilted.values())
        if total <= 0:
            return weights
        scale = sum(weights.values()) / total
        return {code: w * scale for code, w in tilted.items()}
