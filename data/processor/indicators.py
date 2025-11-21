"""技術指標計算モジュール"""

import logging
import numpy as np
import pandas as pd
from typing import Tuple

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """技術指標計算クラス"""

    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """
        全ての技術指標を計算

        Args:
            df: OHLCVデータフレーム（open, high, low, close, volume）

        Returns:
            技術指標が追加されたデータフレーム
        """
        df = df.copy()

        # トレンド系
        df = TechnicalIndicators.add_sma(df)
        df = TechnicalIndicators.add_ema(df)
        df = TechnicalIndicators.add_macd(df)
        df = TechnicalIndicators.add_adx(df)

        # オシレーター系
        df = TechnicalIndicators.add_rsi(df)
        df = TechnicalIndicators.add_stochastic(df)
        df = TechnicalIndicators.add_cci(df)

        # ボラティリティ系
        df = TechnicalIndicators.add_bollinger_bands(df)
        df = TechnicalIndicators.add_atr(df)

        # 出来高系
        df = TechnicalIndicators.add_obv(df)
        df = TechnicalIndicators.add_vwap(df)

        logger.debug(f"技術指標計算完了: {len(df)}行")
        return df

    # ========== トレンド系 ==========

    @staticmethod
    def add_sma(df: pd.DataFrame, periods: list = [5, 25, 75]) -> pd.DataFrame:
        """
        単純移動平均（SMA）を追加

        Args:
            df: データフレーム
            periods: 期間リスト

        Returns:
            SMAが追加されたデータフレーム
        """
        for period in periods:
            df[f'sma_{period}'] = df['close'].rolling(window=period).mean()
        return df

    @staticmethod
    def add_ema(df: pd.DataFrame, periods: list = [12, 26]) -> pd.DataFrame:
        """
        指数移動平均（EMA）を追加

        Args:
            df: データフレーム
            periods: 期間リスト

        Returns:
            EMAが追加されたデータフレーム
        """
        for period in periods:
            df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
        return df

    @staticmethod
    def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """
        MACD（Moving Average Convergence Divergence）を追加

        Args:
            df: データフレーム
            fast: 短期EMA期間
            slow: 長期EMA期間
            signal: シグナル線期間

        Returns:
            MACDが追加されたデータフレーム
        """
        ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow, adjust=False).mean()

        df['macd'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd'].ewm(span=signal, adjust=False).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']

        return df

    @staticmethod
    def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        ADX（Average Directional Index）を追加

        Args:
            df: データフレーム
            period: 期間

        Returns:
            ADXが追加されたデータフレーム
        """
        # True Range
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

        # +DM, -DM
        high_diff = df['high'] - df['high'].shift()
        low_diff = df['low'].shift() - df['low']

        plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0)
        minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0)

        # ATR
        atr = tr.rolling(window=period).mean()

        # +DI, -DI
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)

        # DX
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)

        # ADX
        df['adx'] = dx.rolling(window=period).mean()

        return df

    # ========== オシレーター系 ==========

    @staticmethod
    def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        RSI（Relative Strength Index）を追加

        Args:
            df: データフレーム
            period: 期間

        Returns:
            RSIが追加されたデータフレーム
        """
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()

        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))

        return df

    @staticmethod
    def add_stochastic(df: pd.DataFrame, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> pd.DataFrame:
        """
        ストキャスティクスを追加

        Args:
            df: データフレーム
            period: 期間
            smooth_k: %Kスムージング
            smooth_d: %Dスムージング

        Returns:
            ストキャスティクスが追加されたデータフレーム
        """
        low_min = df['low'].rolling(window=period).min()
        high_max = df['high'].rolling(window=period).max()

        stoch_k_raw = 100 * (df['close'] - low_min) / (high_max - low_min)
        df['stoch_k'] = stoch_k_raw.rolling(window=smooth_k).mean()
        df['stoch_d'] = df['stoch_k'].rolling(window=smooth_d).mean()

        return df

    @staticmethod
    def add_cci(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """
        CCI（Commodity Channel Index）を追加

        Args:
            df: データフレーム
            period: 期間

        Returns:
            CCIが追加されたデータフレーム
        """
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        sma_tp = typical_price.rolling(window=period).mean()
        mad = typical_price.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean())

        df['cci'] = (typical_price - sma_tp) / (0.015 * mad)

        return df

    # ========== ボラティリティ系 ==========

    @staticmethod
    def add_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: int = 2) -> pd.DataFrame:
        """
        ボリンジャーバンドを追加

        Args:
            df: データフレーム
            period: 期間
            std_dev: 標準偏差の倍数

        Returns:
            ボリンジャーバンドが追加されたデータフレーム
        """
        sma = df['close'].rolling(window=period).mean()
        std = df['close'].rolling(window=period).std()

        df['bb_middle'] = sma
        df['bb_upper'] = sma + (std * std_dev)
        df['bb_lower'] = sma - (std * std_dev)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']

        return df

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        ATR（Average True Range）を追加

        Args:
            df: データフレーム
            period: 期間

        Returns:
            ATRが追加されたデータフレーム
        """
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())

        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = true_range.rolling(window=period).mean()

        return df

    # ========== 出来高系 ==========

    @staticmethod
    def add_obv(df: pd.DataFrame) -> pd.DataFrame:
        """
        OBV（On-Balance Volume）を追加

        Args:
            df: データフレーム

        Returns:
            OBVが追加されたデータフレーム
        """
        obv = [0]
        for i in range(1, len(df)):
            if df['close'].iloc[i] > df['close'].iloc[i-1]:
                obv.append(obv[-1] + df['volume'].iloc[i])
            elif df['close'].iloc[i] < df['close'].iloc[i-1]:
                obv.append(obv[-1] - df['volume'].iloc[i])
            else:
                obv.append(obv[-1])

        df['obv'] = obv
        return df

    @staticmethod
    def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
        """
        VWAP（Volume Weighted Average Price）を追加

        Args:
            df: データフレーム

        Returns:
            VWAPが追加されたデータフレーム
        """
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

        return df

    # ========== 価格変動率 ==========

    @staticmethod
    def add_price_changes(df: pd.DataFrame, periods: list = [1, 4, 24]) -> pd.DataFrame:
        """
        価格変動率を追加

        Args:
            df: データフレーム
            periods: 期間リスト（時間単位）

        Returns:
            価格変動率が追加されたデータフレーム
        """
        for period in periods:
            df[f'price_change_{period}h'] = df['close'].pct_change(periods=period) * 100

        return df

    @staticmethod
    def add_volume_changes(df: pd.DataFrame, periods: list = [1, 4, 24]) -> pd.DataFrame:
        """
        出来高変動率を追加

        Args:
            df: データフレーム
            periods: 期間リスト

        Returns:
            出来高変動率が追加されたデータフレーム
        """
        for period in periods:
            df[f'volume_change_{period}h'] = df['volume'].pct_change(periods=period) * 100

        return df


# ユーティリティ関数
def calculate_indicators(df: pd.DataFrame, indicators: list = None) -> pd.DataFrame:
    """
    指定された技術指標を計算

    Args:
        df: OHLCVデータフレーム
        indicators: 計算する指標のリスト（Noneの場合は全て）

    Returns:
        技術指標が追加されたデータフレーム
    """
    ti = TechnicalIndicators()

    if indicators is None:
        # 全指標を計算
        return ti.calculate_all(df)
    else:
        # 指定された指標のみ計算
        result = df.copy()
        for indicator in indicators:
            method_name = f'add_{indicator}'
            if hasattr(ti, method_name):
                method = getattr(ti, method_name)
                result = method(result)
            else:
                logger.warning(f"未知の指標: {indicator}")
        return result
