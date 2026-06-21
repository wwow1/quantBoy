"""
Go API 数据客户端模块

与 Go 后端 API 交互，获取股票数据
"""

from typing import Optional, Dict, List, Any
import pandas as pd
import requests


class QuantBoyClient:
    """
    Go API 数据客户端
    
    用于与 QuantBoy Go 后端 API 交互，获取股票列表、行情数据等。
    
    Attributes:
        base_url: API 服务器地址
        timeout: 请求超时时间（秒）
        
    Example:
        >>> client = QuantBoyClient('http://localhost:8080')
        >>> stocks = client.get_stocks()
        >>> bars = client.get_daily_bars('000001', '2024-01-01', '2024-03-01')
    """
    
    def __init__(self, base_url: str = 'http://localhost:8080', timeout: int = 30):
        """
        初始化客户端
        
        Args:
            base_url: API 服务器地址，默认 http://localhost:8080
            timeout: 请求超时时间（秒），默认30秒
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._session = requests.Session()
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        发送 HTTP 请求
        
        Args:
            method: 请求方法 (GET/POST/etc)
            endpoint: API 端点
            params: 查询参数
            data: 请求体数据
            
        Returns:
            API 响应数据
            
        Raises:
            requests.RequestException: 请求失败时抛出
            ValueError: API 返回错误时抛出
        """
        url = f"{self.base_url}{endpoint}"
        
        response = self._session.request(
            method=method,
            url=url,
            params=params,
            json=data,
            timeout=self.timeout
        )
        
        response.raise_for_status()
        
        result = response.json()
        
        # 检查 API 错误响应（统一格式：{"code": 0, "message": "success", "data": ...}）
        if isinstance(result, dict):
            if result.get('error'):
                raise ValueError(f"API 错误: {result.get('error')}")
            # Go 端返回 code != 0 表示错误
            if 'code' in result and result.get('code') != 0:
                raise ValueError(f"API 错误: {result.get('message', 'Unknown error')}")
        
        return result
    
    def health_check(self) -> bool:
        """
        健康检查
        
        检查 API 服务器是否正常运行
        
        Returns:
            True 表示服务正常，False 表示服务异常
            
        Example:
            >>> if client.health_check():
            ...     print("API 服务正常")
        """
        try:
            self._request('GET', '/api/health')
            return True
        except Exception:
            return False
    
    def get_stocks(self) -> pd.DataFrame:
        """
        获取股票列表
        
        从 API 获取所有股票的基本信息列表
        
        Returns:
            股票列表 DataFrame，包含以下列：
            - code: 股票代码
            - name: 股票名称
            - market: 市场（SH/SZ）
            - list_date: 上市日期
            
        Example:
            >>> stocks = client.get_stocks()
            >>> print(stocks.head())
        """
        result = self._request('GET', '/api/stocks')
        
        # 处理返回数据
        if isinstance(result, dict) and 'data' in result:
            data = result['data']
        elif isinstance(result, list):
            data = result
        else:
            data = []
        
        if not data:
            return pd.DataFrame(columns=['code', 'name', 'market', 'list_date'])
        
        df = pd.DataFrame(data)
        return df
    
    def get_stock_info(self, code: str) -> Dict[str, Any]:
        """
        获取单只股票详细信息
        
        Args:
            code: 股票代码
            
        Returns:
            股票详细信息字典，包含：
            - code: 股票代码
            - name: 股票名称
            - market: 市场
            - industry: 行业
            - list_date: 上市日期
            - 以及其他详细信息
            
        Example:
            >>> info = client.get_stock_info('000001')
            >>> print(info['name'])
        """
        result = self._request('GET', f'/api/stocks/{code}/info')
        
        if isinstance(result, dict) and 'data' in result:
            return result['data']
        return result
    
    def get_daily_bars(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        获取日线数据
        
        从 API 获取指定股票的日 K 线数据
        
        Args:
            code: 股票代码
            start_date: 开始日期，格式 'YYYY-MM-DD'，默认获取全部数据
            end_date: 结束日期，格式 'YYYY-MM-DD'，默认为当前日期
            
        Returns:
            日线数据 DataFrame，包含以下列：
            - date/datetime: 日期
            - open: 开盘价
            - high: 最高价
            - low: 最低价
            - close: 收盘价
            - volume: 成交量
            - amount: 成交额（如果有）
            
        Example:
            >>> bars = client.get_daily_bars('000001', '2024-01-01', '2024-03-01')
            >>> print(bars.head())
        """
        params = {}
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date
        
        result = self._request('GET', f'/api/stocks/{code}/daily', params=params)
        
        # 处理返回数据
        if isinstance(result, dict) and 'data' in result:
            data = result['data']
        elif isinstance(result, list):
            data = result
        else:
            data = []
        
        if not data:
            return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume'])
        
        df = pd.DataFrame(data)
        
        # 处理日期列
        for date_col in ['date', 'datetime', 'trade_date']:
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col])
                df.set_index(date_col, inplace=True)
                break
        
        # 确保列名统一（小写）
        df.columns = df.columns.str.lower()
        
        # 按日期排序
        df.sort_index(inplace=True)
        
        return df
    
    def get_minute_bars(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        freq: str = '1m'
    ) -> pd.DataFrame:
        """
        获取分钟线数据
        
        从 API 获取指定股票的分钟 K 线数据
        
        Args:
            code: 股票代码
            start_date: 开始日期，格式 'YYYY-MM-DD'
            end_date: 结束日期，格式 'YYYY-MM-DD'
            freq: 频率，'1m'/'5m'/'15m'/'30m'/'60m'
            
        Returns:
            分钟线数据 DataFrame
            
        Example:
            >>> bars = client.get_minute_bars('000001', '2024-03-01', freq='5m')
        """
        params = {'freq': freq}
        if start_date:
            params['start_time'] = start_date if len(start_date) > 10 else f'{start_date} 00:00:00'
        if end_date:
            params['end_time'] = end_date if len(end_date) > 10 else f'{end_date} 23:59:59'

        result = self._request('GET', f'/api/stocks/{code}/minute', params=params)

        if isinstance(result, dict) and 'data' in result:
            data = result['data']
        elif isinstance(result, list):
            data = result
        else:
            data = []

        if not data:
            return pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume'])

        df = pd.DataFrame(data)
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'])
            df.set_index('time', inplace=True)
        df.columns = df.columns.str.lower()
        df.sort_index(inplace=True)
        return df

    def get_etf_daily_bars(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        获取 ETF 日线数据

        Args:
            code: ETF 代码
            start_date: 开始日期，格式 'YYYY-MM-DD'
            end_date: 结束日期，格式 'YYYY-MM-DD'

        Returns:
            ETF 日线数据 DataFrame
        """
        params = {}
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date

        result = self._request('GET', f'/api/etfs/{code}/daily', params=params)

        if isinstance(result, dict) and 'data' in result:
            data = result['data']
        elif isinstance(result, list):
            data = result
        else:
            data = []

        if not data:
            return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume'])

        df = pd.DataFrame(data)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
        df.columns = df.columns.str.lower()
        df.sort_index(inplace=True)
        return df
    
    def search_stocks(self, keyword: str) -> pd.DataFrame:
        """
        搜索股票
        
        根据关键字搜索股票（代码或名称）
        
        注意：当前通过获取全部股票列表后在本地过滤实现，
        因为 Go 服务端尚未提供搜索接口。
        
        Args:
            keyword: 搜索关键字
            
        Returns:
            匹配的股票列表 DataFrame
            
        Example:
            >>> result = client.search_stocks('平安')
        """
        # Go 端没有搜索接口，通过获取全部股票后本地过滤
        stocks = self.get_stocks()
        if stocks.empty:
            return pd.DataFrame(columns=['code', 'name', 'market'])
        
        # 在代码和名称中搜索关键字
        mask = (
            stocks['code'].str.contains(keyword, case=False, na=False) |
            stocks['name'].str.contains(keyword, case=False, na=False)
        )
        return stocks[mask].reset_index(drop=True)
    
    def close(self) -> None:
        """
        关闭客户端连接
        
        释放网络资源
        """
        self._session.close()
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
        return False
    
    def __repr__(self) -> str:
        return f"QuantBoyClient(base_url='{self.base_url}')"
