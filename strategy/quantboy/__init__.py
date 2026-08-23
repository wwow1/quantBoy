"""
QuantBoy strategy utilities for RQAlpha-based low-frequency research.

QuantBoy no longer ships a self-built backtest engine. RQAlpha is the only
execution/backtest engine on the main path; this package provides the adapter
that lets QuantBoy target-weight strategies run inside RQAlpha.
"""

__version__ = "0.2.0"
__author__ = "QuantBoy Team"

from .client import QuantBoyClient
from .rqalpha_adapter import (
    RQAlphaAdapterConfig,
    RQAlphaTargetWeightAdapter,
    from_rqalpha_order_book_id,
    to_rqalpha_order_book_id,
)
from strategies import (
    DualMovingAverageStrategy,
    EqualWeightStrategy,
    LowVolatilityStrategy,
    MeanReversionStrategy,
    MomentumRotationStrategy,
    MovingAverageTrendStrategy,
    RiskParityStrategy,
)

from . import indicator
from .indicator import (
    ATR,
    BOLL,
    CROSS,
    CROSSDOWN,
    EMA,
    HHV,
    KDJ,
    LLV,
    MA,
    MACD,
    OBV,
    REF,
    RSI,
    SMA,
    STDDEV,
    VWAP,
    WR,
)

__all__ = [
    "__version__",
    "QuantBoyClient",
    "RQAlphaAdapterConfig",
    "RQAlphaTargetWeightAdapter",
    "to_rqalpha_order_book_id",
    "from_rqalpha_order_book_id",
    "EqualWeightStrategy",
    "MomentumRotationStrategy",
    "MovingAverageTrendStrategy",
    "DualMovingAverageStrategy",
    "MeanReversionStrategy",
    "LowVolatilityStrategy",
    "RiskParityStrategy",
    "indicator",
    "MA",
    "EMA",
    "MACD",
    "BOLL",
    "RSI",
    "KDJ",
    "WR",
    "OBV",
    "VWAP",
    "ATR",
    "STDDEV",
    "SMA",
    "CROSS",
    "CROSSDOWN",
    "REF",
    "HHV",
    "LLV",
]
