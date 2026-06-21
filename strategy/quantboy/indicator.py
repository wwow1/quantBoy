"""
技术指标库模块

基于 numpy/pandas 实现常用技术指标，所有函数支持 pd.Series 和 np.array 输入
"""

from typing import Tuple, Union
import numpy as np
import pandas as pd


# 类型别名
ArrayLike = Union[pd.Series, np.ndarray]


def _ensure_series(data: ArrayLike, name: str = 'value') -> pd.Series:
    """
    确保输入数据为 pd.Series 格式
    
    Args:
        data: 输入数据，支持 pd.Series 或 np.ndarray
        name: 如果是数组，转换后的 Series 名称
        
    Returns:
        pd.Series 格式的数据
    """
    if isinstance(data, pd.Series):
        return data.copy()
    return pd.Series(data, name=name)


# ==================== 趋势类指标 ====================

def MA(series: ArrayLike, period: int = 20) -> pd.Series:
    """
    简单移动平均线 (Simple Moving Average)
    
    计算公式：MA = SUM(CLOSE, N) / N
    
    Args:
        series: 价格序列（通常为收盘价）
        period: 计算周期，默认20
        
    Returns:
        移动平均值序列，前 period-1 个值为 NaN
        
    Example:
        >>> ma20 = MA(df['close'], period=20)
    """
    s = _ensure_series(series)
    return s.rolling(window=period).mean()


def EMA(series: ArrayLike, period: int = 20) -> pd.Series:
    """
    指数移动平均线 (Exponential Moving Average)
    
    计算公式：EMA(t) = α * CLOSE(t) + (1-α) * EMA(t-1)
    其中 α = 2 / (period + 1)
    
    Args:
        series: 价格序列（通常为收盘价）
        period: 计算周期，默认20
        
    Returns:
        指数移动平均值序列
        
    Example:
        >>> ema12 = EMA(df['close'], period=12)
    """
    s = _ensure_series(series)
    return s.ewm(span=period, adjust=False).mean()


def MACD(
    series: ArrayLike,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD 指标 (Moving Average Convergence Divergence)
    
    计算公式：
    - DIF = EMA(CLOSE, fast) - EMA(CLOSE, slow)
    - DEA = EMA(DIF, signal)
    - MACD柱 = (DIF - DEA) * 2
    
    Args:
        series: 价格序列（通常为收盘价）
        fast: 快线周期，默认12
        slow: 慢线周期，默认26
        signal: 信号线周期，默认9
        
    Returns:
        (dif, dea, macd_hist) 元组
        - dif: 快慢线差值
        - dea: 信号线
        - macd_hist: MACD柱状图值
        
    Example:
        >>> dif, dea, macd_hist = MACD(df['close'])
    """
    s = _ensure_series(series)
    
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = (dif - dea) * 2
    
    return dif, dea, macd_hist


def BOLL(
    series: ArrayLike,
    period: int = 20,
    std_dev: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    布林带 (Bollinger Bands)
    
    计算公式：
    - 中轨 = MA(CLOSE, N)
    - 上轨 = 中轨 + K * STD(CLOSE, N)
    - 下轨 = 中轨 - K * STD(CLOSE, N)
    
    Args:
        series: 价格序列（通常为收盘价）
        period: 计算周期，默认20
        std_dev: 标准差倍数，默认2
        
    Returns:
        (upper, middle, lower) 元组
        - upper: 上轨
        - middle: 中轨
        - lower: 下轨
        
    Example:
        >>> upper, middle, lower = BOLL(df['close'])
    """
    s = _ensure_series(series)
    
    middle = s.rolling(window=period).mean()
    std = s.rolling(window=period).std()
    
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    
    return upper, middle, lower


# ==================== 震荡类指标 ====================

def RSI(series: ArrayLike, period: int = 14) -> pd.Series:
    """
    相对强弱指标 (Relative Strength Index)
    
    计算公式：
    RSI = 100 * EMA(UP, N) / (EMA(UP, N) + EMA(DOWN, N))
    其中 UP = max(CLOSE - CLOSE(-1), 0)
         DOWN = max(CLOSE(-1) - CLOSE, 0)
    
    Args:
        series: 价格序列（通常为收盘价）
        period: 计算周期，默认14
        
    Returns:
        RSI 值序列，范围 0-100
        
    Example:
        >>> rsi = RSI(df['close'], period=14)
    """
    s = _ensure_series(series)
    
    delta = s.diff()
    
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def KDJ(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    n: int = 9,
    m1: int = 3,
    m2: int = 3
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    KDJ 随机指标 (Stochastic Oscillator)
    
    计算公式：
    - RSV = (CLOSE - LLV(LOW, N)) / (HHV(HIGH, N) - LLV(LOW, N)) * 100
    - K = SMA(RSV, M1)
    - D = SMA(K, M2)
    - J = 3 * K - 2 * D
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        n: RSV 计算周期，默认9
        m1: K 平滑周期，默认3
        m2: D 平滑周期，默认3
        
    Returns:
        (K, D, J) 元组
        - K: 快速随机指标
        - D: 慢速随机指标
        - J: J 值
        
    Example:
        >>> k, d, j = KDJ(df['high'], df['low'], df['close'])
    """
    h = _ensure_series(high)
    l = _ensure_series(low)
    c = _ensure_series(close)
    
    # 计算 N 日内最高最低价
    hh = h.rolling(window=n).max()  # 最高价的最高值
    ll = l.rolling(window=n).min()  # 最低价的最低值
    
    # 计算 RSV
    rsv = (c - ll) / (hh - ll).replace(0, np.nan) * 100
    
    # 计算 K、D、J
    # 使用 SMA 平滑（指数移动平均的变体）
    k = rsv.ewm(alpha=1/m1, adjust=False).mean()
    d = k.ewm(alpha=1/m2, adjust=False).mean()
    j = 3 * k - 2 * d
    
    return k, d, j


def WR(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    period: int = 14
) -> pd.Series:
    """
    威廉指标 (Williams %R)
    
    计算公式：
    WR = (HHV(HIGH, N) - CLOSE) / (HHV(HIGH, N) - LLV(LOW, N)) * -100
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 计算周期，默认14
        
    Returns:
        威廉指标值序列，范围 -100 到 0
        
    Note:
        - WR > -20: 超买区间
        - WR < -80: 超卖区间
        
    Example:
        >>> wr = WR(df['high'], df['low'], df['close'])
    """
    h = _ensure_series(high)
    l = _ensure_series(low)
    c = _ensure_series(close)
    
    hh = h.rolling(window=period).max()
    ll = l.rolling(window=period).min()
    
    wr = (hh - c) / (hh - ll).replace(0, np.nan) * -100
    
    return wr


# ==================== 量能类指标 ====================

def OBV(close: ArrayLike, volume: ArrayLike) -> pd.Series:
    """
    能量潮指标 (On-Balance Volume)
    
    计算公式：
    - 如果 CLOSE > CLOSE(-1)，则 OBV = OBV(-1) + VOLUME
    - 如果 CLOSE < CLOSE(-1)，则 OBV = OBV(-1) - VOLUME
    - 如果 CLOSE = CLOSE(-1)，则 OBV = OBV(-1)
    
    Args:
        close: 收盘价序列
        volume: 成交量序列
        
    Returns:
        OBV 值序列
        
    Example:
        >>> obv = OBV(df['close'], df['volume'])
    """
    c = _ensure_series(close)
    v = _ensure_series(volume)
    
    # 计算价格变化方向
    direction = np.sign(c.diff())
    
    # OBV = 累计的带符号成交量
    obv = (direction * v).fillna(0).cumsum()
    
    return obv


def VWAP(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    volume: ArrayLike
) -> pd.Series:
    """
    成交量加权平均价 (Volume Weighted Average Price)
    
    计算公式：
    VWAP = SUM(典型价格 * 成交量) / SUM(成交量)
    其中 典型价格 = (HIGH + LOW + CLOSE) / 3
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        volume: 成交量序列
        
    Returns:
        VWAP 值序列
        
    Example:
        >>> vwap = VWAP(df['high'], df['low'], df['close'], df['volume'])
    """
    h = _ensure_series(high)
    l = _ensure_series(low)
    c = _ensure_series(close)
    v = _ensure_series(volume)
    
    # 典型价格
    tp = (h + l + c) / 3
    
    # VWAP = 累计(典型价格 * 成交量) / 累计成交量
    vwap = (tp * v).cumsum() / v.cumsum().replace(0, np.nan)
    
    return vwap


# ==================== 波动类指标 ====================

def ATR(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    period: int = 14
) -> pd.Series:
    """
    平均真实波幅 (Average True Range)
    
    计算公式：
    TR = MAX(HIGH - LOW, ABS(HIGH - CLOSE(-1)), ABS(LOW - CLOSE(-1)))
    ATR = EMA(TR, N)
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 计算周期，默认14
        
    Returns:
        ATR 值序列
        
    Example:
        >>> atr = ATR(df['high'], df['low'], df['close'])
    """
    h = _ensure_series(high)
    l = _ensure_series(low)
    c = _ensure_series(close)
    
    prev_close = c.shift(1)
    
    # 计算真实波幅的三个组成部分
    tr1 = h - l
    tr2 = (h - prev_close).abs()
    tr3 = (l - prev_close).abs()
    
    # 真实波幅 = 三者最大值
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # ATR = 真实波幅的移动平均
    atr = tr.ewm(span=period, adjust=False).mean()
    
    return atr


def STDDEV(series: ArrayLike, period: int = 20) -> pd.Series:
    """
    标准差 (Standard Deviation)
    
    计算公式：
    STDDEV = SQRT(SUM((CLOSE - MA)^2, N) / N)
    
    Args:
        series: 价格序列
        period: 计算周期，默认20
        
    Returns:
        标准差序列，前 period-1 个值为 NaN
        
    Example:
        >>> std = STDDEV(df['close'], period=20)
    """
    s = _ensure_series(series)
    return s.rolling(window=period).std()


# ==================== 其他辅助指标 ====================

def SMA(series: ArrayLike, period: int = 20, weight: float = 1.0) -> pd.Series:
    """
    加权移动平均 (Weighted Moving Average)
    
    通达信风格的 SMA 函数
    SMA(X, N, M) = (X * M + SMA' * (N - M)) / N
    
    Args:
        series: 价格序列
        period: 计算周期，默认20
        weight: 权重，默认1
        
    Returns:
        加权移动平均序列
        
    Example:
        >>> sma = SMA(df['close'], period=20, weight=1)
    """
    s = _ensure_series(series)
    return s.ewm(alpha=weight/period, adjust=False).mean()


def CROSS(series1: ArrayLike, series2: ArrayLike) -> pd.Series:
    """
    判断穿越信号
    
    当 series1 从下向上穿过 series2 时返回 True
    
    Args:
        series1: 序列1
        series2: 序列2
        
    Returns:
        布尔序列，穿越时为 True
        
    Example:
        >>> golden_cross = CROSS(ma5, ma20)  # 金叉信号
    """
    s1 = _ensure_series(series1)
    s2 = _ensure_series(series2)
    
    # 当前 s1 > s2 且 前一个 s1 <= s2
    cross = (s1 > s2) & (s1.shift(1) <= s2.shift(1))
    
    return cross


def CROSSDOWN(series1: ArrayLike, series2: ArrayLike) -> pd.Series:
    """
    判断下穿信号
    
    当 series1 从上向下穿过 series2 时返回 True
    
    Args:
        series1: 序列1
        series2: 序列2
        
    Returns:
        布尔序列，下穿时为 True
        
    Example:
        >>> death_cross = CROSSDOWN(ma5, ma20)  # 死叉信号
    """
    s1 = _ensure_series(series1)
    s2 = _ensure_series(series2)
    
    # 当前 s1 < s2 且 前一个 s1 >= s2
    cross = (s1 < s2) & (s1.shift(1) >= s2.shift(1))
    
    return cross


def REF(series: ArrayLike, n: int = 1) -> pd.Series:
    """
    获取 N 周期前的数据
    
    Args:
        series: 数据序列
        n: 向前偏移周期数，默认1
        
    Returns:
        偏移后的序列
        
    Example:
        >>> prev_close = REF(df['close'], 1)  # 昨日收盘价
    """
    s = _ensure_series(series)
    return s.shift(n)


def HHV(series: ArrayLike, period: int = 20) -> pd.Series:
    """
    N 周期内最高值 (Highest High Value)
    
    Args:
        series: 数据序列
        period: 计算周期，默认20
        
    Returns:
        N 周期内最高值序列
        
    Example:
        >>> high_20 = HHV(df['high'], 20)
    """
    s = _ensure_series(series)
    return s.rolling(window=period).max()


def LLV(series: ArrayLike, period: int = 20) -> pd.Series:
    """
    N 周期内最低值 (Lowest Low Value)
    
    Args:
        series: 数据序列
        period: 计算周期，默认20
        
    Returns:
        N 周期内最低值序列
        
    Example:
        >>> low_20 = LLV(df['low'], 20)
    """
    s = _ensure_series(series)
    return s.rolling(window=period).min()
