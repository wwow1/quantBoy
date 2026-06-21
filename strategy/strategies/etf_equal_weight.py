from typing import Dict, List

import pandas as pd


class EqualWeightStrategy:
    """Equal-weight all tradable symbols on each rebalance date."""

    name = "ETF等权月度再平衡"

    def target_weights(
        self,
        date: pd.Timestamp,
        history: Dict[str, pd.DataFrame],
        tradable_codes: List[str],
    ) -> Dict[str, float]:
        if not tradable_codes:
            return {}
        weight = 1.0 / len(tradable_codes)
        return {code: weight for code in tradable_codes}
