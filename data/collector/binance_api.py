"""Binance API接続モジュール"""

import ccxt
from typing import Dict, List
import pandas as pd

class BinanceDataCollector:
    def __init__(self, api_key: str = None, api_secret: str = None):
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
        })
    
    def fetch_ohlcv(self, symbol: str, timeframe: str = '1m', limit: int = 1000) -> pd.DataFrame:
        """ローソク足データ取得"""
        ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    
    def fetch_ticker(self, symbol: str) -> Dict:
        """現在価格取得"""
        return self.exchange.fetch_ticker(symbol)
