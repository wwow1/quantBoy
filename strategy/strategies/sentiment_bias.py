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


def _as_yyyymmdd(date) -> str:
    """Coerce str/Timestamp/datetime to YYYYMMDD."""
    if isinstance(date, str):
        return date[:8].replace("-", "")
    return pd.Timestamp(date).strftime("%Y%m%d")


class SentimentBiasStrategy:
    """Tilt an inner strategy's target weights by LLM research-title sentiment.

    Sentiment is a *bias*, not a signal, acting through two channels:

    1. **Relative tilt**: each held code's weight is scaled by
       ``(1 + max_tilt * centered_score)`` where centered_score is the
       code's weekly score minus the cross-sectional mean over ALL codes
       scored that week; matters only when several names are held.
    2. **Exposure tilt**: total exposure is scaled by
       ``min(1, 1 + max_tilt * centered_held_mean)`` so bearish sentiment
       moves weight to cash (never above 100%, no leverage). This keeps
       the bias effective for single-name strategies where channel 1
       cancels out under renormalization.

    Weights are renormalized to the resulting target exposure.
    ``max_tilt`` caps both distortions (default 0.15 => +-15%).

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
        date,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        date = _as_yyyymmdd(date)
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
        base_total = sum(weights.values())
        held = [(weights[c], raw[c][0] - raw[c][1]) for c in known]
        held_mean = sum(w * c for w, c in held) / sum(w for w, _ in held)
        target_total = base_total * min(1.0, 1.0 + self.max_tilt * held_mean)
        tilted_total = sum(tilted.values())
        if tilted_total <= 0:
            return weights
        scale = target_total / tilted_total
        return {code: w * scale for code, w in tilted.items()}
