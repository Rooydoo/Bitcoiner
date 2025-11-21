"""共和分分析モジュール

ペアトレーディングのための共和分検定とスプレッド計算を行う。
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint, adfuller
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

logger = logging.getLogger(__name__)


@dataclass
class CointegrationResult:
    """共和分検定結果"""
    symbol1: str
    symbol2: str
    is_cointegrated: bool
    p_value: float
    test_statistic: float
    critical_values: Dict[str, float]
    hedge_ratio: float
    half_life: float


@dataclass
class SpreadSignal:
    """スプレッドシグナル"""
    spread: float
    z_score: float
    signal: str  # 'long_spread', 'short_spread', 'close', 'hold'
    hedge_ratio: float


class CointegrationAnalyzer:
    """共和分分析クラス"""

    def __init__(
        self,
        significance_level: float = 0.05,
        lookback_period: int = 252,
        z_score_entry: float = 2.0,
        z_score_exit: float = 0.5
    ):
        """
        初期化

        Args:
            significance_level: 有意水準（デフォルト5%）
            lookback_period: ルックバック期間（日数）
            z_score_entry: エントリーZスコア閾値
            z_score_exit: エグジットZスコア閾値
        """
        self.significance_level = significance_level
        self.lookback_period = lookback_period
        self.z_score_entry = z_score_entry
        self.z_score_exit = z_score_exit

        logger.info(
            f"CointegrationAnalyzer初期化: "
            f"significance={significance_level}, lookback={lookback_period}, "
            f"z_entry={z_score_entry}, z_exit={z_score_exit}"
        )

    def test_cointegration(
        self,
        price1: pd.Series,
        price2: pd.Series,
        symbol1: str = "asset1",
        symbol2: str = "asset2"
    ) -> CointegrationResult:
        """
        Engle-Granger共和分検定を実行

        Args:
            price1: 資産1の価格系列
            price2: 資産2の価格系列
            symbol1: 資産1のシンボル
            symbol2: 資産2のシンボル

        Returns:
            CointegrationResult: 検定結果
        """
        # 長さを揃える
        min_len = min(len(price1), len(price2))
        p1 = price1.iloc[-min_len:].values
        p2 = price2.iloc[-min_len:].values

        # Engle-Granger検定
        score, p_value, critical_values = coint(p1, p2)

        is_cointegrated = p_value < self.significance_level

        # ヘッジ比率の計算（OLS回帰）
        hedge_ratio = self._calculate_hedge_ratio(p1, p2)

        # 半減期の計算
        spread = p1 - hedge_ratio * p2
        half_life = self._calculate_half_life(spread)

        result = CointegrationResult(
            symbol1=symbol1,
            symbol2=symbol2,
            is_cointegrated=is_cointegrated,
            p_value=p_value,
            test_statistic=score,
            critical_values={
                '1%': critical_values[0],
                '5%': critical_values[1],
                '10%': critical_values[2]
            },
            hedge_ratio=hedge_ratio,
            half_life=half_life
        )

        logger.info(
            f"共和分検定: {symbol1}/{symbol2} - "
            f"p値={p_value:.4f}, 共和分={is_cointegrated}, "
            f"ヘッジ比率={hedge_ratio:.4f}, 半減期={half_life:.1f}日"
        )

        return result

    def _calculate_hedge_ratio(self, price1: np.ndarray, price2: np.ndarray) -> float:
        """
        OLS回帰でヘッジ比率を計算

        Args:
            price1: 資産1の価格
            price2: 資産2の価格

        Returns:
            ヘッジ比率（β係数）
        """
        X = add_constant(price2)
        model = OLS(price1, X).fit()
        return model.params[1]

    def _calculate_half_life(self, spread: np.ndarray) -> float:
        """
        平均回帰の半減期を計算（Ornstein-Uhlenbeck過程）

        Args:
            spread: スプレッド系列

        Returns:
            半減期（日数）
        """
        spread_lag = np.roll(spread, 1)[1:]
        spread_diff = np.diff(spread)

        X = add_constant(spread_lag)
        model = OLS(spread_diff, X).fit()

        # 平均回帰速度
        theta = -model.params[1]

        if theta <= 0:
            return float('inf')

        half_life = np.log(2) / theta
        return max(half_life, 1.0)

    def calculate_spread(
        self,
        price1: pd.Series,
        price2: pd.Series,
        hedge_ratio: float
    ) -> pd.Series:
        """
        スプレッドを計算

        Args:
            price1: 資産1の価格系列
            price2: 資産2の価格系列
            hedge_ratio: ヘッジ比率

        Returns:
            スプレッド系列
        """
        min_len = min(len(price1), len(price2))
        p1 = price1.iloc[-min_len:]
        p2 = price2.iloc[-min_len:]

        spread = p1.values - hedge_ratio * p2.values
        return pd.Series(spread, index=p1.index)

    def calculate_z_score(
        self,
        spread: pd.Series,
        window: int = None
    ) -> pd.Series:
        """
        スプレッドのZスコアを計算

        Args:
            spread: スプレッド系列
            window: 移動平均ウィンドウ（Noneの場合は全期間）

        Returns:
            Zスコア系列
        """
        if window is None:
            window = self.lookback_period

        mean = spread.rolling(window=window).mean()
        std = spread.rolling(window=window).std()

        z_score = (spread - mean) / std
        return z_score

    def generate_signal(
        self,
        price1: pd.Series,
        price2: pd.Series,
        hedge_ratio: float,
        window: int = None
    ) -> SpreadSignal:
        """
        トレーディングシグナルを生成

        Args:
            price1: 資産1の価格系列
            price2: 資産2の価格系列
            hedge_ratio: ヘッジ比率
            window: Zスコア計算ウィンドウ

        Returns:
            SpreadSignal: シグナル
        """
        spread = self.calculate_spread(price1, price2, hedge_ratio)
        z_score = self.calculate_z_score(spread, window)

        current_spread = spread.iloc[-1]
        current_z = z_score.iloc[-1]

        # シグナル判定
        if current_z > self.z_score_entry:
            signal = 'short_spread'  # スプレッドが高すぎる -> 資産1売り、資産2買い
        elif current_z < -self.z_score_entry:
            signal = 'long_spread'  # スプレッドが低すぎる -> 資産1買い、資産2売り
        elif abs(current_z) < self.z_score_exit:
            signal = 'close'  # 平均回帰 -> ポジションクローズ
        else:
            signal = 'hold'  # 維持

        return SpreadSignal(
            spread=current_spread,
            z_score=current_z,
            signal=signal,
            hedge_ratio=hedge_ratio
        )

    def find_cointegrated_pairs(
        self,
        price_data: Dict[str, pd.Series]
    ) -> List[CointegrationResult]:
        """
        全ペアの共和分検定を実行し、共和分関係にあるペアを返す

        Args:
            price_data: {シンボル: 価格系列}の辞書

        Returns:
            共和分関係にあるペアのリスト
        """
        symbols = list(price_data.keys())
        cointegrated_pairs = []

        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                sym1, sym2 = symbols[i], symbols[j]
                price1, price2 = price_data[sym1], price_data[sym2]

                try:
                    result = self.test_cointegration(price1, price2, sym1, sym2)

                    if result.is_cointegrated:
                        cointegrated_pairs.append(result)
                        logger.info(f"共和分ペア発見: {sym1}/{sym2}")

                except Exception as e:
                    logger.warning(f"共和分検定エラー: {sym1}/{sym2} - {e}")

        logger.info(f"共和分ペア数: {len(cointegrated_pairs)}/{len(symbols) * (len(symbols) - 1) // 2}")
        return cointegrated_pairs

    def test_stationarity(self, series: pd.Series) -> Tuple[bool, float]:
        """
        ADF検定で定常性を検定

        Args:
            series: 時系列データ

        Returns:
            (定常か, p値)
        """
        result = adfuller(series.dropna())
        p_value = result[1]
        is_stationary = p_value < self.significance_level
        return is_stationary, p_value


def create_cointegration_analyzer(
    significance_level: float = 0.05,
    lookback_period: int = 252,
    z_score_entry: float = 2.0,
    z_score_exit: float = 0.5
) -> CointegrationAnalyzer:
    """
    CointegrationAnalyzerを作成

    Args:
        significance_level: 有意水準
        lookback_period: ルックバック期間
        z_score_entry: エントリーZスコア
        z_score_exit: エグジットZスコア

    Returns:
        CointegrationAnalyzerインスタンス
    """
    return CointegrationAnalyzer(
        significance_level=significance_level,
        lookback_period=lookback_period,
        z_score_entry=z_score_entry,
        z_score_exit=z_score_exit
    )
