"""バックテストエンジン

過去データを使ってモデルのパフォーマンスを評価
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class BacktestEngine:
    """バックテストエンジン"""

    def __init__(
        self,
        initial_capital: float = 200000.0,  # 初期資金20万円
        position_size: float = 0.95,  # ポジションサイズ（資金の95%）
        commission_rate: float = 0.0015,  # 手数料率（bitFlyer: 0.15%）
        slippage_rate: float = 0.0005,  # スリッページ（0.05%）
        allow_short: bool = False  # ショートポジション許可（現物では不可）
    ):
        """
        初期化

        Args:
            initial_capital: 初期資金
            position_size: ポジションサイズ（0-1）
            commission_rate: 手数料率
            slippage_rate: スリッページ率
            allow_short: ショートポジションを許可するか（FX以外の現物では不可）
        """
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.allow_short = allow_short

        # バックテスト結果
        self.trades = []
        self.equity_curve = []
        self.current_position = None
        self.cash = initial_capital
        self.equity = initial_capital

        logger.info("バックテストエンジン初期化")
        logger.info(f"  - 初期資金: ¥{initial_capital:,.0f}")
        logger.info(f"  - ポジションサイズ: {position_size:.1%}")
        logger.info(f"  - 手数料率: {commission_rate:.2%}")
        logger.info(f"  - ショート許可: {'はい' if allow_short else 'いいえ（現物モード）'}")

    def run_backtest(
        self,
        df: pd.DataFrame,
        signals: np.ndarray,
        prices: Optional[np.ndarray] = None
    ) -> Dict:
        """
        バックテストを実行

        Args:
            df: 価格データ
            signals: 売買シグナル配列（1=買い, -1=売り, 0=ホールド）
            prices: 価格配列（Noneの場合はdf['close']を使用）

        Returns:
            バックテスト結果の辞書
        """
        logger.info("バックテスト開始")

        # 初期化
        self.trades = []
        self.equity_curve = []
        self.current_position = None
        self.cash = self.initial_capital
        self.equity = self.initial_capital

        # 価格データ
        if prices is None:
            prices = df['close'].values

        # データサイズ調整
        min_len = min(len(signals), len(prices))
        signals = signals[:min_len]
        prices = prices[:min_len]

        # シグナルごとに処理
        for i in range(len(signals)):
            signal = signals[i]
            price = prices[i]

            # ポジション管理
            if signal == 1 and self.current_position is None:
                # 買いシグナル & ポジションなし → 買い注文
                self._open_position('BUY', price, i)

            elif signal == -1 and self.current_position is None:
                # 売りシグナル & ポジションなし
                if self.allow_short:
                    # ショート許可時のみ売り注文（FXモード）
                    self._open_position('SELL', price, i)
                # 現物モードでは売りシグナルでポジションなしの場合は何もしない

            elif signal == -1 and self.current_position and self.current_position['side'] == 'BUY':
                # 売りシグナル & 買いポジション保有 → 決済
                self._close_position(price, i)

            elif signal == 1 and self.current_position and self.current_position['side'] == 'SELL':
                # 買いシグナル & 売りポジション保有 → 決済
                self._close_position(price, i)

            # エクイティカーブ記録
            current_equity = self._calculate_equity(price)
            self.equity_curve.append({
                'index': i,
                'price': price,
                'cash': self.cash,
                'equity': current_equity,
                'position': self.current_position['side'] if self.current_position else None
            })

        # 最後にポジションが残っている場合は決済
        if self.current_position:
            self._close_position(prices[-1], len(prices) - 1)

        # 結果集計
        results = self._calculate_metrics()

        logger.info(f"バックテスト完了: {len(self.trades)}回取引")

        return results

    def _open_position(self, side: str, price: float, index: int):
        """ポジションを開く"""
        # 取引金額
        trade_amount = self.cash * self.position_size

        # スリッページ考慮
        if side == 'BUY':
            exec_price = price * (1 + self.slippage_rate)
        else:  # SELL
            exec_price = price * (1 - self.slippage_rate)

        # エントリー時手数料
        entry_commission = trade_amount * self.commission_rate

        # 手数料を差し引いた金額でポジション数量を計算
        net_trade_amount = trade_amount - entry_commission
        quantity = net_trade_amount / exec_price

        # ポジション記録
        self.current_position = {
            'side': side,
            'entry_price': exec_price,
            'entry_index': index,
            'quantity': quantity,
            'entry_commission': entry_commission,
            'trade_amount': trade_amount
        }

        # キャッシュ更新（手数料込みの取引金額を差し引く）
        self.cash -= trade_amount

        logger.debug(f"ポジションオープン: {side} {quantity:.4f}単位 @ ¥{exec_price:,.0f} (手数料: ¥{entry_commission:,.0f})")

    def _close_position(self, price: float, index: int):
        """ポジションを閉じる"""
        if not self.current_position:
            return

        # スリッページ考慮
        if self.current_position['side'] == 'BUY':
            exec_price = price * (1 - self.slippage_rate)
        else:  # SELL
            exec_price = price * (1 + self.slippage_rate)

        quantity = self.current_position['quantity']
        trade_value = quantity * exec_price
        exit_commission = trade_value * self.commission_rate

        # 損益計算（エントリー・エグジット両方の手数料を考慮）
        entry_commission = self.current_position['entry_commission']
        if self.current_position['side'] == 'BUY':
            gross_pnl = (exec_price - self.current_position['entry_price']) * quantity
        else:  # SELL
            gross_pnl = (self.current_position['entry_price'] - exec_price) * quantity

        # 総手数料を差し引いた純損益
        total_commission = entry_commission + exit_commission
        pnl = gross_pnl - exit_commission  # エントリー手数料は既にtrade_amountから差し引き済み

        # キャッシュ更新（決済金額から決済手数料を差し引く）
        self.cash += trade_value - exit_commission

        # 取引記録
        trade_record = {
            'side': self.current_position['side'],
            'entry_price': self.current_position['entry_price'],
            'exit_price': exec_price,
            'entry_index': self.current_position['entry_index'],
            'exit_index': index,
            'quantity': quantity,
            'pnl': pnl,
            'pnl_pct': (pnl / self.current_position['trade_amount']) * 100,  # 投資額に対する損益率
            'holding_period': index - self.current_position['entry_index'],
            'total_commission': total_commission
        }

        self.trades.append(trade_record)

        logger.debug(f"ポジションクローズ: {self.current_position['side']} @ ¥{exec_price:,.0f}, PnL=¥{pnl:,.0f} (手数料: ¥{total_commission:,.0f})")

        # ポジションクリア
        self.current_position = None

    def _calculate_equity(self, current_price: float) -> float:
        """現在のエクイティを計算"""
        equity = self.cash

        if self.current_position:
            quantity = self.current_position['quantity']

            if self.current_position['side'] == 'BUY':
                # 買いポジション: 現在価格で評価
                equity += quantity * current_price
            else:  # SELL
                # 売りポジション: 損益を反映
                unrealized_pnl = (self.current_position['entry_price'] - current_price) * quantity
                equity += unrealized_pnl

        return equity

    def _calculate_metrics(self) -> Dict:
        """パフォーマンス指標を計算"""
        if len(self.trades) == 0:
            return {
                'total_trades': 0,
                'final_equity': self.initial_capital,
                'total_return': 0.0,
                'total_return_pct': 0.0
            }

        # 基本指標
        total_trades = len(self.trades)
        final_equity = self.equity_curve[-1]['equity'] if self.equity_curve else self.initial_capital
        total_return = final_equity - self.initial_capital
        total_return_pct = (total_return / self.initial_capital) * 100

        # 勝ち/負けトレード
        winning_trades = [t for t in self.trades if t['pnl'] > 0]
        losing_trades = [t for t in self.trades if t['pnl'] <= 0]

        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0

        # 平均損益
        avg_win = np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t['pnl'] for t in losing_trades]) if losing_trades else 0

        # プロフィットファクター
        total_profit = sum([t['pnl'] for t in winning_trades])
        total_loss = abs(sum([t['pnl'] for t in losing_trades]))
        profit_factor = total_profit / total_loss if total_loss > 0 else 0

        # 最大ドローダウン
        equity_values = [e['equity'] for e in self.equity_curve]
        max_dd, max_dd_pct = self._calculate_max_drawdown(equity_values)

        # シャープレシオ（簡易版）
        returns = [t['pnl_pct'] for t in self.trades]
        sharpe_ratio = (np.mean(returns) / np.std(returns)) if len(returns) > 1 and np.std(returns) > 0 else 0

        results = {
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'total_profit': total_profit,
            'total_loss': total_loss,
            'final_equity': final_equity,
            'total_return': total_return,
            'total_return_pct': total_return_pct,
            'max_drawdown': max_dd,
            'max_drawdown_pct': max_dd_pct,
            'sharpe_ratio': sharpe_ratio,
            'avg_holding_period': np.mean([t['holding_period'] for t in self.trades]),
            'trades': self.trades,
            'equity_curve': self.equity_curve
        }

        return results

    def _calculate_max_drawdown(self, equity_values: List[float]) -> Tuple[float, float]:
        """最大ドローダウンを計算"""
        if not equity_values:
            return 0.0, 0.0

        peak = equity_values[0]
        max_dd = 0.0
        max_dd_pct = 0.0

        for value in equity_values:
            if value > peak:
                peak = value

            dd = peak - value
            dd_pct = (dd / peak) * 100 if peak > 0 else 0

            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct

        return max_dd, max_dd_pct

    def print_summary(self, results: Dict):
        """結果サマリーを表示"""
        print("\n" + "=" * 60)
        print("バックテスト結果サマリー")
        print("=" * 60)

        print(f"\n【基本指標】")
        print(f"  総取引回数:        {results['total_trades']}回")
        print(f"  勝ちトレード:      {results['winning_trades']}回")
        print(f"  負けトレード:      {results['losing_trades']}回")
        print(f"  勝率:              {results['win_rate']:.2%}")

        print(f"\n【損益】")
        print(f"  初期資金:          ¥{self.initial_capital:,.0f}")
        print(f"  最終資金:          ¥{results['final_equity']:,.0f}")
        print(f"  総損益:            ¥{results['total_return']:,.0f}")
        print(f"  リターン:          {results['total_return_pct']:.2f}%")

        print(f"\n【トレード詳細】")
        print(f"  総利益:            ¥{results['total_profit']:,.0f}")
        print(f"  総損失:            ¥{results['total_loss']:,.0f}")
        print(f"  平均勝ちトレード:  ¥{results['avg_win']:,.0f}")
        print(f"  平均負けトレード:  ¥{results['avg_loss']:,.0f}")
        print(f"  プロフィット率:    {results['profit_factor']:.2f}")

        print(f"\n【リスク指標】")
        print(f"  最大ドローダウン:  ¥{results['max_drawdown']:,.0f} ({results['max_drawdown_pct']:.2f}%)")
        print(f"  シャープレシオ:    {results['sharpe_ratio']:.2f}")
        print(f"  平均保有期間:      {results['avg_holding_period']:.1f}期間")

        print("=" * 60 + "\n")


# ヘルパー関数
def create_backtest_engine(
    initial_capital: float = 200000.0,
    position_size: float = 0.95,
    commission_rate: float = 0.0015,
    allow_short: bool = False
) -> BacktestEngine:
    """
    バックテストエンジンを作成

    Args:
        initial_capital: 初期資金
        position_size: ポジションサイズ
        commission_rate: 手数料率
        allow_short: ショートポジションを許可するか（デフォルト: False = 現物モード）

    Returns:
        BacktestEngineインスタンス
    """
    return BacktestEngine(
        initial_capital=initial_capital,
        position_size=position_size,
        commission_rate=commission_rate,
        allow_short=allow_short
    )
