"""パフォーマンストラッカー - 取引パフォーマンスの記録・分析

勝率、損益、Sharpe比率、最大ドローダウンなどを自動計算
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.storage.sqlite_manager import SQLiteManager

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """パフォーマンストラッカークラス"""

    def __init__(self, db_manager: Optional[SQLiteManager] = None):
        """
        Args:
            db_manager: データベースマネージャー
        """
        self.db_manager = db_manager or SQLiteManager()

    def get_all_trades(self) -> pd.DataFrame:
        """
        全取引履歴を取得

        Returns:
            取引履歴のDataFrame
        """
        try:
            trades = self.db_manager.get_trades(limit=10000)  # 最大10000件

            if not trades:
                return pd.DataFrame()

            df = pd.DataFrame(trades)
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            return df
        except Exception as e:
            logger.error(f"取引履歴取得失敗: {e}")
            return pd.DataFrame()

    def calculate_metrics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict:
        """
        パフォーマンスメトリクスを計算

        Args:
            start_date: 開始日時（None=全期間）
            end_date: 終了日時（None=現在まで）

        Returns:
            メトリクス辞書
        """
        df = self.get_all_trades()

        if df.empty:
            return self._empty_metrics()

        # 期間フィルタ
        if start_date:
            df = df[df['timestamp'] >= start_date]
        if end_date:
            df = df[df['timestamp'] <= end_date]

        if df.empty:
            return self._empty_metrics()

        # 基本メトリクス
        total_trades = len(df)
        winning_trades = len(df[df['pnl'] > 0])
        losing_trades = len(df[df['pnl'] < 0])

        total_pnl = df['pnl'].sum()
        total_fees = df['fee'].sum()
        net_pnl = total_pnl - total_fees

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        # 平均損益
        avg_win = df[df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0.0
        avg_loss = df[df['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0.0

        # プロフィット率（平均利益 / 平均損失）
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        # 最大ドローダウン
        cumulative_pnl = df['pnl'].cumsum()
        running_max = cumulative_pnl.cummax()
        drawdown = cumulative_pnl - running_max
        max_drawdown = drawdown.min()
        max_drawdown_pct = (max_drawdown / running_max[drawdown.idxmin()] * 100) if max_drawdown < 0 else 0.0

        # Sharpe比率（リターンの標準偏差に対するリターンの比率）
        if len(df) > 1:
            returns = df['pnl'] / df['cost']  # リターン率
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # 最長連勝・連敗
        streak_win, streak_loss = self._calculate_streaks(df)

        # 期間
        if not df.empty:
            period_days = (df['timestamp'].max() - df['timestamp'].min()).days + 1
        else:
            period_days = 0

        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_fees': total_fees,
            'net_pnl': net_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'max_drawdown_pct': max_drawdown_pct,
            'sharpe_ratio': sharpe_ratio,
            'max_win_streak': streak_win,
            'max_loss_streak': streak_loss,
            'period_days': period_days,
            'start_date': df['timestamp'].min() if not df.empty else None,
            'end_date': df['timestamp'].max() if not df.empty else None
        }

    def _empty_metrics(self) -> Dict:
        """空のメトリクスを返す"""
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'total_pnl': 0.0,
            'total_fees': 0.0,
            'net_pnl': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'profit_factor': 0.0,
            'max_drawdown': 0.0,
            'max_drawdown_pct': 0.0,
            'sharpe_ratio': 0.0,
            'max_win_streak': 0,
            'max_loss_streak': 0,
            'period_days': 0,
            'start_date': None,
            'end_date': None
        }

    def _calculate_streaks(self, df: pd.DataFrame) -> Tuple[int, int]:
        """
        最長連勝・連敗を計算

        Args:
            df: 取引履歴DataFrame

        Returns:
            (最長連勝, 最長連敗)
        """
        if df.empty:
            return 0, 0

        wins = (df['pnl'] > 0).astype(int)

        max_win_streak = 0
        max_loss_streak = 0
        current_win_streak = 0
        current_loss_streak = 0

        for win in wins:
            if win:
                current_win_streak += 1
                current_loss_streak = 0
                max_win_streak = max(max_win_streak, current_win_streak)
            else:
                current_loss_streak += 1
                current_win_streak = 0
                max_loss_streak = max(max_loss_streak, current_loss_streak)

        return max_win_streak, max_loss_streak

    def get_daily_performance(self, days: int = 30) -> pd.DataFrame:
        """
        日次パフォーマンスを取得

        Args:
            days: 過去何日分（デフォルト: 30日）

        Returns:
            日次パフォーマンスのDataFrame
        """
        df = self.get_all_trades()

        if df.empty:
            return pd.DataFrame()

        # 過去N日分のデータ
        cutoff_date = datetime.now() - timedelta(days=days)
        df = df[df['timestamp'] >= cutoff_date]

        if df.empty:
            return pd.DataFrame()

        # 日付でグループ化
        df['date'] = df['timestamp'].dt.date
        daily = df.groupby('date').agg({
            'pnl': ['sum', 'count'],
            'fee': 'sum'
        }).reset_index()

        daily.columns = ['date', 'pnl', 'trades', 'fees']
        daily['net_pnl'] = daily['pnl'] - daily['fees']
        daily['cumulative_pnl'] = daily['net_pnl'].cumsum()

        return daily

    def get_monthly_performance(self, months: int = 12) -> pd.DataFrame:
        """
        月次パフォーマンスを取得

        Args:
            months: 過去何ヶ月分（デフォルト: 12ヶ月）

        Returns:
            月次パフォーマンスのDataFrame
        """
        df = self.get_all_trades()

        if df.empty:
            return pd.DataFrame()

        # 過去Nヶ月分のデータ
        cutoff_date = datetime.now() - timedelta(days=months*30)
        df = df[df['timestamp'] >= cutoff_date]

        if df.empty:
            return pd.DataFrame()

        # 月でグループ化
        df['month'] = df['timestamp'].dt.to_period('M')
        monthly = df.groupby('month').agg({
            'pnl': ['sum', 'count'],
            'fee': 'sum'
        }).reset_index()

        monthly.columns = ['month', 'pnl', 'trades', 'fees']
        monthly['net_pnl'] = monthly['pnl'] - monthly['fees']
        monthly['cumulative_pnl'] = monthly['net_pnl'].cumsum()
        monthly['month'] = monthly['month'].astype(str)

        return monthly

    def print_performance_report(self, period: str = 'all'):
        """
        パフォーマンスレポートを表示

        Args:
            period: 期間（'all', 'daily', 'weekly', 'monthly'）
        """
        if period == 'all':
            metrics = self.calculate_metrics()
        elif period == 'daily':
            metrics = self.calculate_metrics(start_date=datetime.now() - timedelta(days=1))
        elif period == 'weekly':
            metrics = self.calculate_metrics(start_date=datetime.now() - timedelta(days=7))
        elif period == 'monthly':
            metrics = self.calculate_metrics(start_date=datetime.now() - timedelta(days=30))
        else:
            metrics = self.calculate_metrics()

        print("\n" + "=" * 60)
        print(f"パフォーマンスレポート ({period.upper()})")
        print("=" * 60)

        print(f"\n📊 取引統計:")
        print(f"  総取引数: {metrics['total_trades']}回")
        print(f"  勝ちトレード: {metrics['winning_trades']}回")
        print(f"  負けトレード: {metrics['losing_trades']}回")
        print(f"  勝率: {metrics['win_rate']:.2f}%")

        print(f"\n💰 損益:")
        print(f"  総損益: ¥{metrics['total_pnl']:,.0f}")
        print(f"  手数料: ¥{metrics['total_fees']:,.0f}")
        print(f"  純損益: ¥{metrics['net_pnl']:,.0f}")
        print(f"  平均利益: ¥{metrics['avg_win']:,.0f}")
        print(f"  平均損失: ¥{metrics['avg_loss']:,.0f}")

        print(f"\n📈 リスク指標:")
        print(f"  プロフィット率: {metrics['profit_factor']:.2f}")
        print(f"  最大ドローダウン: ¥{metrics['max_drawdown']:,.0f} ({metrics['max_drawdown_pct']:.2f}%)")
        print(f"  Sharpe比率: {metrics['sharpe_ratio']:.2f}")

        print(f"\n🔁 連勝・連敗:")
        print(f"  最長連勝: {metrics['max_win_streak']}回")
        print(f"  最長連敗: {metrics['max_loss_streak']}回")

        if metrics['start_date']:
            print(f"\n📅 期間:")
            print(f"  開始: {metrics['start_date'].strftime('%Y-%m-%d')}")
            print(f"  終了: {metrics['end_date'].strftime('%Y-%m-%d')}")
            print(f"  日数: {metrics['period_days']}日")

        print("=" * 60 + "\n")


# テスト実行
if __name__ == "__main__":
    tracker = PerformanceTracker()
    tracker.print_performance_report('all')
