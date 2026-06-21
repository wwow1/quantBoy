from typing import Dict, List

import pandas as pd


class MomentumRotationStrategy:
    """Rank symbols by trailing close-to-close momentum and hold the top names."""

    def __init__(self, lookback: int = 120, top_k: int = 1):
        self.lookback = lookback
        self.top_k = top_k
        self.name = f"ETF{lookback}日动量Top{top_k}"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        scores = {}
        for code in tradable_codes:
            close = history.get(code, pd.DataFrame()).get("close")
            if close is None:
                continue
            close = close.dropna()
            if len(close) <= self.lookback:
                continue
            scores[code] = close.iloc[-1] / close.iloc[-self.lookback - 1] - 1

        selected = [
            code for code, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][: self.top_k]
        if not selected:
            return {}

        weight = 1.0 / len(selected)
        return {code: weight for code in selected}
