"""特徴量エンジニアリングモジュール

機械学習モデル用の特徴量を生成する
"""

import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """特徴量エンジニアリングクラス"""

    def __init__(self):
        """初期化"""
        self.feature_columns = []
        logger.info("特徴量エンジニアリング初期化")

    def create_all_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        全ての特徴量を生成

        Args:
            df: OHLCVデータ（技術指標計算済み）

        Returns:
            特徴量追加済みDataFrame
        """
        logger.info(f"特徴量生成開始: {len(df)}行")

        df = df.copy()

        # 1. 価格ベースの特徴量
        df = self._add_price_features(df)

        # 2. ボラティリティ特徴量
        df = self._add_volatility_features(df)

        # 3. トレンド特徴量
        df = self._add_trend_features(df)

        # 4. モメンタム特徴量
        df = self._add_momentum_features(df)

        # 5. 出来高特徴量
        df = self._add_volume_features(df)

        # 6. 時系列特徴量
        df = self._add_temporal_features(df)

        # 7. ラグ特徴量
        df = self._add_lag_features(df)

        # 8. 統計特徴量
        df = self._add_statistical_features(df)

        # NaN除去（最初の期間は計算できない）
        df = df.dropna()

        logger.info(f"特徴量生成完了: {len(df)}行, {len(df.columns)}列")
        self.feature_columns = [col for col in df.columns if col not in ['timestamp', 'open', 'high', 'low', 'close', 'volume']]

        return df

    def _add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """価格ベースの特徴量"""

        # 価格変化率（リターン）
        df['return_1'] = df['close'].pct_change(1)
        df['return_5'] = df['close'].pct_change(5)
        df['return_10'] = df['close'].pct_change(10)
        df['return_20'] = df['close'].pct_change(20)

        # 対数リターン
        df['log_return'] = np.log(df['close'] / df['close'].shift(1))

        # 高値・安値からの価格位置
        df['high_low_ratio'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-10)

        # 終値と始値の差
        df['close_open_ratio'] = df['close'] / df['open']

        # 上下ヒゲの長さ
        df['upper_shadow'] = (df['high'] - df[['open', 'close']].max(axis=1)) / (df['high'] - df['low'] + 1e-10)
        df['lower_shadow'] = (df[['open', 'close']].min(axis=1) - df['low']) / (df['high'] - df['low'] + 1e-10)

        # ローソク実体の長さ
        df['body_size'] = abs(df['close'] - df['open']) / df['open']

        return df

    def _add_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """ボラティリティ特徴量"""

        # リターンの標準偏差（ボラティリティ）
        df['volatility_5'] = df['return_1'].rolling(window=5).std()
        df['volatility_10'] = df['return_1'].rolling(window=10).std()
        df['volatility_20'] = df['return_1'].rolling(window=20).std()

        # 高値-安値の範囲
        df['hl_range'] = (df['high'] - df['low']) / df['close']
        df['hl_range_ma5'] = df['hl_range'].rolling(window=5).mean()

        # Parkinson's Volatility（高値・安値を使ったボラティリティ推定）
        df['parkinson_vol'] = np.sqrt(
            (np.log(df['high'] / df['low']) ** 2) / (4 * np.log(2))
        )

        # Garman-Klass Volatility
        df['gk_vol'] = np.sqrt(
            0.5 * (np.log(df['high'] / df['low']) ** 2) -
            (2 * np.log(2) - 1) * (np.log(df['close'] / df['open']) ** 2)
        )

        # ATR正規化（ボラティリティ正規化）
        if 'atr' in df.columns:
            df['atr_pct'] = df['atr'] / df['close']

        # ボラティリティレジーム（高/低）
        if 'volatility_20' in df.columns:
            df['vol_regime'] = (df['volatility_20'] > df['volatility_20'].rolling(window=50).mean()).astype(int)

        return df

    def _add_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """トレンド特徴量"""

        # 移動平均からの乖離率
        if 'sma_20' in df.columns:
            df['sma20_distance'] = (df['close'] - df['sma_20']) / df['sma_20']
            df['sma20_crossover'] = ((df['close'] > df['sma_20']).astype(int) -
                                     (df['close'].shift(1) > df['sma_20'].shift(1)).astype(int))

        if 'sma_50' in df.columns:
            df['sma50_distance'] = (df['close'] - df['sma_50']) / df['sma_50']

        if 'ema_12' in df.columns and 'ema_26' in df.columns:
            df['ema_diff'] = (df['ema_12'] - df['ema_26']) / df['close']

        # 価格が上昇トレンドかどうか
        df['uptrend_5'] = (df['close'] > df['close'].shift(5)).astype(int)
        df['uptrend_10'] = (df['close'] > df['close'].shift(10)).astype(int)
        df['uptrend_20'] = (df['close'] > df['close'].shift(20)).astype(int)

        # 連続上昇/下降日数
        df['price_up'] = (df['close'] > df['close'].shift(1)).astype(int)
        df['consecutive_up'] = df['price_up'].groupby((df['price_up'] != df['price_up'].shift()).cumsum()).cumsum()

        # ADXベースのトレンド強度
        if 'adx' in df.columns:
            df['strong_trend'] = (df['adx'] > 25).astype(int)

        return df

    def _add_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """モメンタム特徴量"""

        # RSIベース
        if 'rsi' in df.columns:
            df['rsi_overbought'] = (df['rsi'] > 70).astype(int)
            df['rsi_oversold'] = (df['rsi'] < 30).astype(int)
            df['rsi_neutral'] = ((df['rsi'] >= 40) & (df['rsi'] <= 60)).astype(int)
            df['rsi_change'] = df['rsi'].diff()

        # Stochasticベース
        if 'stoch_k' in df.columns and 'stoch_d' in df.columns:
            df['stoch_crossover'] = ((df['stoch_k'] > df['stoch_d']).astype(int) -
                                     (df['stoch_k'].shift(1) > df['stoch_d'].shift(1)).astype(int))

        # MACDベース
        if 'macd' in df.columns and 'macd_signal' in df.columns:
            df['macd_crossover'] = ((df['macd'] > df['macd_signal']).astype(int) -
                                    (df['macd'].shift(1) > df['macd_signal'].shift(1)).astype(int))
            df['macd_histogram'] = df['macd'] - df['macd_signal']
            df['macd_histogram_change'] = df['macd_histogram'].diff()

        # CCIベース
        if 'cci' in df.columns:
            df['cci_overbought'] = (df['cci'] > 100).astype(int)
            df['cci_oversold'] = (df['cci'] < -100).astype(int)

        # ROC（Rate of Change）
        df['roc_5'] = ((df['close'] - df['close'].shift(5)) / df['close'].shift(5)) * 100
        df['roc_10'] = ((df['close'] - df['close'].shift(10)) / df['close'].shift(10)) * 100

        return df

    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """出来高特徴量"""

        # 出来高変化率
        df['volume_change'] = df['volume'].pct_change()
        df['volume_ma5'] = df['volume'].rolling(window=5).mean()
        df['volume_ma20'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / (df['volume_ma20'] + 1e-10)

        # 出来高急増フラグ
        df['volume_spike'] = (df['volume'] > df['volume_ma20'] * 2).astype(int)

        # OBVベース
        if 'obv' in df.columns:
            df['obv_change'] = df['obv'].pct_change()
            df['obv_ma5'] = df['obv'].rolling(window=5).mean()
            df['obv_trend'] = (df['obv'] > df['obv_ma5']).astype(int)

        # VWAP距離
        if 'vwap' in df.columns:
            df['vwap_distance'] = (df['close'] - df['vwap']) / df['vwap']

        # 価格×出来高（取引代金）
        df['turnover'] = df['close'] * df['volume']
        df['turnover_ma5'] = df['turnover'].rolling(window=5).mean()

        return df

    def _add_temporal_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """時系列特徴量（時間・曜日など）"""

        # timestampから日時情報を抽出
        if 'timestamp' in df.columns:
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
            df['hour'] = df['datetime'].dt.hour
            df['day_of_week'] = df['datetime'].dt.dayofweek
            df['day_of_month'] = df['datetime'].dt.day
            df['month'] = df['datetime'].dt.month

            # 週末フラグ
            df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)

            # 取引時間帯（アジア・欧州・米国）
            df['is_asian_hours'] = ((df['hour'] >= 0) & (df['hour'] < 8)).astype(int)
            df['is_european_hours'] = ((df['hour'] >= 8) & (df['hour'] < 16)).astype(int)
            df['is_us_hours'] = ((df['hour'] >= 16) & (df['hour'] < 24)).astype(int)

            # datetimeカラムは削除（モデルに不要）
            df = df.drop('datetime', axis=1)

        return df

    def _add_lag_features(self, df: pd.DataFrame, lags: List[int] = [1, 2, 3, 5, 10]) -> pd.DataFrame:
        """ラグ特徴量（過去の値）"""

        # 終値のラグ
        for lag in lags:
            df[f'close_lag_{lag}'] = df['close'].shift(lag)

        # リターンのラグ
        for lag in lags[:3]:  # 1, 2, 3のみ
            if 'return_1' in df.columns:
                df[f'return_lag_{lag}'] = df['return_1'].shift(lag)

        # ボリュームのラグ
        for lag in lags[:3]:
            df[f'volume_lag_{lag}'] = df['volume'].shift(lag)

        return df

    def _add_statistical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """統計特徴量"""

        windows = [5, 10, 20]

        for window in windows:
            # 移動平均
            df[f'close_ma_{window}'] = df['close'].rolling(window=window).mean()

            # 移動標準偏差
            df[f'close_std_{window}'] = df['close'].rolling(window=window).std()

            # 最大値・最小値
            df[f'close_max_{window}'] = df['close'].rolling(window=window).max()
            df[f'close_min_{window}'] = df['close'].rolling(window=window).min()

            # 変動係数（CV）
            df[f'close_cv_{window}'] = df[f'close_std_{window}'] / (df[f'close_ma_{window}'] + 1e-10)

            # Zスコア
            df[f'close_zscore_{window}'] = (
                (df['close'] - df[f'close_ma_{window}']) / (df[f'close_std_{window}'] + 1e-10)
            )

        # 歪度・尖度（20期間のみ）
        df['skewness_20'] = df['return_1'].rolling(window=20).skew()
        df['kurtosis_20'] = df['return_1'].rolling(window=20).kurt()

        return df

    def create_target_variable(
        self,
        df: pd.DataFrame,
        prediction_horizon: int = 1,
        threshold: float = 0.001
    ) -> pd.DataFrame:
        """
        目的変数（ターゲット）を生成

        Args:
            df: 特徴量データ
            prediction_horizon: 何期先を予測するか（デフォルト: 1）
            threshold: 上昇/下降の閾値（デフォルト: 0.1%）

        Returns:
            ターゲット変数追加済みDataFrame
        """
        df = df.copy()

        # 将来リターン
        df['future_return'] = df['close'].shift(-prediction_horizon) / df['close'] - 1

        # 3クラス分類（上昇/横ばい/下降）
        df['target_direction'] = 0  # 横ばい
        df.loc[df['future_return'] > threshold, 'target_direction'] = 1  # 上昇
        df.loc[df['future_return'] < -threshold, 'target_direction'] = -1  # 下降

        # 2クラス分類（上昇/下降）
        df['target_binary'] = (df['future_return'] > 0).astype(int)

        # 回帰用ターゲット（リターンそのもの）
        df['target_return'] = df['future_return']

        # 未来データは削除（予測できない最後の行）
        df = df[:-prediction_horizon]

        logger.info(f"ターゲット変数生成完了: {len(df)}行")
        logger.info(f"  - 上昇: {(df['target_direction'] == 1).sum()}")
        logger.info(f"  - 横ばい: {(df['target_direction'] == 0).sum()}")
        logger.info(f"  - 下降: {(df['target_direction'] == -1).sum()}")

        return df

    def get_feature_columns(self) -> List[str]:
        """
        特徴量カラムのリストを取得

        Returns:
            特徴量カラム名のリスト
        """
        return self.feature_columns

    def select_important_features(
        self,
        df: pd.DataFrame,
        target_col: str = 'target_direction',
        top_n: int = 50
    ) -> List[str]:
        """
        重要な特徴量を選択（相関ベース）

        Args:
            df: 特徴量データ
            target_col: ターゲット変数名
            top_n: 上位何個選ぶか

        Returns:
            選択された特徴量のリスト
        """
        # ターゲットとの相関を計算
        correlations = df[self.feature_columns].corrwith(df[target_col]).abs()

        # 上位N個を選択
        top_features = correlations.nlargest(top_n).index.tolist()

        logger.info(f"特徴量選択完了: {len(top_features)}個")
        logger.info(f"  - Top 5: {top_features[:5]}")

        return top_features


# ヘルパー関数
def create_feature_engineer() -> FeatureEngineer:
    """
    特徴量エンジニアリングインスタンスを作成

    Returns:
        FeatureEngineerインスタンス
    """
    return FeatureEngineer()
