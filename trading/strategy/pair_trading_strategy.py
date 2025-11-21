"""ペアトレーディング戦略

共和分を利用したペアトレーディング戦略を実装する。
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd
import numpy as np

from ml.models.cointegration_analyzer import (
    CointegrationAnalyzer,
    CointegrationResult,
    SpreadSignal,
    create_cointegration_analyzer
)

logger = logging.getLogger(__name__)


@dataclass
class PairPosition:
    """ペアポジション"""
    pair_id: str
    symbol1: str
    symbol2: str
    direction: str  # 'long_spread' or 'short_spread'
    hedge_ratio: float
    entry_spread: float
    entry_z_score: float
    entry_time: datetime
    size1: float  # 資産1のポジションサイズ
    size2: float  # 資産2のポジションサイズ
    entry_price1: float
    entry_price2: float
    unrealized_pnl: float = 0.0


@dataclass
class PairTradingConfig:
    """ペアトレーディング設定"""
    z_score_entry: float = 2.0
    z_score_exit: float = 0.5
    z_score_stop_loss: float = 4.0
    max_pairs: int = 3
    position_size_pct: float = 0.1  # 資金の10%
    lookback_period: int = 252
    rebalance_interval: int = 24  # 時間
    min_half_life: float = 5.0  # 最小半減期（日）
    max_half_life: float = 60.0  # 最大半減期（日）


class PairTradingStrategy:
    """ペアトレーディング戦略クラス"""

    def __init__(self, config: PairTradingConfig = None):
        """
        初期化

        Args:
            config: 戦略設定
        """
        self.config = config or PairTradingConfig()
        self.analyzer = create_cointegration_analyzer(
            z_score_entry=self.config.z_score_entry,
            z_score_exit=self.config.z_score_exit,
            lookback_period=self.config.lookback_period
        )
        self.positions: Dict[str, PairPosition] = {}
        self.cointegrated_pairs: List[CointegrationResult] = []
        self.last_rebalance: Optional[datetime] = None

        logger.info(f"PairTradingStrategy初期化: {self.config}")

    def update_cointegration(self, price_data: Dict[str, pd.Series]) -> List[CointegrationResult]:
        """
        共和分関係を更新

        Args:
            price_data: {シンボル: 価格系列}の辞書

        Returns:
            共和分ペアのリスト
        """
        self.cointegrated_pairs = self.analyzer.find_cointegrated_pairs(price_data)

        # 半減期でフィルタリング
        valid_pairs = [
            p for p in self.cointegrated_pairs
            if self.config.min_half_life <= p.half_life <= self.config.max_half_life
        ]

        # p値でソート（低い方が良い）
        valid_pairs.sort(key=lambda x: x.p_value)

        self.cointegrated_pairs = valid_pairs[:self.config.max_pairs]

        logger.info(f"有効な共和分ペア: {len(self.cointegrated_pairs)}")
        for pair in self.cointegrated_pairs:
            logger.info(f"  {pair.symbol1}/{pair.symbol2}: p={pair.p_value:.4f}, half_life={pair.half_life:.1f}")

        return self.cointegrated_pairs

    def generate_signals(
        self,
        price_data: Dict[str, pd.Series]
    ) -> Dict[str, SpreadSignal]:
        """
        全ペアのシグナルを生成

        Args:
            price_data: {シンボル: 価格系列}の辞書

        Returns:
            {ペアID: シグナル}の辞書
        """
        signals = {}

        for pair in self.cointegrated_pairs:
            pair_id = f"{pair.symbol1}_{pair.symbol2}"

            if pair.symbol1 not in price_data or pair.symbol2 not in price_data:
                continue

            signal = self.analyzer.generate_signal(
                price_data[pair.symbol1],
                price_data[pair.symbol2],
                pair.hedge_ratio
            )

            signals[pair_id] = signal

            logger.debug(
                f"シグナル {pair_id}: z={signal.z_score:.2f}, signal={signal.signal}"
            )

        return signals

    def calculate_position_sizes(
        self,
        pair: CointegrationResult,
        capital: float,
        price1: float,
        price2: float
    ) -> Tuple[float, float]:
        """
        ポジションサイズを計算

        Args:
            pair: 共和分ペア情報
            capital: 利用可能資金
            price1: 資産1の現在価格
            price2: 資産2の現在価格

        Returns:
            (資産1のサイズ, 資産2のサイズ)
        """
        # 資金の一定割合を使用
        pair_capital = capital * self.config.position_size_pct

        # 資産1のサイズ
        size1 = pair_capital / price1

        # 資産2のサイズ（ヘッジ比率を考慮）
        size2 = size1 * pair.hedge_ratio * (price1 / price2)

        return size1, size2

    def should_enter(self, signal: SpreadSignal, pair_id: str) -> bool:
        """
        エントリー条件を確認

        Args:
            signal: シグナル
            pair_id: ペアID

        Returns:
            エントリーすべきか
        """
        # 既にポジションがある場合はエントリーしない
        if pair_id in self.positions:
            return False

        # シグナルがエントリーを示している場合
        return signal.signal in ['long_spread', 'short_spread']

    def should_exit(self, signal: SpreadSignal, position: PairPosition) -> Tuple[bool, str]:
        """
        エグジット条件を確認

        Args:
            signal: シグナル
            position: 現在のポジション

        Returns:
            (エグジットすべきか, 理由)
        """
        # 平均回帰でクローズ
        if signal.signal == 'close':
            return True, 'mean_reversion'

        # ストップロス
        if abs(signal.z_score) > self.config.z_score_stop_loss:
            return True, 'stop_loss'

        # 方向転換
        if position.direction == 'long_spread' and signal.signal == 'short_spread':
            return True, 'direction_change'
        if position.direction == 'short_spread' and signal.signal == 'long_spread':
            return True, 'direction_change'

        return False, ''

    def open_position(
        self,
        pair: CointegrationResult,
        signal: SpreadSignal,
        price1: float,
        price2: float,
        capital: float
    ) -> PairPosition:
        """
        ポジションをオープン

        Args:
            pair: 共和分ペア情報
            signal: シグナル
            price1: 資産1の現在価格
            price2: 資産2の現在価格
            capital: 利用可能資金

        Returns:
            オープンしたポジション
        """
        pair_id = f"{pair.symbol1}_{pair.symbol2}"
        size1, size2 = self.calculate_position_sizes(pair, capital, price1, price2)

        position = PairPosition(
            pair_id=pair_id,
            symbol1=pair.symbol1,
            symbol2=pair.symbol2,
            direction=signal.signal,
            hedge_ratio=signal.hedge_ratio,
            entry_spread=signal.spread,
            entry_z_score=signal.z_score,
            entry_time=datetime.now(),
            size1=size1,
            size2=size2,
            entry_price1=price1,
            entry_price2=price2
        )

        self.positions[pair_id] = position

        logger.info(
            f"ポジションオープン: {pair_id} {signal.signal} "
            f"z={signal.z_score:.2f} size1={size1:.6f} size2={size2:.6f}"
        )

        return position

    def close_position(
        self,
        pair_id: str,
        price1: float,
        price2: float,
        reason: str
    ) -> Tuple[PairPosition, float]:
        """
        ポジションをクローズ

        Args:
            pair_id: ペアID
            price1: 資産1の現在価格
            price2: 資産2の現在価格
            reason: クローズ理由

        Returns:
            (クローズしたポジション, 実現損益)
        """
        position = self.positions.pop(pair_id)

        # 損益計算
        if position.direction == 'long_spread':
            # 資産1ロング、資産2ショート
            pnl1 = position.size1 * (price1 - position.entry_price1)
            pnl2 = -position.size2 * (price2 - position.entry_price2)
        else:
            # 資産1ショート、資産2ロング
            pnl1 = -position.size1 * (price1 - position.entry_price1)
            pnl2 = position.size2 * (price2 - position.entry_price2)

        realized_pnl = pnl1 + pnl2

        logger.info(
            f"ポジションクローズ: {pair_id} reason={reason} "
            f"PnL={realized_pnl:.2f}円"
        )

        return position, realized_pnl

    def update_unrealized_pnl(
        self,
        price_data: Dict[str, float]
    ) -> float:
        """
        未実現損益を更新

        Args:
            price_data: {シンボル: 現在価格}の辞書

        Returns:
            総未実現損益
        """
        total_pnl = 0.0

        for pair_id, position in self.positions.items():
            price1 = price_data.get(position.symbol1, position.entry_price1)
            price2 = price_data.get(position.symbol2, position.entry_price2)

            if position.direction == 'long_spread':
                pnl1 = position.size1 * (price1 - position.entry_price1)
                pnl2 = -position.size2 * (price2 - position.entry_price2)
            else:
                pnl1 = -position.size1 * (price1 - position.entry_price1)
                pnl2 = position.size2 * (price2 - position.entry_price2)

            position.unrealized_pnl = pnl1 + pnl2
            total_pnl += position.unrealized_pnl

        return total_pnl

    def get_orders(
        self,
        signal: SpreadSignal,
        pair: CointegrationResult,
        price1: float,
        price2: float,
        capital: float
    ) -> List[Dict]:
        """
        実行すべき注文を生成

        Args:
            signal: シグナル
            pair: 共和分ペア情報
            price1: 資産1の価格
            price2: 資産2の価格
            capital: 利用可能資金

        Returns:
            注文リスト
        """
        orders = []
        pair_id = f"{pair.symbol1}_{pair.symbol2}"

        # 既存ポジションの確認
        if pair_id in self.positions:
            position = self.positions[pair_id]
            should_close, reason = self.should_exit(signal, position)

            if should_close:
                # クローズ注文
                if position.direction == 'long_spread':
                    orders.append({
                        'symbol': pair.symbol1,
                        'side': 'sell',
                        'size': position.size1,
                        'type': 'market'
                    })
                    orders.append({
                        'symbol': pair.symbol2,
                        'side': 'buy',
                        'size': position.size2,
                        'type': 'market'
                    })
                else:
                    orders.append({
                        'symbol': pair.symbol1,
                        'side': 'buy',
                        'size': position.size1,
                        'type': 'market'
                    })
                    orders.append({
                        'symbol': pair.symbol2,
                        'side': 'sell',
                        'size': position.size2,
                        'type': 'market'
                    })

        elif self.should_enter(signal, pair_id):
            # エントリー注文
            size1, size2 = self.calculate_position_sizes(pair, capital, price1, price2)

            if signal.signal == 'long_spread':
                orders.append({
                    'symbol': pair.symbol1,
                    'side': 'buy',
                    'size': size1,
                    'type': 'market'
                })
                orders.append({
                    'symbol': pair.symbol2,
                    'side': 'sell',
                    'size': size2,
                    'type': 'market'
                })
            elif signal.signal == 'short_spread':
                orders.append({
                    'symbol': pair.symbol1,
                    'side': 'sell',
                    'size': size1,
                    'type': 'market'
                })
                orders.append({
                    'symbol': pair.symbol2,
                    'side': 'buy',
                    'size': size2,
                    'type': 'market'
                })

        return orders

    def get_status(self) -> Dict:
        """
        戦略ステータスを取得

        Returns:
            ステータス辞書
        """
        return {
            'active_positions': len(self.positions),
            'cointegrated_pairs': len(self.cointegrated_pairs),
            'positions': [
                {
                    'pair_id': p.pair_id,
                    'direction': p.direction,
                    'unrealized_pnl': p.unrealized_pnl,
                    'entry_z_score': p.entry_z_score
                }
                for p in self.positions.values()
            ],
            'pairs': [
                {
                    'symbols': f"{p.symbol1}/{p.symbol2}",
                    'p_value': p.p_value,
                    'half_life': p.half_life
                }
                for p in self.cointegrated_pairs
            ]
        }


def create_pair_trading_strategy(
    z_score_entry: float = 2.0,
    z_score_exit: float = 0.5,
    position_size_pct: float = 0.1
) -> PairTradingStrategy:
    """
    PairTradingStrategyを作成

    Args:
        z_score_entry: エントリーZスコア
        z_score_exit: エグジットZスコア
        position_size_pct: ポジションサイズ割合

    Returns:
        PairTradingStrategyインスタンス
    """
    config = PairTradingConfig(
        z_score_entry=z_score_entry,
        z_score_exit=z_score_exit,
        position_size_pct=position_size_pct
    )
    return PairTradingStrategy(config)
