"""
Formal QuantBoy target-weight strategies.
"""

from .etf_equal_weight import EqualWeightStrategy
from .etf_momentum import MomentumRotationStrategy

__all__ = [
    "EqualWeightStrategy",
    "MomentumRotationStrategy",
]
